"""Validate structure and label counts without scoring test errors."""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

if __package__:
    from .runner_common import DEFAULT_GT, DEFAULT_RAW, document_id, load_doc_text, load_ground_truth, write_json
else:
    from runner_common import DEFAULT_GT, DEFAULT_RAW, document_id, load_doc_text, load_ground_truth, write_json


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def validate_file(path, split, gt_path=DEFAULT_GT, raw_dir=DEFAULT_RAW):
    if split not in ("dev", "test"):
        raise ValueError("Invalid split")
    docs = [doc for doc in load_ground_truth(gt_path) if doc["split"] == split]
    if not docs:
        raise ValueError("Requested split contains no documents")
    with Path(path).open(encoding="utf-8") as handle:
        predictions = json.load(handle, object_pairs_hook=unique_object)
    expected = {document_id(doc) for doc in docs}
    if not isinstance(predictions, dict) or set(predictions) != expected:
        raise ValueError("Document ID coverage mismatch (missing or extra documents)")
    labels = Counter()
    for doc in docs:
        entry = predictions[document_id(doc)]
        if not isinstance(entry, dict) or set(entry) != {"spans", "ms"}:
            raise ValueError("Invalid prediction entry schema")
        ms = entry["ms"]
        if type(ms) is not float or not math.isfinite(ms) or ms < 0:
            raise ValueError("ms must be a finite nonnegative float")
        if not isinstance(entry["spans"], list):
            raise ValueError("spans must be a list")
        length = len(load_doc_text(doc, raw_dir))
        for span in entry["spans"]:
            if not isinstance(span, dict) or set(span) != {"label", "start", "end"}:
                raise ValueError("Invalid span schema")
            if not isinstance(span["label"], str):
                raise ValueError("Span label must be a string")
            start, end = span["start"], span["end"]
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= length:
                raise ValueError("Span offsets outside document bounds")
            labels[span["label"]] += 1
    return dict(sorted(labels.items()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--split", required=True, choices=("dev", "test"))
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GT)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--report", type=Path, help="Write aggregate structural validation results")
    args = parser.parse_args(argv)
    records = []
    for path in args.files:
        try:
            labels = validate_file(path, args.split, args.ground_truth, args.raw_dir)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            print(f"FAIL {path.name}: {exc}")
            return 1
        print(f"PASS {path.name}: {json.dumps(labels, sort_keys=True)}")
        records.append({"file": path.name, "split": args.split, "status": "pass", "labels": labels})
    if args.report:
        write_json(args.report, records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
