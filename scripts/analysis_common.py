"""Diagnostics built on the unchanged Phase 2 matching and label mappings."""
if __package__:
    from .metrics import DEFAULT_PRED_LABEL_MAP, GT_LABEL_MAP, match_entities_and_predictions, score
    from .runner_common import document_id
else:
    from metrics import DEFAULT_PRED_LABEL_MAP, GT_LABEL_MAP, match_entities_and_predictions, score
    from runner_common import document_id


def overlap(a, b):
    return max(a["start"], b["start"]) < min(a["end"], b["end"])


def scorer_predictions(docs, predictions):
    # Phase 2 resolves file keys; adapt IDs in memory without changing artifacts.
    return {doc["file"]: predictions[document_id(doc)] for doc in docs}


def id_diagnostics(docs, predictions, split, metrics=None):
    docs = [doc for doc in docs if doc["split"] == split]
    if metrics is None:
        metrics = score(docs, scorer_predictions(docs, predictions), split=split)
    result = {
        "id_precision_strict": metrics["metrics_strict"]["ID"]["precision"],
        "id_precision_overlap": metrics["metrics_overlap"]["ID"]["precision"],
        "id_prediction_count": metrics["metrics_strict"]["ID"]["pred_count"],
        "order_id_decoys_hit_by_id": 0,
        "id_entities_assigned_phone": 0,
        "id_entities_fully_uncovered": 0,
        "id_entities_partially_uncovered": 0,
        "id_entities_any_uncovered": 0,
        "id_entities_phone_or_any_uncovered": 0,
    }
    for doc in docs:
        spans = predictions[document_id(doc)]["spans"]
        matched = match_entities_and_predictions(doc["entities"], spans)
        mapped = matched["mapped_preds"]
        ids = [span for span in mapped if span["mapped_label"] == "ID"]
        # Count distinct decoy annotations, not prediction-decoy pairs.
        result["order_id_decoys_hit_by_id"] += sum(
            decoy["type"] == "ORDER_ID" and any(overlap(decoy, span) for span in ids)
            for decoy in doc["decoys"])
        phone_entities = {m["gt_idx"] for m in matched["matches"]
                          if m["gt_type"] == "ID" and m["pred_type"] == "PHONE"}
        result["id_entities_assigned_phone"] += len(phone_entities)
        covered = {i for span in mapped for i in range(span["start"], span["end"])}
        for index, entity in enumerate(doc["entities"]):
            if GT_LABEL_MAP.get(entity["type"], entity["type"]) != "ID":
                continue
            chars = set(range(entity["start"], entity["end"]))
            uncovered = len(chars - covered)
            result["id_entities_fully_uncovered"] += uncovered == len(chars)
            result["id_entities_partially_uncovered"] += 0 < uncovered < len(chars)
            result["id_entities_any_uncovered"] += uncovered > 0
            result["id_entities_phone_or_any_uncovered"] += index in phone_entities or uncovered > 0
    return result
