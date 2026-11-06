"""Evaluate frozen test predictions with the unchanged Phase 2 scorer."""
import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .analysis_common import id_diagnostics, overlap, scorer_predictions
    from .metrics import CANONICAL_TYPES, GT_LABEL_MAP, compute_percentile, match_entities_and_predictions, score
    from .runner_common import (DEFAULT_GT, DEFAULT_OUTPUT, DEFAULT_RAW, ROOT, document_id,
                                load_doc_text, load_ground_truth, require_custom_freeze, write_json)
    from .validate_predictions import validate_file
else:
    from analysis_common import id_diagnostics, overlap, scorer_predictions
    from metrics import CANONICAL_TYPES, GT_LABEL_MAP, compute_percentile, match_entities_and_predictions, score
    from runner_common import (DEFAULT_GT, DEFAULT_OUTPUT, DEFAULT_RAW, ROOT, document_id,
                               load_doc_text, load_ground_truth, require_custom_freeze, write_json)
    from validate_predictions import validate_file

CONFIGS = ("spacy", "presidio_default", "presidio_ng_phone", "presidio_custom_generic", "presidio_custom")


def measured_latency(docs, predictions):
    values = [predictions[document_id(doc)]["ms"] for doc in docs]
    return {"median_ms": compute_percentile(values, 50.0),
            "p95_ms": compute_percentile(values, 95.0), "measured_doc_count": len(values)}


def error_records(docs, predictions, raw_dir=DEFAULT_RAW):
    """Retain every scorer miss/decoy hit plus confusion, partial, and exposure records."""
    records = []
    for doc in docs:
        text = load_doc_text(doc, raw_dir)
        result = match_entities_and_predictions(doc["entities"], predictions[document_id(doc)]["spans"])
        def add(kind, item, label, **extra):
            records.append({"document": document_id(doc), "kind": kind, "label": label,
                            "start": item["start"], "end": item["end"],
                            "context": text[max(0, item["start"] - 35):item["end"] + 35], **extra})
        for index in result["unmatched_gt_indices"]:
            entity = doc["entities"][index]
            add("miss", entity, GT_LABEL_MAP.get(entity["type"], entity["type"]))
        for match in result["matches"]:
            if not match["same_type"]:
                add("type_confusion", match["gt_entity"], match["gt_type"], predicted_type=match["pred_type"])
            elif not match["is_strict"]:
                add("partial_match", match["gt_entity"], match["gt_type"],
                    predicted_start=match["pred_span"]["start"], predicted_end=match["pred_span"]["end"])
        for index in result["unmatched_pred_indices"]:
            prediction = result["mapped_preds"][index]
            # Same first-overlapping-decoy rule as metrics.score; one record per hit prediction.
            for decoy in doc["decoys"]:
                if overlap(prediction, decoy):
                    add("decoy_hit", prediction, prediction["mapped_label"], decoy_type=decoy["type"],
                        decoy_start=decoy["start"], decoy_end=decoy["end"])
                    break
        covered = {i for p in result["mapped_preds"] for i in range(p["start"], p["end"])}
        for entity in doc["entities"]:
            chars = set(range(entity["start"], entity["end"]))
            exposed = len(chars - covered)
            if exposed:
                add("fully_uncovered" if exposed == len(chars) else "partially_uncovered",
                    entity, GT_LABEL_MAP.get(entity["type"], entity["type"]), uncovered_characters=exposed)
    return records


def markdown_table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\r", "").replace("\n", " ").replace("`", "'")
    lines = ["| " + " | ".join(map(cell, headers)) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(lines)


def result_row(config, metrics, ids, latency):
    row = {"config": config, "split": "test", "documents": metrics["doc_count"],
           "leak_rate": metrics["leak_rate"]["overall"]}
    row.update({f"leak_rate_{kind}": metrics["leak_rate"]["per_type"][kind] for kind in CANONICAL_TYPES})
    for group in ("overall", "cued", "bare"):
        for mode in ("strict", "overlap"):
            row[f"id_recall_{group}_{mode}"] = metrics["id_recall"][group][f"recall_{mode}"]
        row[f"id_count_{group}"] = metrics["id_recall"][group]["total"]
    row.update(ids)
    row.update({"precision_strict": metrics["metrics_strict"]["overall"]["precision"],
                "precision_overlap": metrics["metrics_overlap"]["overall"]["precision"],
                "entity_exposure_rate": metrics["entity_exposure"]["exposure_rate"],
                "over_redaction_rate": metrics["over_redaction"]["rate"],
                "decoy_hit_predictions": metrics["decoys"]["total_hits"],
                "unmapped_prediction_count": metrics["unmapped_predictions"]["total"],
                **latency,
                "scorer_median_ms_after_extra_drop": metrics["latency"]["median_ms"],
                "scorer_p95_ms_after_extra_drop": metrics["latency"]["p95_ms"],
                "scorer_extra_dropped_timings": metrics["latency"]["warmup_excluded"]})
    row.update({f"leak_rate_domain_{domain}": value
                for domain, value in sorted(metrics["leak_rate"]["per_doc_type"].items())})
    row.update({"fully_uncovered_entities": metrics["entity_exposure"]["fully_leaked_count"],
                "partially_exposed_entities": metrics["entity_exposure"]["partially_exposed_count"],
                "total_entities": metrics["entity_exposure"]["total_entities"]})
    return row


def write_reports(output_dir, rows, details):
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    pct = lambda value: f"{100 * value:.2f}%"
    domains = sorted({domain for detail in details.values()
                      for domain in detail["phase2"]["leak_rate"]["per_doc_type"]})
    sections = ["# Test results", "",
                "Generated by scripts/evaluate.py from validated test predictions after the two-config freeze. "
                "No tuning or model calls occur during evaluation. Seed 42; full en_core_web_sm pipeline for all configs.", "",
                "## Overall", "",
                markdown_table(["Config", "Documents", "PII character leak", "Strict precision", "Overlap precision", "Exposed entities", "Decoy-hit predictions", "Median ms", "p95 ms"],
                    [[r["config"], r["documents"], pct(r["leak_rate"]), pct(r["precision_strict"]),
                      pct(r["precision_overlap"]), pct(r["entity_exposure_rate"]), r["decoy_hit_predictions"],
                      f"{r['median_ms']:.3f}", f"{r['p95_ms']:.3f}"] for r in rows]), "",
                "## Character leak by entity type", "",
                markdown_table(["Config", *CANONICAL_TYPES],
                    [[r["config"], *[pct(r[f"leak_rate_{kind}"]) for kind in CANONICAL_TYPES]] for r in rows]), "",
                "## Character leak by document domain", "",
                "Rates exported directly from the scorer's leak_rate.per_doc_type output.", "",
                markdown_table(["Config", *domains],
                    [[r["config"], *[pct(r[f"leak_rate_domain_{domain}"]) for domain in domains]] for r in rows]), "",
                "## Character over-redaction and entity exposure", "",
                markdown_table(["Config", "Non-PII character over-redaction", "Fully uncovered entities", "Partially exposed entities", "Total entities", "Entity exposure rate"],
                    [[r["config"], pct(r["over_redaction_rate"]), r["fully_uncovered_entities"],
                      r["partially_exposed_entities"], r["total_entities"], pct(r["entity_exposure_rate"])] for r in rows]), "",
                "## ID precision and recall", "",
                f"ID denominators: {rows[0]['id_count_overall']} overall; {rows[0]['id_count_cued']} cued; "
                f"{rows[0]['id_count_bare']} bare.", "",
                markdown_table(["Config", "ID precision strict", "ID precision overlap", "ID recall strict", "ID recall overlap", "Cued recall strict", "Cued recall overlap", "Bare recall strict", "Bare recall overlap"],
                    [[r["config"], pct(r["id_precision_strict"]), pct(r["id_precision_overlap"]),
                      *[pct(r[f"id_recall_{group}_{mode}"]) for group in ("overall", "cued", "bare")
                        for mode in ("strict", "overlap")]] for r in rows]), "",
                "## ID diagnostics", "",
                markdown_table(["Config", "ID predictions", "ORDER_ID decoys hit by ID", "IDs assigned PHONE", "Fully uncovered IDs", "Partly uncovered IDs"],
                    [[r["config"], r["id_prediction_count"], r["order_id_decoys_hit_by_id"],
                      r["id_entities_assigned_phone"], r["id_entities_fully_uncovered"],
                      r["id_entities_partially_uncovered"]] for r in rows]), "",
                "## Definitions and limits", "",
                "- Matching ranks positive-overlap pairs by overlap size, then earlier ground-truth start, earlier "
                "prediction start, lower ground-truth index, and lower prediction index. Label correctness and "
                "exactness are checked only after one-to-one assignment; neither is prioritised. Equal-span "
                "competing labels can be resolved by prediction order.",
                "- After assignment, strict means same mapped type and exact span; overlap means same mapped type "
                "and nonzero overlap. A matcher miss is an entity left unmatched after assignment, even if predicted "
                "characters cover it. Unmatched mapped predictions differ from strict/overlap false positives, "
                "which equal prediction count minus the corresponding true positives. ID precision is per-class precision "
                "under that full assignment. A zero score with no ID predictions is the scorer's convention.",
                "- Leak, exposure, and character over-redaction use the union of all mapped prediction spans, "
                "independently of assignment or label correctness. Raw labels are retained; "
                "unmapped labels do not count as redaction, following the Phase 2 scorer.",
                "- Decoy-hit predictions inspect only unmatched mapped predictions and count the first overlapping "
                "decoy per prediction. Predictions matched to PII can also cover decoy characters without appearing "
                "in this count. ORDER_ID decoys hit by ID instead counts distinct decoy annotations touched by any "
                "mapped ID span. These are different counting measures; neither substitutes for character-level "
                "over-redaction, the share of non-PII characters covered by the mapped prediction union.",
                "- IDs assigned PHONE are the matcher's ID-to-PHONE assignments. An entity is fully uncovered "
                "when no mapped predicted characters cover it; partly uncovered means at least one but not all characters exposed.",
                "- Timing records analysis calls only, after five preliminary unrecorded dev warm-up calls. Main median/p95 use "
                "all stored test timings and the Phase 2 percentile helper. The unchanged scorer additionally "
                "drops the first five stored timings; its original latency output is retained in evaluation_details.json "
                "and the explicitly named scorer columns in results.csv. p95 is the 95th percentile, calculated "
                "with the scorer's linear interpolation; it does not remove outliers. Neither timing calculation changed.",
                "- custom_generic is archived experiment 01; custom is experiment 02. The generator never emits "
                "BVN/NIN IDs starting with 0, which benefits custom's nonzero-leading rule. Bare random order IDs "
                "remain ambiguous. This is synthetic, template-based, small-scale evaluation with one spaCy model.",
                "- The generator-dependent leading-zero exclusion improved ID precision on this dataset. Both custom "
                "variants have equal reported character leakage and over-redaction rates. Equal aggregate rates "
                "do not establish identical covered character positions.",
                "- Baseline predictions for spacy, default, and ng_phone were generated on dev/test before freeze "
                "(dd6b474). After the two-source freeze (853bcbb), all five test configurations were regenerated "
                "and committed (da55731). Phase 4 and this reporting patch rescore those archived predictions "
                "without inference. Test error records were first generated after freeze; prediction generation "
                "and rescoring are distinct operations.",
                "- Latencies are single sequential runs on this machine and may reflect cache, host load, and run order; "
                "they do not establish a universal speed ranking.",
                "- Full scorer outputs, denominators, source hashes, and prediction hashes are in evaluation_details.json. "
                "All error records with snippets are in error_analysis.md.", ""]
    (output_dir / "results.md").write_text("\n".join(sections), encoding="utf-8", newline="\n")
    error_sections = ["# Test error analysis", "",
        "Generated after freeze. Offsets are start-inclusive/end-exclusive. Misses, type confusions, "
        "partial matches, and coverage exposure are distinct categories and may describe the same entity. "
        "A miss means unmatched after one-to-one assignment, not necessarily zero predicted character coverage. "
        "Assignment ranks overlap and deterministic tie-breaks before checking labels or exactness; prediction "
        "order can resolve equal-span competing labels. Unmatched predictions differ from strict/overlap false "
        "positives (prediction count minus corresponding true positives). Decoy-hit rows inspect only unmatched "
        "mapped predictions and count their first overlapping decoy; PII-matched predictions can cover decoy "
        "characters without appearing here. Coverage uses every mapped span independently of assignment and "
        "label correctness. Context is synthetic text.", ""]
    for config, detail in details.items():
        records = detail["errors"]
        counts = Counter(record["kind"] for record in records)
        error_sections += [f"## {config}", "", json.dumps(dict(sorted(counts.items())), sort_keys=True), "",
            markdown_table(["Category", "Document", "Type", "Span", "Details", "Context"],
                [[r["kind"], r["document"], r["label"], f"{r['start']}:{r['end']}",
                  json.dumps({k: v for k, v in r.items() if k not in
                    ("kind", "document", "label", "start", "end", "context")}, sort_keys=True),
                  r["context"].replace("\n", " ")] for r in records]), ""]
    (output_dir / "error_analysis.md").write_text("\n".join(error_sections), encoding="utf-8", newline="\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, default=DEFAULT_GT)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--predictions-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args(argv)
    # Never create test error records until both source hashes match the freeze.
    for config in ("custom", "custom_generic"):
        require_custom_freeze(config=config)
    docs = [doc for doc in load_ground_truth(args.ground_truth) if doc["split"] == "test"]
    rows, details = [], {}
    for config in CONFIGS:
        path = args.predictions_dir / f"{config}__test.json"
        labels = validate_file(path, "test", args.ground_truth, args.raw_dir)
        predictions = json.loads(path.read_text(encoding="utf-8"))
        metrics = score(docs, scorer_predictions(docs, predictions), split="test")
        ids = id_diagnostics(docs, predictions, "test", metrics)
        latency = measured_latency(docs, predictions)
        records = error_records(docs, predictions, args.raw_dir)
        counts = Counter(record["kind"] for record in records)
        if counts["decoy_hit"] != metrics["decoys"]["total_hits"]:
            raise AssertionError("Decoy error report differs from Phase 2 scorer")
        if counts["miss"] != sum(metrics["confusion_matrix"][kind]["NONE"] for kind in CANONICAL_TYPES):
            raise AssertionError("Miss error report differs from Phase 2 scorer")
        if (counts["fully_uncovered"] != metrics["entity_exposure"]["fully_leaked_count"] or
                counts["partially_uncovered"] != metrics["entity_exposure"]["partially_exposed_count"]):
            raise AssertionError("Coverage error report differs from Phase 2 scorer")
        rows.append(result_row(config, metrics, ids, latency))
        details[config] = {"phase2": metrics, "id_diagnostics": ids, "reported_latency": latency,
                           "label_counts": labels, "prediction_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "errors": records}
    write_reports(args.output_dir, rows, details)
    write_json(args.output_dir / "evaluation_details.json", {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "ground_truth_sha256": hashlib.sha256(args.ground_truth.read_bytes()).hexdigest(),
        "phase2_scorer_sha256": hashlib.sha256((ROOT / "scripts/metrics.py").read_bytes()).hexdigest(),
        "evaluation_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "diagnostics_script_sha256": hashlib.sha256((ROOT / "scripts/analysis_common.py").read_bytes()).hexdigest(),
        "environment_sha256": hashlib.sha256((ROOT / "results/environment.txt").read_bytes()).hexdigest(),
        "freeze": json.loads((ROOT / "results/freeze.json").read_text(encoding="utf-8")),
        "configs": details})
    print(f"Evaluated {len(rows)} configs; reports: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
