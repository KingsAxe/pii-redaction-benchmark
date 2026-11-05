"""
test_metrics.py – Unit tests for PII redaction benchmark metrics.

Tests:
  1. perfect match
  2. partial match
  3. complete miss
  4. decoy hit
  5. wrong-type but covering span
  6. two overlapping predictions on one entity
  7. one prediction spanning two adjacent entities
  8. empty predictions
  9. missing prediction raises error
  10. a document with no PII
  11. split guard refuses dev unless explicit
  12. unmapped labels ignored and counted
  13. deterministic tie-break
  14. off-by-one at span ends (end is exclusive)
  15. hand-calculated leak rate and precision/recall
"""

import unittest
from scripts.metrics import (
    DEFAULT_PRED_LABEL_MAP,
    GT_LABEL_MAP,
    match_entities_and_predictions,
    score,
)


class TestMetrics(unittest.TestCase):
    def test_perfect_match(self):
        """Exact span match with identical mapped type."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "hr_intake",
            "split": "test",
            "length": 100,
            "entities": [{"type": "PERSON", "start": 10, "end": 25, "text": "Adebayo Sani"}],
            "decoys": [],
        }]
        preds = {
            "doc1.txt": {
                "spans": [{"label": "PERSON", "start": 10, "end": 25}],
                "ms": 12.0,
            }
        }
        res = score(gt, preds, split="test")

        # Strict & overlap TP
        self.assertEqual(res["metrics_strict"]["PERSON"]["tp"], 1)
        self.assertEqual(res["metrics_strict"]["PERSON"]["fp"], 0)
        self.assertEqual(res["metrics_strict"]["PERSON"]["fn"], 0)
        self.assertAlmostEqual(res["metrics_strict"]["PERSON"]["f1"], 1.0)

        self.assertEqual(res["metrics_overlap"]["PERSON"]["tp"], 1)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["fp"], 0)
        self.assertAlmostEqual(res["metrics_overlap"]["PERSON"]["f1"], 1.0)

        # Leak rate: fully covered -> 0.0
        self.assertAlmostEqual(res["leak_rate"]["overall"], 0.0)
        self.assertEqual(res["entity_exposure"]["fully_leaked_count"], 0)
        self.assertEqual(res["entity_exposure"]["total_exposed_count"], 0)

        # Confusion matrix
        self.assertEqual(res["confusion_matrix"]["PERSON"]["PERSON"], 1)
        self.assertEqual(res["confusion_matrix"]["PERSON"]["NONE"], 0)
        self.assertEqual(res["confusion_matrix"]["NONE"]["PERSON"], 0)

    def test_partial_match(self):
        """Predicted span overlaps ground truth entity, but start/end are not exact."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "hr_intake",
            "split": "test",
            "length": 100,
            "entities": [{"type": "PERSON", "start": 10, "end": 30, "text": "Dr. Ngozi Okafor"}],
            "decoys": [],
        }]
        preds = {
            "doc1.txt": {
                # Only covers "Ngozi Okafor" (start=14, end=30)
                "spans": [{"label": "PERSON", "start": 14, "end": 30}],
                "ms": 10.0,
            }
        }
        res = score(gt, preds, split="test")

        # Strict: not a match (TP=0, FP=1, FN=1)
        self.assertEqual(res["metrics_strict"]["PERSON"]["tp"], 0)
        self.assertEqual(res["metrics_strict"]["PERSON"]["fp"], 1)
        self.assertEqual(res["metrics_strict"]["PERSON"]["fn"], 1)
        self.assertAlmostEqual(res["metrics_strict"]["PERSON"]["f1"], 0.0)

        # Overlap: is a match (TP=1, FP=0, FN=0)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["tp"], 1)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["fp"], 0)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["fn"], 0)
        self.assertAlmostEqual(res["metrics_overlap"]["PERSON"]["f1"], 1.0)

        # Leak rate: 4 uncovered chars out of 20 total -> 4 / 20 = 0.2
        self.assertAlmostEqual(res["leak_rate"]["overall"], 4 / 20)
        self.assertEqual(res["entity_exposure"]["partially_exposed_count"], 1)
        self.assertEqual(res["entity_exposure"]["fully_leaked_count"], 0)

    def test_complete_miss(self):
        """Entity exists in ground truth but no prediction overlaps it."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "health_report",
            "split": "test",
            "length": 50,
            "entities": [{"type": "PHONE", "start": 5, "end": 16, "text": "08031234567"}],
            "decoys": [],
        }]
        preds = {
            "doc1.txt": {
                "spans": [],
                "ms": 8.0,
            }
        }
        res = score(gt, preds, split="test")

        self.assertEqual(res["metrics_strict"]["PHONE"]["tp"], 0)
        self.assertEqual(res["metrics_strict"]["PHONE"]["fn"], 1)
        self.assertEqual(res["metrics_overlap"]["PHONE"]["tp"], 0)
        self.assertEqual(res["metrics_overlap"]["PHONE"]["fn"], 1)

        # 100% leak
        self.assertAlmostEqual(res["leak_rate"]["overall"], 1.0)
        self.assertEqual(res["entity_exposure"]["fully_leaked_count"], 1)
        self.assertEqual(res["confusion_matrix"]["PHONE"]["NONE"], 1)

    def test_decoy_hit(self):
        """Prediction overlaps no PII entity, but overlaps a decoy span."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "vendor_invoice",
            "split": "test",
            "length": 100,
            "entities": [],
            "decoys": [{"type": "ORDER_ID", "start": 20, "end": 31, "text": "08039999999"}],
        }]
        preds = {
            "doc1.txt": {
                "spans": [{"label": "ID", "start": 20, "end": 31}],
                "ms": 15.0,
            }
        }
        res = score(gt, preds, split="test")

        # Counts as false positive in confusion matrix
        self.assertEqual(res["confusion_matrix"]["NONE"]["ID"], 1)
        self.assertEqual(res["metrics_overlap"]["ID"]["fp"], 1)

        # Also reported separately as decoy hit
        self.assertEqual(res["decoys"]["total_hits"], 1)
        self.assertEqual(res["decoys"]["by_decoy_type"]["ORDER_ID"], 1)

    def test_wrong_type_covering_span(self):
        """Prediction covers entity span completely, but has mismatched mapped type."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "health_report",
            "split": "test",
            "length": 100,
            "entities": [{"type": "PERSON", "start": 10, "end": 25, "text": "Adebayo Sani"}],
            "decoys": [],
        }]
        # spaCy GPE maps to ADDRESS, not PERSON
        preds = {
            "doc1.txt": {
                "spans": [{"label": "GPE", "start": 10, "end": 25}],
                "ms": 10.0,
            }
        }
        res = score(gt, preds, split="test")

        # Neither strict nor overlap TP for PERSON or ADDRESS
        self.assertEqual(res["metrics_strict"]["PERSON"]["tp"], 0)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["tp"], 0)
        self.assertEqual(res["metrics_strict"]["ADDRESS"]["tp"], 0)
        self.assertEqual(res["metrics_overlap"]["ADDRESS"]["tp"], 0)

        # Type confusion in confusion matrix
        self.assertEqual(res["confusion_matrix"]["PERSON"]["ADDRESS"], 1)

        # But character leak rate is type-agnostic: chars are covered -> 0.0 leak rate!
        self.assertAlmostEqual(res["leak_rate"]["overall"], 0.0)
        self.assertEqual(res["entity_exposure"]["fully_leaked_count"], 0)

    def test_two_overlapping_predictions_on_one_entity(self):
        """Two predictions overlap the same entity: 1-to-1 greedy matching picks only one."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "hr_intake",
            "split": "test",
            "length": 100,
            "entities": [{"type": "PERSON", "start": 10, "end": 30, "text": "Dr. Ngozi Okafor"}],
            "decoys": [],
        }]
        preds = {
            "doc1.txt": {
                "spans": [
                    # Span A: 10..30 (exact 20-char overlap)
                    {"label": "PERSON", "start": 10, "end": 30},
                    # Span B: 10..20 (10-char overlap)
                    {"label": "PERSON", "start": 10, "end": 20},
                ],
                "ms": 14.0,
            }
        }
        res = score(gt, preds, split="test")

        # Only 1 true positive matched; second prediction is a false positive
        self.assertEqual(res["metrics_strict"]["PERSON"]["tp"], 1)
        self.assertEqual(res["metrics_strict"]["PERSON"]["fp"], 1)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["tp"], 1)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["fp"], 1)
        self.assertEqual(res["confusion_matrix"]["PERSON"]["PERSON"], 1)
        self.assertEqual(res["confusion_matrix"]["NONE"]["PERSON"], 1)

    def test_one_prediction_spanning_two_adjacent_entities(self):
        """One prediction covers spans of two separate entities: matches at most one entity."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "vendor_invoice",
            "split": "test",
            "length": 100,
            "entities": [
                # Entity 1: length 10
                {"type": "PERSON", "start": 10, "end": 20, "text": "Ngozi Okafor"},
                # Entity 2: length 15
                {"type": "PERSON", "start": 25, "end": 40, "text": "Adebayo Sani"},
            ],
            "decoys": [],
        }]
        preds = {
            "doc1.txt": {
                # Spans from 10 to 40 (covers both, but overlaps Entity 2 by 15 chars, Entity 1 by 10 chars)
                "spans": [{"label": "PERSON", "start": 10, "end": 40}],
                "ms": 11.0,
            }
        }
        res = score(gt, preds, split="test")

        # Greedy match matches Entity 2 (overlap 15 > 10). Entity 1 is missed.
        self.assertEqual(res["metrics_overlap"]["PERSON"]["tp"], 1)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["fn"], 1)
        self.assertEqual(res["confusion_matrix"]["PERSON"]["PERSON"], 1)
        self.assertEqual(res["confusion_matrix"]["PERSON"]["NONE"], 1)

    def test_empty_predictions(self):
        """Empty predictions dictionary."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "hr_intake",
            "split": "test",
            "length": 50,
            "entities": [{"type": "EMAIL", "start": 10, "end": 25, "text": "test@domain.ng"}],
            "decoys": [],
        }]
        preds = {
            "doc1.txt": {"spans": [], "ms": 5.0}
        }
        res = score(gt, preds, split="test")

        self.assertEqual(res["metrics_overlap"]["EMAIL"]["tp"], 0)
        self.assertEqual(res["metrics_overlap"]["EMAIL"]["fn"], 1)
        self.assertAlmostEqual(res["leak_rate"]["overall"], 1.0)
        self.assertEqual(res["entity_exposure"]["fully_leaked_count"], 1)

    def test_missing_prediction_raises_error(self):
        """Missing prediction entry for a document in the requested split raises KeyError."""
        gt = [
            {"file": "doc1.txt", "doc_type": "hr_intake", "split": "test", "entities": [], "decoys": []},
            {"file": "doc2.txt", "doc_type": "hr_intake", "split": "test", "entities": [], "decoys": []},
        ]
        preds = {
            "doc1.txt": {"spans": [], "ms": 5.0}
            # doc2.txt is missing
        }
        with self.assertRaises(KeyError):
            score(gt, preds, split="test")

    def test_document_with_no_pii(self):
        """Document with zero PII entities handles division cleanly."""
        gt = [{
            "file": "doc_empty.txt",
            "doc_type": "vendor_invoice",
            "split": "test",
            "length": 80,
            "entities": [],
            "decoys": [],
        }]
        preds = {
            "doc_empty.txt": {"spans": [], "ms": 4.0}
        }
        res = score(gt, preds, split="test")

        self.assertEqual(res["leak_rate"]["total_pii_chars"], 0)
        self.assertAlmostEqual(res["leak_rate"]["overall"], 0.0)
        self.assertEqual(res["entity_exposure"]["total_entities"], 0)
        self.assertAlmostEqual(res["over_redaction"]["rate"], 0.0)

    def test_split_guard_refuses_dev_unless_explicit(self):
        """Calling score refuses invalid splits or dev unless explicit."""
        gt = [
            {"file": "dev1.txt", "doc_type": "health_report", "split": "dev", "entities": [], "decoys": []},
            {"file": "test1.txt", "doc_type": "health_report", "split": "test", "entities": [], "decoys": []},
        ]
        preds = {
            "dev1.txt": {"spans": [], "ms": 5.0},
            "test1.txt": {"spans": [], "ms": 5.0},
        }

        # Default scores test
        res_default = score(gt, preds)
        self.assertEqual(res_default["split"], "test")

        # Explicit dev works
        res_dev = score(gt, preds, split="dev")
        self.assertEqual(res_dev["split"], "dev")

        # Invalid splits raise ValueError
        with self.assertRaises(ValueError):
            score(gt, preds, split="all")
        with self.assertRaises(ValueError):
            score(gt, preds, split="training")
        with self.assertRaises(ValueError):
            score(gt, preds, split="")

    def test_unmapped_labels_ignored_and_counted(self):
        """Unmapped predictions (e.g. DATE, ORG) are ignored in matching and counted."""
        gt = [{
            "file": "doc1.txt",
            "doc_type": "health_report",
            "split": "test",
            "length": 60,
            "entities": [{"type": "PERSON", "start": 10, "end": 20, "text": "Emeka Obi"}],
            "decoys": [],
        }]
        preds = {
            "doc1.txt": {
                "spans": [
                    {"label": "DATE", "start": 10, "end": 20},
                    {"label": "ORG", "start": 30, "end": 40},
                ],
                "ms": 12.0,
            }
        }
        res = score(gt, preds, split="test")

        # Ignored: PERSON is missed, DATE did not count as redaction
        self.assertEqual(res["metrics_overlap"]["PERSON"]["tp"], 0)
        self.assertEqual(res["metrics_overlap"]["PERSON"]["fn"], 1)
        self.assertAlmostEqual(res["leak_rate"]["overall"], 1.0)

        # Counted in unmapped_predictions
        self.assertEqual(res["unmapped_predictions"]["total"], 2)
        self.assertEqual(res["unmapped_predictions"]["by_label"]["DATE"], 1)
        self.assertEqual(res["unmapped_predictions"]["by_label"]["ORG"], 1)

    def test_deterministic_tie_break(self):
        """Tie-breaking selects earlier start and lower entity index when overlaps match."""
        # Two identical-length entities
        gt_entities = [
            {"type": "PERSON", "start": 10, "end": 20, "text": "Person A"},
            {"type": "PERSON", "start": 30, "end": 40, "text": "Person B"},
        ]
        pred_spans = [
            # Two predictions with identical overlap (5 chars) on Person A and Person B
            {"label": "PERSON", "start": 15, "end": 25},  # overlaps Person A by 5 chars (15..20)
            {"label": "PERSON", "start": 35, "end": 45},  # overlaps Person B by 5 chars (35..40)
        ]
        res1 = match_entities_and_predictions(gt_entities, pred_spans)
        # Person A (start=10) matched to first pred, Person B (start=30) matched to second pred
        self.assertEqual(len(res1["matches"]), 2)
        self.assertEqual(res1["matches"][0]["gt_idx"], 0)
        self.assertEqual(res1["matches"][1]["gt_idx"], 1)

        # Even if candidates are presented in reversed prediction order
        rev_preds = list(reversed(pred_spans))
        res2 = match_entities_and_predictions(gt_entities, rev_preds)
        self.assertEqual(len(res2["matches"]), 2)
        # Person A (start=10) should still be evaluated first due to earlier start tie-breaker
        self.assertEqual(res2["matches"][0]["gt_idx"], 0)

    def test_off_by_one_at_span_ends(self):
        """Span ends are exclusive. [10, 20) and [20, 30) have overlap 0 (adjacent)."""
        gt_entities = [{"type": "ID", "start": 10, "end": 20, "text": "1234567890"}]
        # Adjacent prediction: starts right where GT ends
        adjacent_pred = [{"label": "ID", "start": 20, "end": 30}]
        res_adj = match_entities_and_predictions(gt_entities, adjacent_pred)
        self.assertEqual(len(res_adj["matches"]), 0)
        self.assertEqual(res_adj["unmatched_gt_indices"], [0])
        self.assertEqual(res_adj["unmatched_pred_indices"], [0])

        # Overlapping by exactly 1 character: [19, 21)
        overlap_pred = [{"label": "ID", "start": 19, "end": 21}]
        res_ov = match_entities_and_predictions(gt_entities, overlap_pred)
        self.assertEqual(len(res_ov["matches"]), 1)
        self.assertEqual(res_ov["matches"][0]["overlap"], 1)

    def test_hand_calculated_leak_rate_and_precision_recall(self):
        """Hand-calculated test: 11-char entity with 5 chars covered gives 6/11 leak rate."""
        # 11-char entity from index 10 to 21 (e.g. BVN: "12345678901")
        gt = [{
            "file": "doc_hand.txt",
            "doc_type": "vendor_invoice",
            "split": "test",
            "length": 100,
            "entities": [{"type": "BVN", "start": 10, "end": 21, "text": "12345678901", "cued": True}],
            "decoys": [],
        }]
        # 5 characters covered: from index 10 to 15
        preds = {
            "doc_hand.txt": {
                "spans": [{"label": "ID", "start": 10, "end": 15}],
                "ms": 10.0,
            }
        }
        res = score(gt, preds, split="test")

        # Leak rate: exactly 6 uncovered characters out of 11
        self.assertEqual(res["leak_rate"]["total_pii_chars"], 11)
        self.assertEqual(res["leak_rate"]["uncovered_pii_chars"], 6)
        self.assertAlmostEqual(res["leak_rate"]["overall"], 6 / 11)
        self.assertAlmostEqual(res["leak_rate"]["per_type"]["ID"], 6 / 11)

        # Precision / Recall
        # Strict: start=10, end=15 vs 10, 21 -> NOT strict
        self.assertEqual(res["metrics_strict"]["ID"]["tp"], 0)
        self.assertEqual(res["metrics_strict"]["ID"]["fp"], 1)
        self.assertEqual(res["metrics_strict"]["ID"]["fn"], 1)
        self.assertAlmostEqual(res["metrics_strict"]["ID"]["precision"], 0.0)
        self.assertAlmostEqual(res["metrics_strict"]["ID"]["recall"], 0.0)

        # Overlap: 5 chars overlap -> Overlap TP = 1
        self.assertEqual(res["metrics_overlap"]["ID"]["tp"], 1)
        self.assertEqual(res["metrics_overlap"]["ID"]["fp"], 0)
        self.assertEqual(res["metrics_overlap"]["ID"]["fn"], 0)
        self.assertAlmostEqual(res["metrics_overlap"]["ID"]["precision"], 1.0)
        self.assertAlmostEqual(res["metrics_overlap"]["ID"]["recall"], 1.0)
        self.assertAlmostEqual(res["metrics_overlap"]["ID"]["f1"], 1.0)

        # ID cued recall breakdown
        self.assertEqual(res["id_recall"]["cued"]["total"], 1)
        self.assertEqual(res["id_recall"]["cued"]["tp_overlap"], 1)
        self.assertEqual(res["id_recall"]["cued"]["tp_strict"], 0)
        self.assertAlmostEqual(res["id_recall"]["cued"]["recall_overlap"], 1.0)
        self.assertAlmostEqual(res["id_recall"]["cued"]["recall_strict"], 0.0)


if __name__ == "__main__":
    unittest.main()
