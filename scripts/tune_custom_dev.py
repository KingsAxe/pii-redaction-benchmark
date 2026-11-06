"""Run and archive one custom dev experiment; never accepts a test split."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .metrics import score
    from .run_presidio import main as run_presidio
    from .runner_common import CUSTOM_SOURCE, DEFAULT_GT, ROOT, load_ground_truth, write_json
    from .validate_predictions import validate_file
else:
    from metrics import score
    from run_presidio import main as run_presidio
    from runner_common import CUSTOM_SOURCE, DEFAULT_GT, ROOT, load_ground_truth, write_json
    from validate_predictions import validate_file


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--change", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", args.experiment):
        parser.error("Experiment must be a lowercase filename component")
    destination = ROOT / "results/tuning" / args.experiment
    if destination.exists():
        parser.error("Experiment already exists; use a new name")
    source = CUSTOM_SOURCE.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    destination.mkdir(parents=True)
    (destination / "custom_recognizers.py").write_bytes(source)
    record = {"experiment": args.experiment, "change": args.change,
              "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "sha256": digest, "split": "dev", "status": "started"}
    write_json(destination / "experiment.json", record)
    log = ROOT / "results/tuning_log.md"
    if not log.exists():
        log.write_text(
            "# Custom dev experiment log\n\n"
            "Seed 42; full en_core_web_sm; dev only. No freeze approved or written.\n\n"
            "ID recall and overall micro precision use the unchanged Phase 2 scorer. "
            "Strict means exact span and mapped type; overlap also accepts partial spans. "
            "Raw unmapped labels are retained in predictions and ignored by that scorer.\n\n"
            "Each experiment archives source, SHA-256, predictions, label counts, and dev metrics "
            "under results/tuning/<experiment>/. Only custom_recognizers.py is tuned.\n\n",
            encoding="utf-8", newline="\n")
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"## {args.experiment}\n\nChange: {args.change}\n\n")
        handle.write(f"Source SHA-256: `{digest}`\n\n")
    try:
        run_presidio(["--config", "custom", "--splits", "dev", "--output-dir", str(destination)])
        prediction_path = destination / "presidio_custom__dev.json"
        labels = validate_file(prediction_path, "dev")
        dev_docs = [doc for doc in load_ground_truth(DEFAULT_GT) if doc["split"] == "dev"]
        predictions = json.loads(prediction_path.read_text(encoding="utf-8"))
        # Explicit dev-only input and split. Never compute test error records.
        metrics = score(dev_docs, predictions, split="dev")
        write_json(destination / "metrics.json", metrics)
        write_json(destination / "label_counts.json", labels)
        strict = metrics["metrics_strict"]
        overlap = metrics["metrics_overlap"]
        record.update(status="complete", doc_count=metrics["doc_count"],
                      id_recall_strict=strict["ID"]["recall"],
                      precision_strict=strict["overall"]["precision"],
                      id_recall_overlap=overlap["ID"]["recall"],
                      precision_overlap=overlap["overall"]["precision"])
        with log.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"Dev documents: {metrics['doc_count']}\n\n")
            for name in ("id_recall_strict", "precision_strict", "id_recall_overlap", "precision_overlap"):
                handle.write(f"- {name}: {record[name]:.6f}\n")
            handle.write(f"\nArtifacts: `results/tuning/{args.experiment}/`\n\n")
        # The standard dev path reflects the most recently completed experiment.
        write_json(ROOT / "data/predictions/presidio_custom__dev.json", predictions)
    except Exception as exc:
        record.update(status="failed", failure=f"{type(exc).__name__}: {exc}")
        with log.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"Experiment failed: {record['failure']}\n\n")
        raise
    finally:
        write_json(destination / "experiment.json", record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
