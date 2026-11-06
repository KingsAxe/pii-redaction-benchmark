"""Add dev ID diagnostics from existing archives; never invokes an analyzer."""
import hashlib
import json
from pathlib import Path

if __package__:
    from .analysis_common import id_diagnostics
    from .runner_common import ROOT, load_ground_truth, write_json
    from .validate_predictions import validate_file
else:
    from analysis_common import id_diagnostics
    from runner_common import ROOT, load_ground_truth, write_json
    from validate_predictions import validate_file

MARKER = "## Accepted review: ID-only archived dev diagnostics"


def main():
    docs = [doc for doc in load_ground_truth() if doc["split"] == "dev"]
    records = []
    for experiment in ("01-initial", "02-nonzero", "03-cued-only"):
        path = ROOT / "results/tuning" / experiment / "presidio_custom__dev.json"
        validate_file(path, "dev")
        predictions = json.loads(path.read_text(encoding="utf-8"))
        records.append({"experiment": experiment,
                        "prediction_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        **id_diagnostics(docs, predictions, "dev")})
    write_json(ROOT / "results/dev_id_diagnostics.json", records)
    lines = [MARKER, "", "Computed from archived predictions only; no new inference or tuning runs.", "",
             "ID precision is the Phase 2 per-ID precision using its full, type-aware greedy assignment. "
             "PHONE means an ID entity assigned to a PHONE prediction by that matcher. "
             "Coverage is the union of every mapped prediction, regardless of its type. "
             "Uncovered means at least one ID character exposed; fully uncovered means no character covered. "
             "ORDER_ID counts distinct decoy annotations touched by an ID prediction, once per decoy.", "",
             "| Experiment | ID precision strict | ID precision overlap | ORDER_ID decoys hit by ID | IDs assigned PHONE | Fully uncovered IDs | Partly uncovered IDs | Any uncovered IDs | PHONE or any uncovered IDs |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in records:
        lines.append(f"| {r['experiment']} | {r['id_precision_strict']:.6f} | {r['id_precision_overlap']:.6f} | "
                     f"{r['order_id_decoys_hit_by_id']} | {r['id_entities_assigned_phone']} | "
                     f"{r['id_entities_fully_uncovered']} | {r['id_entities_partially_uncovered']} | "
                     f"{r['id_entities_any_uncovered']} | {r['id_entities_phone_or_any_uncovered']} |")
    lines += ["", "Experiment 02's rule works because gen_11digit() in scripts/generate_data.py draws from "
              "10_000_000_000 through 99_999_999_999: the generator never emits BVN/NIN IDs starting with 0. "
              "This assumption excludes phone-shaped numbers without excluding generated IDs; it is not evidence "
              "that real identifiers obey that restriction. The user accepted review and authorized freezing both "
              "01 (custom_generic) and 02 (custom), without any new tuning experiments.", ""]
    path = ROOT / "results/tuning_log.md"
    original = path.read_text(encoding="utf-8").split(MARKER)[0].rstrip()
    path.write_text(original + "\n\n" + "\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
