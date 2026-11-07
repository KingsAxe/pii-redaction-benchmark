"""Character-union and source-order checks without models or benchmark mutations."""
import csv
import tempfile
import unittest
from pathlib import Path

from scripts.plot_benchmark import CONFIGS, load_rows
from scripts.render_document_example import coverage, render, select_document, wrapped_positions


class TestFigures(unittest.TestCase):
    def test_csv_order_and_equal_values_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("config", "split", "documents", "leak_rate", "over_redaction_rate"))
                writer.writeheader()
                for config in reversed(CONFIGS):
                    writer.writerow({"config": config, "split": "test", "documents": 1,
                                     "leak_rate": 0.25, "over_redaction_rate": 0.05})
            rows = load_rows(path)
            self.assertEqual([row["config"] for row in rows], list(CONFIGS))
            self.assertEqual(rows[-1]["leak_rate"], rows[-2]["leak_rate"])
            self.assertEqual(rows[-1]["over_redaction_rate"], rows[-2]["over_redaction_rate"])

    def test_overlapping_predictions_are_unioned_once(self):
        text = "abcdefghij"
        entities = [{"start": 2, "end": 8}]
        spans = [{"label": "PERSON", "start": 1, "end": 6},
                 {"label": "LOCATION", "start": 4, "end": 9}]
        sets, masked = coverage(text, entities, spans)
        self.assertEqual(sets["masked_pii"], set(range(2, 8)))
        self.assertEqual(sets["over_redacted"], {1, 8})
        self.assertEqual(sets["missed_pii"], set())
        self.assertEqual(masked, "a########j")

    def test_partial_coverage_and_unmapped_labels(self):
        text = "abcdefghij"
        sets, masked = coverage(text, [{"start": 2, "end": 7}], [
            {"label": "ID", "start": 2, "end": 4},
            {"label": "ORG", "start": 4, "end": 10}])
        self.assertEqual(sets["missed_pii"], {4, 5, 6})
        self.assertEqual(sets["masked_pii"], {2, 3})
        self.assertEqual(masked, "ab##efghij")

    def test_prediction_extends_into_non_pii_and_ignores_label_correctness(self):
        sets, _ = coverage("abcdefghij", [{"start": 3, "end": 5}], [
            {"label": "PHONE_NUMBER", "start": 1, "end": 8}])
        self.assertEqual(sets["over_redacted"], {1, 2, 5, 6, 7})
        self.assertEqual(sets["masked_pii"], {3, 4})

    def test_wrapping_and_newlines_preserve_offsets_and_render_counts(self):
        text = "ab cd ef\n\nghijklmnopqrst\n"
        rows = wrapped_positions(text, columns=5)
        self.assertEqual([i for _, row in rows for i in row],
                         [i for i, char in enumerate(text) if char != "\n"])
        entities = [{"start": 1, "end": 7}]
        spans = [{"label": "ID", "start": 4, "end": 13}]
        sets, masked = coverage(text, entities, spans)
        image, metadata = render(text, entities, spans, "fixture", "presidio_custom")
        self.assertEqual(len(masked), len(text))
        self.assertEqual([i for i, c in enumerate(masked) if c == "\n"], [8, 9, 24])
        for kind, positions in sets.items():
            self.assertEqual(metadata["character_counts"][kind], len(positions))
            self.assertEqual(metadata["rendered_character_counts"][kind] +
                             metadata["preserved_line_break_counts"][kind], len(positions))
        self.assertEqual(image.mode, "RGB")

    def test_selection_is_by_test_document_id(self):
        docs = [{"doc_id": "a", "split": "dev"}, {"doc_id": "c", "split": "test"},
                {"doc_id": "b", "split": "test"}]
        self.assertEqual(select_document(docs)[0]["doc_id"], "b")
        self.assertEqual(select_document(docs, "c")[0]["doc_id"], "c")
        with self.assertRaises(ValueError):
            select_document(docs, "a")


if __name__ == "__main__":
    unittest.main()
