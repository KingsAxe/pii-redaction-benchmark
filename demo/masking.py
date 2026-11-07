"""Character-position masking; no entity assignment or model execution."""
import hashlib
import json
from collections import Counter

from scripts.metrics import DEFAULT_PRED_LABEL_MAP

CONFIGURATION = "custom_generic"
MAX_CODE_POINTS = 20_000


class InvalidPredictions(ValueError):
    """Analyzer output cannot be applied to this canonical text."""


def canonicalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def make_proposal(text, results, source_hash):
    covered, labels = set(), Counter()
    raw_count = mapped_count = 0
    if not isinstance(results, (list, tuple)):
        raise InvalidPredictions()
    for result in results:
        label = getattr(result, "entity_type", None)
        start, end = getattr(result, "start", None), getattr(result, "end", None)
        if (not isinstance(label, str) or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text)):
            raise InvalidPredictions()
        raw_count += 1
        if label in DEFAULT_PRED_LABEL_MAP:
            mapped_count += 1
            labels[DEFAULT_PRED_LABEL_MAP[label]] += 1
            covered.update(range(start, end))
    line_breaks = sum(text[index] == "\n" for index in covered)
    masked = "".join("#" if index in covered and char != "\n" else char
                     for index, char in enumerate(text))
    revision_material = json.dumps([CONFIGURATION, source_hash, text, masked], ensure_ascii=False).encode("utf-8")
    return {
        "canonical_original": text,
        "masked_proposal": masked,
        "configuration": CONFIGURATION,
        "frozen_source_sha256": source_hash,
        "document_id": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "revision_id": hashlib.sha256(revision_material).hexdigest(),
        "detection_counts": {"raw_span_count": raw_count, "mapped_span_count": mapped_count,
                             "ignored_span_count": raw_count - mapped_count,
                             "spans_by_mapped_label": dict(sorted(labels.items())),
                             "covered_code_point_count": len(covered),
                             "masked_code_point_count": len(covered) - line_breaks,
                             "covered_lf_count": line_breaks},
        "review_required": True,
    }
