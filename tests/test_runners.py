"""Runner contracts tested using temporary fixtures, never benchmark test errors."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_presidio, run_spacy
from scripts.runner_common import (document_id, load_doc_text, load_ground_truth,
                                   require_custom_freeze, run_documents, write_json)
from scripts.validate_predictions import main as validate_main, validate_file


class TestRunners(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.docs = []
        for index in range(6):
            file = f"doc{index}.txt"
            (self.raw / file).write_text(f"text{index}", encoding="utf-8")
            self.docs.append({"doc_id": f"id{index}", "file": f"data/raw/{file}",
                              "split": "test" if index == 0 else "dev"})
        self.gt = self.root / "gt.json"
        write_json(self.gt, self.docs)
        self.pred = self.root / "pred.json"
        self.good = {"id0": {"spans": [{"label": "RAW", "start": 0, "end": 5}], "ms": 1.0}}
        write_json(self.pred, self.good)

    def test_validator_good_file(self):
        self.assertEqual(validate_file(self.pred, "test", self.gt, self.raw), {"RAW": 1})

    def test_validator_missing_document(self):
        write_json(self.pred, {})
        with self.assertRaisesRegex(ValueError, "coverage"):
            validate_file(self.pred, "test", self.gt, self.raw)

    def test_validator_extra_document(self):
        self.good["extra"] = self.good["id0"]
        write_json(self.pred, self.good)
        with self.assertRaisesRegex(ValueError, "coverage"):
            validate_file(self.pred, "test", self.gt, self.raw)

    def test_validator_out_of_range(self):
        self.good["id0"]["spans"][0]["end"] = 6
        write_json(self.pred, self.good)
        with self.assertRaisesRegex(ValueError, "bounds"):
            validate_file(self.pred, "test", self.gt, self.raw)

    def test_validator_bad_types(self):
        for field, value in (("label", 1), ("start", True), ("end", 0)):
            with self.subTest(field=field):
                value_copy = json.loads(json.dumps(self.good))
                value_copy["id0"]["spans"][0][field] = value
                write_json(self.pred, value_copy)
                with self.assertRaises(ValueError):
                    validate_file(self.pred, "test", self.gt, self.raw)
        self.good["id0"]["ms"] = 1
        write_json(self.pred, self.good)
        with self.assertRaisesRegex(ValueError, "float"):
            validate_file(self.pred, "test", self.gt, self.raw)

    def test_validator_duplicate_key(self):
        self.pred.write_text('{"id0": {}, "id0": {}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_file(self.pred, "test", self.gt, self.raw)

    def test_validator_failure_exit(self):
        write_json(self.pred, {})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate_main([str(self.pred), "--split", "test",
                "--ground-truth", str(self.gt), "--raw-dir", str(self.raw)]), 1)

    def test_split_rejection_before_loading(self):
        for main in (run_spacy.main, run_presidio.main):
            with self.subTest(main=main.__module__), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main(["--splits", "validation"])
                self.assertEqual(error.exception.code, 2)

    def test_freeze_missing(self):
        with self.assertRaisesRegex(ValueError, "freeze"):
            require_custom_freeze(self.root / "missing.json", self.gt)

    def test_freeze_hash_mismatch(self):
        freeze = self.root / "freeze.json"
        write_json(freeze, {"sha256": "wrong"})
        with self.assertRaisesRegex(ValueError, "mismatch"):
            require_custom_freeze(freeze, self.gt)

    def test_freeze_hash_matches(self):
        freeze = self.root / "freeze.json"
        write_json(freeze, {"sha256": hashlib.sha256(self.gt.read_bytes()).hexdigest()})
        require_custom_freeze(freeze, self.gt)

    def test_custom_test_guard_precedes_loading(self):
        with patch.object(run_presidio, "require_custom_freeze", side_effect=ValueError("no freeze")):
            with patch.object(run_presidio, "build_analyzer") as build:
                with self.assertRaisesRegex(ValueError, "no freeze"):
                    run_presidio.main(["--config", "custom", "--splits", "dev", "test"])
                build.assert_not_called()

    def test_ng_phone_preserves_default_registry_and_small_model(self):
        from types import SimpleNamespace
        sentinel = object()
        recognizers = [sentinel]
        analyzer = SimpleNamespace(registry=SimpleNamespace(add_recognizer=recognizers.append))
        with patch("presidio_analyzer.nlp_engine.NlpEngineProvider") as provider:
            with patch("presidio_analyzer.AnalyzerEngine", return_value=analyzer):
                self.assertIs(run_presidio.build_analyzer("ng_phone"), analyzer)
        configuration = provider.call_args.kwargs["nlp_configuration"]
        self.assertEqual(configuration, {"nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}]})
        self.assertIs(recognizers[0], sentinel)
        self.assertEqual(recognizers[1].supported_regions, ["NG"])
        import tldextract
        with patch("requests.Session.request", side_effect=AssertionError("Network forbidden")):
            self.assertEqual(tldextract.extract("example.com").suffix, "com")

    def test_authoritative_raw_dir(self):
        from scripts.runner_common import ROOT
        doc = {"file": str(Path(__file__).resolve().relative_to(ROOT))}
        (self.raw / "test_runners.py").write_text("override", encoding="utf-8")
        self.assertEqual(load_doc_text(doc, self.raw), "override")

    def test_exact_ids_sorted_and_duplicates_rejected(self):
        write_json(self.gt, list(reversed(self.docs)))
        self.assertEqual([document_id(d) for d in load_ground_truth(self.gt)],
                         [f"id{i}" for i in range(6)])
        write_json(self.gt, [self.docs[0], self.docs[0]])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            load_ground_truth(self.gt)

    def test_legacy_file_id_preserves_exact_value(self):
        self.assertEqual(document_id({"file": "data/raw/example.txt"}), "data/raw/example.txt")
        self.assertEqual(document_id({"doc_id": "EXACT-ID", "file": "other.txt"}), "EXACT-ID")
        with self.assertRaises(ValueError):
            document_id({"doc_id": "", "file": "other.txt"})

    def test_dev_only_warmup_timing_raw_labels_and_lf(self):
        calls = []
        def analyze(text):
            calls.append(text)
            return [{"label": "UNMAPPED", "start": 0, "end": 1}]
        with patch("scripts.runner_common.time.perf_counter", side_effect=[10.0, 10.025]):
            with contextlib.redirect_stdout(io.StringIO()):
                paths = run_documents(self.docs, ["test"], self.raw, self.root, "fixture", analyze, list)
        self.assertEqual(calls, [f"text{i}" for i in (1, 2, 3, 4, 5, 0)])
        data = json.loads(paths[0].read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"id0"})
        self.assertAlmostEqual(data["id0"]["ms"], 25.0)
        self.assertEqual(data["id0"]["spans"][0]["label"], "UNMAPPED")
        self.assertNotIn(b"\r", paths[0].read_bytes())

    def test_outputs_are_separate_per_split(self):
        with contextlib.redirect_stdout(io.StringIO()):
            paths = run_documents(self.docs, ["dev", "test"], self.raw, self.root,
                                  "fixture", lambda text: [], list)
        self.assertEqual([path.name for path in paths], ["fixture__dev.json", "fixture__test.json"])
        self.assertEqual(len(json.loads(paths[0].read_text())), 5)
        self.assertEqual(len(json.loads(paths[1].read_text())), 1)


if __name__ == "__main__":
    unittest.main()
