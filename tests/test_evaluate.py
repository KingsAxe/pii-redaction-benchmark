"""Hand-built report diagnostics, independent of benchmark test records."""
import unittest

from scripts.analysis_common import id_diagnostics


class TestDiagnostics(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
