"""
metrics.py – Evaluation and scoring metrics for PII redaction benchmark.

Input schema:
  Ground truth: List of document dictionaries produced by generate_data.py:
    [
      {
        "file": str,
        "doc_type": str,
        "split": "dev" | "test",
        "length": int,
        "entities": [{"type": str, "start": int, "end": int, "text": str, ...}],
        "decoys": [{"type": str, "start": int, "end": int, "text": str, ...}],
      },
      ...
    ]

  Predictions: Dictionary mapping doc_id (file path or file stem) to:
    {
      "spans": [{"label": str, "start": int, "end": int}],
      "ms": float
    }

Label mapping:
  Only mapped labels count as redaction. Unmapped predictions are ignored.
  Ground truth: BVN and NIN map to ID.
  Predictions:
    spaCy: PERSON -> PERSON, GPE/LOC/FAC -> ADDRESS
    Presidio: PERSON -> PERSON, PHONE_NUMBER -> PHONE, EMAIL_ADDRESS -> EMAIL,
              LOCATION -> ADDRESS, BVN/NIN/ID -> ID
  Unmapped labels are ignored and counted.
"""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Label Mappings
# ---------------------------------------------------------------------------
CANONICAL_TYPES = ["ADDRESS", "EMAIL", "ID", "PERSON", "PHONE"]

GT_LABEL_MAP: dict[str, str] = {
    "BVN": "ID",
    "NIN": "ID",
    "ID": "ID",
    "PERSON": "PERSON",
    "PHONE": "PHONE",
    "EMAIL": "EMAIL",
    "ADDRESS": "ADDRESS",
}

DEFAULT_PRED_LABEL_MAP: dict[str, str] = {
    # spaCy mappings
    "PERSON": "PERSON",
    "GPE": "ADDRESS",
    "LOC": "ADDRESS",
    "FAC": "ADDRESS",
    # Presidio mappings
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "LOCATION": "ADDRESS",
    # Custom recognizers / canonical names
    "BVN": "ID",
    "NIN": "ID",
    "ID": "ID",
    "PHONE": "PHONE",
    "EMAIL": "EMAIL",
    "ADDRESS": "ADDRESS",
}


# ---------------------------------------------------------------------------
# Helper: Document Prediction Lookup
# ---------------------------------------------------------------------------
def find_prediction_entry(doc_file: str, preds: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve doc_id in predictions dictionary using file path, filename, or stem."""
    if doc_file in preds:
        return preds[doc_file]
    p = Path(doc_file)
    if p.name in preds:
        return preds[p.name]
    if p.stem in preds:
        return preds[p.stem]
    norm_fwd = doc_file.replace("\\", "/")
    if norm_fwd in preds:
        return preds[norm_fwd]
    norm_back = doc_file.replace("/", "\\")
    if norm_back in preds:
        return preds[norm_back]
    return None


# ---------------------------------------------------------------------------
# Helper: Latency Percentile Calculation
# ---------------------------------------------------------------------------
def compute_percentile(data: list[float], p: float) -> float:
    """Compute p-th percentile with linear interpolation on sorted list."""
    if not data:
        return 0.0
    s = sorted(data)
    idx = (len(s) - 1) * (p / 100.0)
    low = int(idx)
    high = low + 1
    if high < len(s):
        return s[low] + (idx - low) * (s[high] - s[low])
    return s[low]


# ---------------------------------------------------------------------------
# Core: 1-to-1 Greedy Matching
# ---------------------------------------------------------------------------
def match_entities_and_predictions(
    gt_entities: list[dict],
    pred_spans: list[dict],
    gt_label_map: dict[str, str] = GT_LABEL_MAP,
    pred_label_map: dict[str, str] = DEFAULT_PRED_LABEL_MAP,
) -> dict[str, Any]:
    """Perform deterministic one-to-one greedy matching between predictions and GT entities.

    Matches by overlap size descending. Ties broken by:
      1. earlier ground-truth start
      2. earlier prediction start
      3. lower ground-truth entity index
      4. lower prediction index

    Only mapped predictions participate in matching; unmapped predictions are filtered out.
    """
    mapped_preds: list[dict] = []
    unmapped_preds: list[dict] = []

    for p_idx, p in enumerate(pred_spans):
        label = p.get("label", "")
        if label in pred_label_map:
            mapped_preds.append({
                "orig_idx": p_idx,
                "label": label,
                "mapped_label": pred_label_map[label],
                "start": p["start"],
                "end": p["end"],
            })
        else:
            unmapped_preds.append(p)

    # Build overlap candidates
    candidates = []
    for g_idx, g in enumerate(gt_entities):
        g_start, g_end = g["start"], g["end"]
        for p_idx, p in enumerate(mapped_preds):
            p_start, p_end = p["start"], p["end"]
            overlap = max(0, min(g_end, p_end) - max(g_start, p_start))
            if overlap > 0:
                candidates.append((overlap, g_start, p_start, g_idx, p_idx))

    # Sort candidates by overlap descending, breaking ties deterministically
    candidates.sort(key=lambda c: (-c[0], c[1], c[2], c[3], c[4]))

    matched_gt: set[int] = set()
    matched_pred: set[int] = set()
    matches: list[dict] = []

    for overlap, _, _, g_idx, p_idx in candidates:
        if g_idx not in matched_gt and p_idx not in matched_pred:
            matched_gt.add(g_idx)
            matched_pred.add(p_idx)
            g = gt_entities[g_idx]
            p = mapped_preds[p_idx]
            gt_type = gt_label_map.get(g["type"], g["type"])
            pred_type = p["mapped_label"]
            is_strict = (gt_type == pred_type and p["start"] == g["start"] and p["end"] == g["end"])
            matches.append({
                "gt_idx": g_idx,
                "pred_idx": p_idx,
                "orig_pred_idx": p["orig_idx"],
                "overlap": overlap,
                "gt_type": gt_type,
                "pred_type": pred_type,
                "is_strict": is_strict,
                "same_type": (gt_type == pred_type),
                "gt_entity": g,
                "pred_span": p,
            })

    unmatched_gt_indices = [i for i in range(len(gt_entities)) if i not in matched_gt]
    unmatched_pred_indices = [i for i in range(len(mapped_preds)) if i not in matched_pred]

    return {
        "matches": matches,
        "unmatched_gt_indices": unmatched_gt_indices,
        "unmatched_pred_indices": unmatched_pred_indices,
        "mapped_preds": mapped_preds,
        "unmapped_preds": unmapped_preds,
    }


# ---------------------------------------------------------------------------
# Scoring Function
# ---------------------------------------------------------------------------
def score(
    gt: list[dict],
    preds: dict[str, Any],
    split: str = "test",
    gt_label_map: dict[str, str] = GT_LABEL_MAP,
    pred_label_map: dict[str, str] = DEFAULT_PRED_LABEL_MAP,
) -> dict[str, Any]:
    """Score predictions against ground truth for the specified split.

    Only mapped labels count as redaction; unmapped predictions are ignored and counted.
    Split guard: Refuses to score dev unless split='dev' is explicitly passed.
    Raises KeyError if any document in the requested split has no prediction entry.
    """
    if split not in ("test", "dev"):
        raise ValueError(
            f"Invalid split '{split}'. Split must be explicitly 'test' or 'dev'."
        )

    docs_in_split = [d for d in gt if d.get("split") == split]
    if not docs_in_split:
        raise ValueError(f"No documents found for split '{split}' in ground truth data.")

    # Validate that every document in the requested split has an entry
    for doc in docs_in_split:
        entry = find_prediction_entry(doc["file"], preds)
        if entry is None:
            raise KeyError(
                f"Missing prediction entry for document '{doc['file']}' in split '{split}'."
            )

    # ---------------------------------------------------------------------------
    # Metrics accumulators
    # ---------------------------------------------------------------------------
    all_types = sorted(list(set(CANONICAL_TYPES)))
    types_with_none = all_types + ["NONE"]

    confusion_matrix: dict[str, dict[str, int]] = {
        row: {col: 0 for col in types_with_none} for row in types_with_none
    }

    # Strict and Overlap TP/FP/FN counters per type
    tp_strict = Counter()
    tp_overlap = Counter()
    fp_strict = Counter()
    fp_overlap = Counter()
    fn_strict = Counter()
    fn_overlap = Counter()

    gt_counts_by_type = Counter()
    pred_counts_by_type = Counter()

    # Leak rate counters (character level)
    total_pii_chars = 0
    uncovered_pii_chars = 0
    pii_chars_by_type = Counter()
    uncovered_pii_chars_by_type = Counter()
    pii_chars_by_doc_type = Counter()
    uncovered_pii_chars_by_doc_type = Counter()

    # Entity exposure counters
    total_entities = 0
    fully_leaked_entities = 0
    partially_exposed_entities = 0
    completely_redacted_entities = 0

    entities_by_type = Counter()
    fully_leaked_by_type = Counter()
    partially_exposed_by_type = Counter()

    # Non-PII over-redaction counters
    total_non_pii_chars = 0
    covered_non_pii_chars = 0

    # Decoy hits
    decoy_hits_count = 0
    decoy_hits_by_type = Counter()

    # ID recall breakdown (cued vs bare)
    id_stats = {
        "cued": {"total": 0, "tp_strict": 0, "tp_overlap": 0},
        "bare": {"total": 0, "tp_strict": 0, "tp_overlap": 0},
        "overall": {"total": 0, "tp_strict": 0, "tp_overlap": 0},
    }

    # Unmapped predictions tracking
    unmapped_counter = Counter()

    # Latency tracking
    latencies: list[float] = []

    # ---------------------------------------------------------------------------
    # Process each document
    # ---------------------------------------------------------------------------
    for doc in docs_in_split:
        entry = find_prediction_entry(doc["file"], preds)
        assert entry is not None  # Verified above

        if "ms" in entry and isinstance(entry["ms"], (int, float)):
            latencies.append(float(entry["ms"]))

        raw_pred_spans = entry.get("spans", [])
        gt_entities = doc.get("entities", [])
        decoys = doc.get("decoys", [])
        doc_type = doc.get("doc_type", "unknown")
        doc_length = doc.get("length", 0)

        # 1. Matching
        match_res = match_entities_and_predictions(
            gt_entities=gt_entities,
            pred_spans=raw_pred_spans,
            gt_label_map=gt_label_map,
            pred_label_map=pred_label_map,
        )

        matches = match_res["matches"]
        unmatched_gt = match_res["unmatched_gt_indices"]
        unmatched_pred = match_res["unmatched_pred_indices"]
        mapped_preds = match_res["mapped_preds"]
        unmapped_preds = match_res["unmapped_preds"]

        # Track unmapped predictions
        for up in unmapped_preds:
            unmapped_counter[up.get("label", "UNKNOWN")] += 1

        # Count predicted types
        for mp in mapped_preds:
            pred_counts_by_type[mp["mapped_label"]] += 1

        # Process matches
        for m in matches:
            gt_t = m["gt_type"]
            pred_t = m["pred_type"]
            confusion_matrix[gt_t][pred_t] += 1

            if m["same_type"]:
                tp_overlap[gt_t] += 1
                if m["is_strict"]:
                    tp_strict[gt_t] += 1

            # Check ID cued vs bare
            if gt_t == "ID":
                is_cued = m["gt_entity"].get("cued", False)
                k = "cued" if is_cued else "bare"
                if m["same_type"]:
                    id_stats[k]["tp_overlap"] += 1
                    id_stats["overall"]["tp_overlap"] += 1
                    if m["is_strict"]:
                        id_stats[k]["tp_strict"] += 1
                        id_stats["overall"]["tp_strict"] += 1

        # Process unmatched GT entities (Misses)
        for g_idx in unmatched_gt:
            g = gt_entities[g_idx]
            gt_t = gt_label_map.get(g["type"], g["type"])
            confusion_matrix[gt_t]["NONE"] += 1

        # Process unmatched predictions (False Positives)
        for p_idx in unmatched_pred:
            p = mapped_preds[p_idx]
            pred_t = p["mapped_label"]
            confusion_matrix["NONE"][pred_t] += 1

            # Check if this false positive hits any decoy
            for dec in decoys:
                dec_start, dec_end = dec["start"], dec["end"]
                if max(p["start"], dec_start) < min(p["end"], dec_end):
                    decoy_hits_count += 1
                    decoy_hits_by_type[dec["type"]] += 1
                    break

        # Count GT types & ID cued/bare totals
        for g in gt_entities:
            gt_t = gt_label_map.get(g["type"], g["type"])
            gt_counts_by_type[gt_t] += 1
            if gt_t == "ID":
                is_cued = g.get("cued", False)
                k = "cued" if is_cued else "bare"
                id_stats[k]["total"] += 1
                id_stats["overall"]["total"] += 1

        # 2. Character-level Leak Rate & Exposure
        # Union of all mapped predicted span character positions
        predicted_char_positions: set[int] = set()
        for p in mapped_preds:
            predicted_char_positions.update(range(p["start"], p["end"]))

        all_pii_char_positions: set[int] = set()

        for g in gt_entities:
            gt_t = gt_label_map.get(g["type"], g["type"])
            g_start, g_end = g["start"], g["end"]
            g_chars = set(range(g_start, g_end))
            g_len = len(g_chars)

            all_pii_char_positions.update(g_chars)
            total_pii_chars += g_len
            pii_chars_by_type[gt_t] += g_len
            pii_chars_by_doc_type[doc_type] += g_len

            covered_chars = len(g_chars & predicted_char_positions)
            uncovered_chars = g_len - covered_chars

            uncovered_pii_chars += uncovered_chars
            uncovered_pii_chars_by_type[gt_t] += uncovered_chars
            uncovered_pii_chars_by_doc_type[doc_type] += uncovered_chars

            total_entities += 1
            entities_by_type[gt_t] += 1

            if covered_chars == 0:
                fully_leaked_entities += 1
                fully_leaked_by_type[gt_t] += 1
            elif covered_chars < g_len:
                partially_exposed_entities += 1
                partially_exposed_by_type[gt_t] += 1
            else:
                completely_redacted_entities += 1

        # 3. Non-PII Over-redaction
        # If doc_length is not stored or 0, fallback to max index
        if doc_length == 0:
            doc_length = max(
                (g["end"] for g in gt_entities),
                default=0
            )
            doc_length = max(
                doc_length,
                max((p["end"] for p in mapped_preds), default=0)
            )

        non_pii_total = max(0, doc_length - len(all_pii_char_positions))
        non_pii_covered = len(predicted_char_positions - all_pii_char_positions)
        total_non_pii_chars += non_pii_total
        covered_non_pii_chars += non_pii_covered

    # ---------------------------------------------------------------------------
    # Compute per-type and overall Precision, Recall, F1
    # ---------------------------------------------------------------------------
    metrics_strict: dict[str, dict[str, float | int]] = {}
    metrics_overlap: dict[str, dict[str, float | int]] = {}

    tot_tp_strict = sum(tp_strict.values())
    tot_tp_overlap = sum(tp_overlap.values())
    tot_pred = sum(pred_counts_by_type.values())
    tot_gt = sum(gt_counts_by_type.values())

    for t in all_types:
        n_gt = gt_counts_by_type[t]
        n_pred = pred_counts_by_type[t]

        # Strict
        tp_s = tp_strict[t]
        fp_s = n_pred - tp_s
        fn_s = n_gt - tp_s
        p_s = (tp_s / n_pred) if n_pred > 0 else 0.0
        r_s = (tp_s / n_gt) if n_gt > 0 else 0.0
        f1_s = (2 * p_s * r_s / (p_s + r_s)) if (p_s + r_s) > 0 else 0.0
        metrics_strict[t] = {
            "precision": p_s,
            "recall": r_s,
            "f1": f1_s,
            "tp": tp_s,
            "fp": fp_s,
            "fn": fn_s,
            "gt_count": n_gt,
            "pred_count": n_pred,
        }

        # Overlap
        tp_o = tp_overlap[t]
        fp_o = n_pred - tp_o
        fn_o = n_gt - tp_o
        p_o = (tp_o / n_pred) if n_pred > 0 else 0.0
        r_o = (tp_o / n_gt) if n_gt > 0 else 0.0
        f1_o = (2 * p_o * r_o / (p_o + r_o)) if (p_o + r_o) > 0 else 0.0
        metrics_overlap[t] = {
            "precision": p_o,
            "recall": r_o,
            "f1": f1_o,
            "tp": tp_o,
            "fp": fp_o,
            "fn": fn_o,
            "gt_count": n_gt,
            "pred_count": n_pred,
        }

    # Micro-averaged overall
    tot_p_strict = (tot_tp_strict / tot_pred) if tot_pred > 0 else 0.0
    tot_r_strict = (tot_tp_strict / tot_gt) if tot_gt > 0 else 0.0
    tot_f1_strict = (
        (2 * tot_p_strict * tot_r_strict / (tot_p_strict + tot_r_strict))
        if (tot_p_strict + tot_r_strict) > 0 else 0.0
    )
    metrics_strict["overall"] = {
        "precision": tot_p_strict,
        "recall": tot_r_strict,
        "f1": tot_f1_strict,
        "tp": tot_tp_strict,
        "fp": tot_pred - tot_tp_strict,
        "fn": tot_gt - tot_tp_strict,
        "gt_count": tot_gt,
        "pred_count": tot_pred,
    }

    tot_p_overlap = (tot_tp_overlap / tot_pred) if tot_pred > 0 else 0.0
    tot_r_overlap = (tot_tp_overlap / tot_gt) if tot_gt > 0 else 0.0
    tot_f1_overlap = (
        (2 * tot_p_overlap * tot_r_overlap / (tot_p_overlap + tot_r_overlap))
        if (tot_p_overlap + tot_r_overlap) > 0 else 0.0
    )
    metrics_overlap["overall"] = {
        "precision": tot_p_overlap,
        "recall": tot_r_overlap,
        "f1": tot_f1_overlap,
        "tp": tot_tp_overlap,
        "fp": tot_pred - tot_tp_overlap,
        "fn": tot_gt - tot_tp_overlap,
        "gt_count": tot_gt,
        "pred_count": tot_pred,
    }

    # ---------------------------------------------------------------------------
    # Leak Rates
    # ---------------------------------------------------------------------------
    overall_leak_rate = (uncovered_pii_chars / total_pii_chars) if total_pii_chars > 0 else 0.0

    leak_rate_by_type = {}
    for t in all_types:
        tot_chars = pii_chars_by_type[t]
        unc_chars = uncovered_pii_chars_by_type[t]
        leak_rate_by_type[t] = (unc_chars / tot_chars) if tot_chars > 0 else 0.0

    leak_rate_by_doc_type = {}
    for dt, tot_chars in pii_chars_by_doc_type.items():
        unc_chars = uncovered_pii_chars_by_doc_type[dt]
        leak_rate_by_doc_type[dt] = (unc_chars / tot_chars) if tot_chars > 0 else 0.0

    # ---------------------------------------------------------------------------
    # Entity Exposure
    # ---------------------------------------------------------------------------
    total_exposed = fully_leaked_entities + partially_exposed_entities
    exposure_rate = (total_exposed / total_entities) if total_entities > 0 else 0.0
    fully_leaked_rate = (fully_leaked_entities / total_entities) if total_entities > 0 else 0.0
    partially_exposed_rate = (partially_exposed_entities / total_entities) if total_entities > 0 else 0.0

    exposure_by_type = {}
    for t in all_types:
        ent_count = entities_by_type[t]
        fl = fully_leaked_by_type[t]
        pe = partially_exposed_by_type[t]
        exposure_by_type[t] = {
            "total_entities": ent_count,
            "fully_leaked": fl,
            "fully_leaked_rate": (fl / ent_count) if ent_count > 0 else 0.0,
            "partially_exposed": pe,
            "partially_exposed_rate": (pe / ent_count) if ent_count > 0 else 0.0,
            "total_exposed": fl + pe,
            "exposure_rate": ((fl + pe) / ent_count) if ent_count > 0 else 0.0,
        }

    # ---------------------------------------------------------------------------
    # ID Recall (cued vs bare)
    # ---------------------------------------------------------------------------
    id_recall_results = {}
    for k in ("cued", "bare", "overall"):
        tot = id_stats[k]["total"]
        tp_s = id_stats[k]["tp_strict"]
        tp_o = id_stats[k]["tp_overlap"]
        id_recall_results[k] = {
            "total": tot,
            "tp_strict": tp_s,
            "tp_overlap": tp_o,
            "recall_strict": (tp_s / tot) if tot > 0 else 0.0,
            "recall_overlap": (tp_o / tot) if tot > 0 else 0.0,
        }

    # ---------------------------------------------------------------------------
    # Over-redaction
    # ---------------------------------------------------------------------------
    over_redaction_rate = (
        (covered_non_pii_chars / total_non_pii_chars)
        if total_non_pii_chars > 0 else 0.0
    )

    # ---------------------------------------------------------------------------
    # Latency: exclude warm-up (first 5 documents)
    # ---------------------------------------------------------------------------
    if len(latencies) > 5:
        timed_latencies = latencies[5:]
        warmup_excluded = 5
    else:
        timed_latencies = latencies
        warmup_excluded = 0

    latency_median = compute_percentile(timed_latencies, 50.0)
    latency_p95 = compute_percentile(timed_latencies, 95.0)
    latency_mean = (sum(timed_latencies) / len(timed_latencies)) if timed_latencies else 0.0

    return {
        "split": split,
        "doc_count": len(docs_in_split),
        "leak_rate": {
            "overall": overall_leak_rate,
            "per_type": leak_rate_by_type,
            "per_doc_type": leak_rate_by_doc_type,
            "total_pii_chars": total_pii_chars,
            "uncovered_pii_chars": uncovered_pii_chars,
        },
        "entity_exposure": {
            "total_entities": total_entities,
            "fully_leaked_count": fully_leaked_entities,
            "fully_leaked_rate": fully_leaked_rate,
            "partially_exposed_count": partially_exposed_entities,
            "partially_exposed_rate": partially_exposed_rate,
            "total_exposed_count": total_exposed,
            "exposure_rate": exposure_rate,
            "per_type": exposure_by_type,
        },
        "over_redaction": {
            "total_non_pii_chars": total_non_pii_chars,
            "covered_non_pii_chars": covered_non_pii_chars,
            "rate": over_redaction_rate,
        },
        "metrics_strict": metrics_strict,
        "metrics_overlap": metrics_overlap,
        "confusion_matrix": confusion_matrix,
        "id_recall": id_recall_results,
        "decoys": {
            "total_hits": decoy_hits_count,
            "hit_rate": (decoy_hits_count / tot_pred) if tot_pred > 0 else 0.0,
            "by_decoy_type": dict(decoy_hits_by_type),
        },
        "unmapped_predictions": {
            "total": sum(unmapped_counter.values()),
            "by_label": dict(unmapped_counter),
        },
        "latency": {
            "median_ms": latency_median,
            "p95_ms": latency_p95,
            "mean_ms": latency_mean,
            "warmup_excluded": warmup_excluded,
            "measured_doc_count": len(timed_latencies),
        },
    }
