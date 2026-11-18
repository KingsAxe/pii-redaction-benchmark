"""Tiny synthetic fixtures; no benchmark test documents or real model calls."""
import hashlib
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from demo.app import CONFIGURATION, create_app
from demo.masking import MAX_CODE_POINTS


def span(label, start, end):
    return SimpleNamespace(entity_type=label, start=start, end=end)


class FakeAnalyzer:
    def __init__(self, results=None, error=None):
        self.results = [] if results is None else results
        self.error = error
        self.calls = []

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.results


class ServiceTests(unittest.TestCase):
    def client_for(self, analyzer):
        return TestClient(create_app(analyzer_factory=lambda: analyzer, hash_verifier=lambda: "f" * 64))

    def submit(self, client, text="abcdefghij", **extra):
        return client.post("/mask", json={"text": text, "synthetic_input": True, **extra})

    def test_overlapping_mapped_spans_are_unioned_once(self):
        analyzer = FakeAnalyzer([span("PERSON", 1, 6), span("LOCATION", 4, 9)])
        with self.client_for(analyzer) as client:
            response = self.submit(client)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["masked_proposal"], "a########j")
        self.assertEqual(result["detection_counts"]["mapped_span_count"], 2)
        self.assertEqual(result["detection_counts"]["masked_code_point_count"], 8)

    def test_partial_pii_and_non_pii_coverage_do_not_depend_on_assignment(self):
        # Fixture PII is positions 2..6; the predicted phone span covers only
        # positions 4..6 of it, plus non-PII positions 7 and 8.
        with self.client_for(FakeAnalyzer([span("PHONE_NUMBER", 4, 9)])) as client:
            result = self.submit(client).json()
        self.assertEqual(result["masked_proposal"], "abcd#####j")
        self.assertEqual(result["masked_proposal"][2:4], "cd")
        self.assertEqual(result["masked_proposal"][7:9], "##")

    def test_ignored_labels_are_counted_but_not_masked(self):
        with self.client_for(FakeAnalyzer([span("ORG", 0, 10), span("ID", 2, 4)])) as client:
            result = self.submit(client).json()
        self.assertEqual(result["masked_proposal"], "ab##efghij")
        self.assertEqual(result["detection_counts"]["raw_span_count"], 2)
        self.assertEqual(result["detection_counts"]["ignored_span_count"], 1)

    def test_no_detections_still_require_review(self):
        with self.client_for(FakeAnalyzer()) as client:
            result = self.submit(client).json()
        self.assertEqual(result["masked_proposal"], result["canonical_original"])
        self.assertEqual(result["detection_counts"]["raw_span_count"], 0)
        self.assertIs(result["review_required"], True)

    def test_all_unmapped_results_preserve_original(self):
        with self.client_for(FakeAnalyzer([span("UNMAPPED", 0, 10)])) as client:
            result = self.submit(client).json()
        self.assertEqual(result["masked_proposal"], "abcdefghij")
        self.assertEqual(result["detection_counts"]["mapped_span_count"], 0)

    def test_canonical_newlines_and_covered_lf_counts(self):
        analyzer = FakeAnalyzer([span("ID", 0, 6)])
        with self.client_for(analyzer) as client:
            result = self.submit(client, "a\r\nb\rc\n").json()
        self.assertEqual(analyzer.calls, [{"text": "a\nb\nc\n", "language": "en"}])
        self.assertEqual(result["masked_proposal"], "#\n#\n#\n")
        self.assertEqual(result["detection_counts"]["covered_code_point_count"], 6)
        self.assertEqual(result["detection_counts"]["masked_code_point_count"], 3)
        self.assertEqual(result["detection_counts"]["covered_lf_count"], 3)

    def test_non_bmp_combining_characters_and_unicode_offsets(self):
        analyzer = FakeAnalyzer([span("PERSON", 1, 4)])
        with self.client_for(analyzer) as client:
            result = self.submit(client, "A\U0001f600e\u0301\r\nB\rC").json()
        self.assertEqual(result["canonical_original"], "A\U0001f600e\u0301\nB\nC")
        self.assertEqual(result["masked_proposal"], "A###\nB\nC")
        self.assertEqual(len(result["canonical_original"]), len(result["masked_proposal"]))

    def test_input_limit_counts_code_points_not_utf16_units(self):
        with self.client_for(FakeAnalyzer()) as client:
            for character in ("a", "\U0001f600"):
                with self.subTest(character=character):
                    self.assertEqual(self.submit(client, character * MAX_CODE_POINTS).status_code, 200)
                    self.assertEqual(self.submit(client, character * (MAX_CODE_POINTS + 1)).status_code, 422)

    def test_limit_is_applied_before_newline_normalization(self):
        with self.client_for(FakeAnalyzer()) as client:
            response = self.submit(client, "a\r\n" * 7000)
        self.assertEqual(response.status_code, 422)

    def test_invalid_inputs_do_not_echo_submitted_values(self):
        secret = "SYNTHETIC_ERROR_CANARY"
        bodies = [{}, {"text": "", "synthetic_input": True}, {"text": " \r\n", "synthetic_input": True},
                  {"text": secret}, {"text": secret, "synthetic_input": False},
                  {"text": secret, "synthetic_input": "true"}, {"text": secret, "synthetic_input": 1},
                  {"text": 12, "synthetic_input": True}, {"text": None, "synthetic_input": True},
                  {"text": secret, "synthetic_input": True, "configuration": "custom"}]
        with self.client_for(FakeAnalyzer()) as client:
            for body in bodies:
                with self.subTest(body=body):
                    response = client.post("/mask", json=body)
                    self.assertEqual(response.status_code, 422)
                    self.assertNotIn(secret, response.text)
                    self.assertEqual(response.headers["cache-control"], "no-store")

    def test_malformed_json_and_unpaired_surrogate_are_text_free(self):
        with self.client_for(FakeAnalyzer()) as client:
            for body in (b'{"text":"CANARY"', b'{"text":"\\ud800","synthetic_input":true}'):
                response = client.post("/mask", content=body, headers={"Content-Type": "application/json"})
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("CANARY", response.text)
                self.assertNotIn("ud800", response.text)

    def test_invalid_spans_fail_without_a_proposal(self):
        for result in (span("ID", -1, 3), span("ID", 0, 11), span("ID", 3, 3),
                       span("ID", 4, 2), span("ID", True, 4), span("ID", 1.2, 4),
                       span(None, 0, 3), span("UNMAPPED", 0, 11)):
            with self.subTest(span=result), self.client_for(FakeAnalyzer([result])) as client:
                response = self.submit(client, "PRIVATE_TX")
                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json()["detail"]["code"], "invalid_predictions")
                self.assertNotIn("PRIVATE_TX", response.text)
                self.assertNotIn("masked_proposal", response.json())

    def test_analysis_error_has_no_text_in_response_or_logs(self):
        secret = "SYNTHETIC_ANALYSIS_CANARY"
        with self.client_for(FakeAnalyzer(error=RuntimeError(secret))) as client:
            with self.assertNoLogs(level="ERROR"):
                response = self.submit(client, secret)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["code"], "analysis_failed")
        self.assertNotIn(secret, response.text)

    def test_not_ready_health_and_mask_are_unavailable(self):
        with self.client_for(FakeAnalyzer()) as client:
            self.assertTrue(client.get("/health").json()["ready"])
            client.app.state.analyzer = None
            self.assertEqual(client.get("/health").status_code, 503)
            self.assertEqual(self.submit(client).status_code, 503)

    def test_freeze_failure_precedes_construction_and_is_sanitized(self):
        factory = Mock()
        app = create_app(analyzer_factory=factory, hash_verifier=Mock(side_effect=ValueError("CANARY")))
        with self.assertRaises(RuntimeError) as result:
            with TestClient(app):
                pass
        self.assertNotIn("CANARY", str(result.exception))
        factory.assert_not_called()

    def test_actual_hash_mismatch_refuses_startup_without_touching_sources(self):
        factory = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "recognizer.py"
            source.write_text("different synthetic source", encoding="utf-8")
            with patch.dict("demo.app.CUSTOM_SOURCES", {"custom_generic": source}):
                with self.assertRaises(RuntimeError):
                    with TestClient(create_app(analyzer_factory=factory)):
                        pass
        factory.assert_not_called()

    def test_analyzer_startup_failure_is_sanitized(self):
        app = create_app(analyzer_factory=Mock(side_effect=RuntimeError("CANARY")), hash_verifier=lambda: "f" * 64)
        with self.assertRaises(RuntimeError) as result:
            with TestClient(app):
                pass
        self.assertNotIn("CANARY", str(result.exception))

    def test_analyzer_reuse_and_proposal_only_semantics(self):
        analyzer = FakeAnalyzer()
        factory = Mock(return_value=analyzer)
        app = create_app(analyzer_factory=factory)
        with TestClient(app) as client:
            first = self.submit(client, "synthetic").json()
            second = self.submit(client, "synthetic").json()
            self.assertEqual(first["configuration"], CONFIGURATION)
            self.assertEqual(first["document_id"], hashlib.sha256(b"synthetic").hexdigest())
            self.assertEqual(first["revision_id"], second["revision_id"])
            self.assertEqual(len(first["frozen_source_sha256"]), 64)
            self.assertIs(first["review_required"], True)
            self.assertNotIn("approved", first)
            self.assertEqual(client.post("/approve").status_code, 404)
            self.assertEqual(client.get("/final-output").status_code, 404)
            self.assertEqual(client.get("/health").json(), {"ready": True, "configuration": CONFIGURATION})
        factory.assert_called_once_with()
        self.assertEqual(len(analyzer.calls), 2)
        self.assertIsNone(app.state.analyzer)

    def test_health_remains_responsive_during_analysis(self):
        entered, release = threading.Event(), threading.Event()
        analyzer = FakeAnalyzer()
        def blocking_analysis(**kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Fixture release timed out")
            return []
        analyzer.analyze = blocking_analysis
        with self.client_for(analyzer) as client, ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.submit, client)
            try:
                self.assertTrue(entered.wait(3))
                self.assertEqual(client.get("/health").status_code, 200)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=5).status_code, 200)


if __name__ == "__main__":
    unittest.main()
