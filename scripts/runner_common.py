"""Deterministic runner I/O, with no benchmark scoring."""
import hashlib
import json
import platform
import time
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GT = ROOT / "data/ground_truth.json"
DEFAULT_RAW = ROOT / "data/raw"
DEFAULT_OUTPUT = ROOT / "data/predictions"
CUSTOM_SOURCE = ROOT / "scripts/custom_recognizers.py"
FREEZE_PATH = ROOT / "results/freeze.json"


def document_id(doc):
    # Legacy Phase 1 records have file only; preserve that exact identifier.
    value = doc["doc_id"] if "doc_id" in doc else doc["file"]
    if not isinstance(value, str) or not value:
        raise ValueError("Document ID must be a nonempty string")
    return value


def load_ground_truth(path=DEFAULT_GT):
    with Path(path).open(encoding="utf-8") as handle:
        docs = json.load(handle)
    if not isinstance(docs, list):
        raise ValueError("Ground truth must be a list")
    ids = [document_id(doc) for doc in docs]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate ground-truth document IDs")
    return sorted(docs, key=document_id)


def load_doc_text(doc, raw_dir=DEFAULT_RAW):
    return (Path(raw_dir) / Path(doc["file"]).name).read_text(encoding="utf-8")


def check_splits(splits):
    if not splits or any(split not in ("dev", "test") for split in splits):
        raise ValueError("Splits must contain only dev and/or test")
    return list(dict.fromkeys(splits))


def add_common_arguments(parser):
    parser.add_argument("--splits", nargs="+", choices=("dev", "test"), default=["dev"])
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GT)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def seed_and_record_environment():
    from spacy.util import fix_random_seed
    fix_random_seed(42)
    versions = sorted({(dist.metadata["Name"], dist.version) for dist in metadata.distributions()})
    path = ROOT / "results/environment.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"Python: {platform.python_version()}\nSeed: 42\n")
        handle.write("Model: en_core_web_sm; default pipeline enabled\n")
        handle.write("Public suffix list: tldextract bundled snapshot; no network or cache\n")
        for name, version in versions:
            handle.write(f"{name}=={version}\n")


def require_custom_freeze(freeze_path=FREEZE_PATH, source_path=CUSTOM_SOURCE):
    try:
        freeze = json.loads(Path(freeze_path).read_text(encoding="utf-8"))
        actual = hashlib.sha256(Path(source_path).read_bytes()).hexdigest()
        if not isinstance(freeze, dict) or freeze.get("sha256") != actual:
            raise ValueError("Custom freeze hash mismatch")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("A valid results/freeze.json is required for custom test") from exc


def run_documents(docs, splits, raw_dir, output_dir, config, analyze, extract_spans):
    splits = check_splits(splits)
    docs = sorted(docs, key=document_id)
    warmup = [doc for doc in docs if doc["split"] == "dev"][:5]
    if len(warmup) != 5:
        raise ValueError("Five dev documents are required for warm-up")
    for doc in warmup:
        analyze(load_doc_text(doc, raw_dir))
    outputs = []
    for split in splits:
        selected = [doc for doc in docs if doc["split"] == split]
        if not selected:
            raise ValueError("Requested split contains no documents")
        predictions = {}
        for doc in selected:
            text = load_doc_text(doc, raw_dir)
            started = time.perf_counter()
            analysis = analyze(text)
            elapsed = (time.perf_counter() - started) * 1000.0
            spans = sorted(extract_spans(analysis), key=lambda s: (s["start"], s["end"], s["label"]))
            predictions[document_id(doc)] = {"spans": spans, "ms": float(elapsed)}
        output = Path(output_dir) / f"{config}__{split}.json"
        write_json(output, predictions)
        outputs.append(output)
        print(f"Saved {len(predictions)} documents: {output}")
    return outputs
