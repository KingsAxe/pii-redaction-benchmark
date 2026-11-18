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


def merged_intervals(positions):
    """Canonical sorted, merged, half-open intervals, including covered LF."""
    intervals = []
    for position in sorted(positions):
        if intervals and intervals[-1][1] == position:
            intervals[-1][1] = position + 1
        else:
            intervals.append([position, position + 1])
    return intervals


def interval_positions(intervals, text_length):
    """Validate correction intervals before creating their character union."""
    if not isinstance(intervals, list) or len(intervals) > MAX_CODE_POINTS:
        raise ValueError("Invalid intervals")
    positions = set()
    for interval in intervals:
        if (not isinstance(interval, (list, tuple)) or len(interval) != 2
                or any(type(value) is not int for value in interval)):
            raise ValueError("Invalid intervals")
        start, end = interval
        if not 0 <= start < end <= text_length:
            raise ValueError("Invalid intervals")
        positions.update(range(start, end))
    return positions


def render_mask(text, positions):
    line_breaks = sum(text[index] == "\n" for index in positions)
    masked = "".join("#" if index in positions and char != "\n" else char
                     for index, char in enumerate(text))
    return masked, {"covered_code_point_count": len(positions),
                    "masked_code_point_count": len(positions) - line_breaks,
                    "covered_lf_count": line_breaks}


def revision_identity(text, source_hash, intervals, review_context=None):
    # Explicit coverage distinguishes a covered original # or LF from no coverage.
    material = ["coverage-v2", CONFIGURATION, source_hash, text, intervals, review_context]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


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
    intervals = merged_intervals(covered)
    masked, counts = render_mask(text, covered)
    return {
        "canonical_original": text,
        "masked_proposal": masked,
        "configuration": CONFIGURATION,
        "frozen_source_sha256": source_hash,
        "document_id": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "revision_id": revision_identity(text, source_hash, intervals),
        "mask_intervals": intervals,
        "detection_counts": {"raw_span_count": raw_count, "mapped_span_count": mapped_count,
                             "ignored_span_count": raw_count - mapped_count,
                             "spans_by_mapped_label": dict(sorted(labels.items())),
                             **counts},
        "review_required": True,
    }
