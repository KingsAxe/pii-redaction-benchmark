"""Hand-built report diagnostics, independent of benchmark test records."""
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.analysis_common import id_diagnostics
from scripts.evaluate import (CONFIGS, error_records, main as evaluate_main, measured_latency,
                              result_row, write_reports)
from scripts.metrics import score
from scripts.runner_common import write_json


class TestDiagnostics(unittest.TestCase):
    def test_domain_over_redaction_and_exposure_exports_use_scorer_outputs(self):
        docs = [{"file": "alpha", "split": "test", "doc_type": "alpha", "length": 12,
                 "entities": [{"type": "PERSON", "start": start, "end": start + 2}
                              for start in (0, 4, 8)], "decoys": []},
                {"file": "beta", "split": "test", "doc_type": "beta", "length": 12,
                 "entities": [{"type": "PERSON", "start": 0, "end": 2}], "decoys": []}]
        predictions = {"alpha": {"ms": 1.0, "spans": [
            {"label": "PERSON", "start": 0, "end": 1},
            {"label": "PERSON", "start": 4, "end": 6},
            {"label": "ID", "start": 10, "end": 12}]},
            "beta": {"ms": 2.0, "spans": [{"label": "PERSON", "start": 0, "end": 2}]}}
        metrics = score(docs, predictions, split="test")
        row = result_row("fixture", metrics, id_diagnostics(docs, predictions, "test", metrics),
                         measured_latency(docs, predictions))
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_reports(output, [row], {"fixture": {"phase2": metrics, "errors": []}})
            with (output / "results.csv").open(encoding="utf-8", newline="") as handle:
                exported = next(csv.DictReader(handle))
            for domain, value in metrics["leak_rate"]["per_doc_type"].items():
                self.assertEqual(float(exported[f"leak_rate_domain_{domain}"]), value)
            self.assertEqual(float(exported["over_redaction_rate"]), metrics["over_redaction"]["rate"])
            for field, source in (("fully_uncovered_entities", "fully_leaked_count"),
                                  ("partially_exposed_entities", "partially_exposed_count"),
                                  ("total_entities", "total_entities")):
                self.assertEqual(int(exported[field]), metrics["entity_exposure"][source])
            markdown = (output / "results.md").read_text(encoding="utf-8")
            self.assertIn("## Character leak by document domain", markdown)
            self.assertIn("| Config | alpha | beta |", markdown)
            domain_values = [f"{100 * metrics['leak_rate']['per_doc_type'][domain]:.2f}%"
                             for domain in ("alpha", "beta")]
            self.assertIn("| fixture | " + " | ".join(domain_values) + " |", markdown)
            exposure = metrics["entity_exposure"]
            self.assertIn(f"| fixture | {100 * metrics['over_redaction']['rate']:.2f}% | "
                          f"{exposure['fully_leaked_count']} | {exposure['partially_exposed_count']} | "
                          f"{exposure['total_entities']} | {100 * exposure['exposure_rate']:.2f}% |", markdown)

    def test_id_phone_coverage_partial_exposure_and_unique_decoy_counts(self):
        docs = [{"file": "fixture", "doc_id": "exact", "split": "dev", "doc_type": "fixture", "length": 40,
                 "entities": [{"type": "BVN", "start": a, "end": a + 4, "cued": False}
                              for a in (0, 10, 20)],
                 "decoys": [{"type": "ORDER_ID", "start": 30, "end": 34}]}]
        predictions = {"exact": {"ms": 1.0, "spans": [
            {"label": "PHONE_NUMBER", "start": 0, "end": 4},
            {"label": "ID", "start": 10, "end": 12},
            {"label": "ID", "start": 30, "end": 34},
            {"label": "ID", "start": 30, "end": 34},
            {"label": "UNMAPPED", "start": 20, "end": 24} ]}}
        result = id_diagnostics(docs, predictions, "dev")
        self.assertEqual(result["order_id_decoys_hit_by_id"], 1)
        self.assertEqual(result["id_entities_assigned_phone"], 1)
        self.assertEqual(result["id_entities_fully_uncovered"], 1)
        self.assertEqual(result["id_entities_partially_uncovered"], 1)
        self.assertEqual(result["id_entities_any_uncovered"], 2)
        self.assertEqual(result["id_entities_phone_or_any_uncovered"], 3)
        self.assertEqual(result["id_precision_strict"], 0.0)
        self.assertAlmostEqual(result["id_precision_overlap"], 1 / 3)

    def test_reported_latency_keeps_all_post_warmup_samples(self):
        docs = [{"file": str(i)} for i in range(6)]
        predictions = {str(i): {"ms": float(i + 1)} for i in range(6)}
        result = measured_latency(docs, predictions)
        self.assertEqual(result["measured_doc_count"], 6)
        self.assertEqual(result["median_ms"], 3.5)
        self.assertEqual(result["p95_ms"], 5.75)

    def test_evaluation_refuses_before_reading_test_data(self):
        with patch("scripts.evaluate.require_custom_freeze", side_effect=ValueError("not frozen")):
            with patch("scripts.evaluate.load_ground_truth") as load:
                with self.assertRaisesRegex(ValueError, "not frozen"):
                    evaluate_main([])
                load.assert_not_called()

    def test_reports_use_scorer_and_list_all_decoy_hits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            raw.mkdir()
            docs, predictions = [], {}
            for index in range(6):
                file = f"fixture{index}.txt"
                (raw / file).write_text("1234  5678", encoding="utf-8")
                docs.append({"file": f"data/raw/{file}", "doc_id": f"exact{index}", "split": "test",
                    "doc_type": "fixture", "length": 10,
                    "entities": [{"type": "NIN", "start": 0, "end": 4, "cued": index % 2 == 0}],
                    "decoys": [{"type": "ORDER_ID", "start": 6, "end": 10}]})
                predictions[f"exact{index}"] = {"ms": float(index + 1), "spans": [
                    {"label": "ID", "start": 0, "end": 4}, {"label": "ID", "start": 6, "end": 10}]}
            gt = root / "gt.json"
            write_json(gt, docs)
            prediction_dir = root / "predictions"
            for config in CONFIGS:
                write_json(prediction_dir / f"{config}__test.json", predictions)
            output = root / "reports"
            with patch("scripts.evaluate.require_custom_freeze") as guard:
                with contextlib.redirect_stdout(io.StringIO()):
                    evaluate_main(["--ground-truth", str(gt), "--raw-dir", str(raw),
                                   "--predictions-dir", str(prediction_dir), "--output-dir", str(output)])
                self.assertEqual(guard.call_count, 2)
            with (output / "results.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), len(CONFIGS))
            for row in rows:
                self.assertEqual(float(row["leak_rate"]), 0.0)
                self.assertEqual(float(row["id_precision_strict"]), 0.5)
                self.assertEqual(float(row["id_recall_cued_strict"]), 1.0)
                self.assertEqual(float(row["id_recall_bare_strict"]), 1.0)
                self.assertEqual(int(row["decoy_hit_predictions"]), 6)
                self.assertEqual(float(row["median_ms"]), 3.5)
                self.assertEqual(float(row["scorer_median_ms_after_extra_drop"]), 6.0)
            details = json.loads((output / "evaluation_details.json").read_text(encoding="utf-8"))
            for detail in details["configs"].values():
                self.assertEqual(len(detail["errors"]), 6)
                self.assertTrue(all(record["kind"] == "decoy_hit" for record in detail["errors"]))
            for path in output.iterdir():
                self.assertNotIn(b"\r", path.read_bytes())

    def test_error_categories_include_misses_confusions_partial_and_exposure(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary)
            (raw / "fixture").write_text("x" * 40, encoding="utf-8")
            docs = [{"file": "fixture", "entities": [
                {"type": "PERSON", "start": 0, "end": 4},
                {"type": "BVN", "start": 10, "end": 14},
                {"type": "EMAIL", "start": 30, "end": 34}],
                "decoys": [{"type": "ORDER_ID", "start": 20, "end": 24}]}]
            predictions = {"fixture": {"spans": [
                {"label": "ID", "start": 0, "end": 2},
                {"label": "ID", "start": 10, "end": 12},
                {"label": "ID", "start": 20, "end": 24}]}}
            from collections import Counter
            counts = Counter(record["kind"] for record in error_records(docs, predictions, raw))
            self.assertEqual(counts, {"miss": 1, "type_confusion": 1, "partial_match": 1,
                                      "decoy_hit": 1, "fully_uncovered": 1, "partially_uncovered": 2})


if __name__ == "__main__":
    unittest.main()
