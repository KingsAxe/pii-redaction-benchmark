"""
verify_ground_truth.py – Gate check for Phase 1.

Asserts:
  1. text[start:end] == stored text for every entity and decoy, read from .txt files on disk.
  2. No two entities within the same document have overlapping spans.
  3. Every document has character count matching 'length'.
  4. Every BVN and NIN entity has a boolean 'cued' field.
  5. Every PERSON and PHONE entity has a 'format' string field.
  6. Exactly 150 ORDER_ID decoys in total (fails if != 150).
  7. No ORDER_ID decoy equals any PII entity text in the same document.

Prints:
  - Document counts overall and per split.
  - Total entities and decoys.
  - ORDER_ID decoys per doc_type and total.
  - Cued vs bare split for BVN, NIN, and combined ID overall and per split (dev/test).
  - Counts per PERSON format.
  - Counts per PHONE format.
  - Overall entity and decoy counts by type and doc_type.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GT_PATH = ROOT / "data" / "ground_truth.json"


def load_text_from_disk(rel_path: str) -> str:
    """Read document text directly from the .txt file on disk with utf-8."""
    full_path = ROOT / rel_path
    if not full_path.exists():
        raise FileNotFoundError(f"File on disk not found: {full_path}")
    with open(full_path, "r", encoding="utf-8") as fh:
        return fh.read()


def verify_document_spans(doc: dict, text_on_disk: str) -> list[str]:
    """Verify that every stored start:end span exactly matches text on disk."""
    errors = []
    # Verify length field
    if doc.get("length") is not None and doc["length"] != len(text_on_disk):
        errors.append(
            f"[{doc['file']}] length mismatch: stored {doc.get('length')} vs actual {len(text_on_disk)}"
        )

    all_items = doc["entities"] + doc["decoys"]
    for item in all_items:
        start = item["start"]
        end = item["end"]
        expected = item["text"]
        actual = text_on_disk[start:end]
        if actual != expected:
            errors.append(
                f"[{doc['file']}] span mismatch for {item['type']}: "
                f"expected {expected!r}, got {actual!r} at ({start}:{end})"
            )
    return errors


def verify_no_overlaps(doc: dict) -> list[str]:
    """Verify that no two entities overlap within the document."""
    errors = []
    ents = sorted(doc["entities"], key=lambda x: x["start"])
    for i in range(len(ents) - 1):
        a, b = ents[i], ents[i + 1]
        if a["end"] > b["start"]:
            errors.append(
                f"[{doc['file']}] entity overlap: "
                f"{a['type']}({a['start']}:{a['end']} {a['text']!r}) vs "
                f"{b['type']}({b['start']}:{b['end']} {b['text']!r})"
            )
    return errors


def main() -> int:
    if not GT_PATH.exists():
        print(f"ERROR: ground_truth.json not found at {GT_PATH}", file=sys.stderr)
        print("Run: venv\\Scripts\\python.exe scripts/generate_data.py", file=sys.stderr)
        return 1

    with open(GT_PATH, "r", encoding="utf-8") as fh:
        ground_truth = json.load(fh)

    all_errors: list[str] = []

    # Counters and aggregators
    total_docs = len(ground_truth)
    split_counts: dict[str, int] = defaultdict(int)
    total_ents = 0
    total_decoys = 0

    order_ids_by_doc_type: dict[str, int] = defaultdict(int)
    total_order_ids = 0

    # ID cued/bare tracking: split -> id_type -> {"cued": count, "bare": count}
    cued_stats: dict[str, dict[str, dict[str, int]]] = {
        "overall": {"BVN": {"cued": 0, "bare": 0}, "NIN": {"cued": 0, "bare": 0}},
        "dev":     {"BVN": {"cued": 0, "bare": 0}, "NIN": {"cued": 0, "bare": 0}},
        "test":    {"BVN": {"cued": 0, "bare": 0}, "NIN": {"cued": 0, "bare": 0}},
    }

    person_format_counts: dict[str, int] = defaultdict(int)
    phone_format_counts: dict[str, int] = defaultdict(int)

    by_type: dict[str, int] = defaultdict(int)
    by_doc_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for doc in ground_truth:
        split = doc["split"]
        doc_type = doc["doc_type"]
        split_counts[split] += 1

        # Read text from disk
        try:
            text_on_disk = load_text_from_disk(doc["file"])
        except Exception as e:
            all_errors.append(str(e))
            continue

        # Check spans and overlaps
        all_errors.extend(verify_document_spans(doc, text_on_disk))
        all_errors.extend(verify_no_overlaps(doc))

        pii_entity_texts = set()

        for ent in doc["entities"]:
            etype = ent["type"]
            by_type[etype] += 1
            by_doc_type[doc_type][etype] += 1
            total_ents += 1
            pii_entity_texts.add(ent["text"])

            # Verify BVN / NIN "cued" flag
            if etype in ("BVN", "NIN"):
                if "cued" not in ent or not isinstance(ent["cued"], bool):
                    all_errors.append(
                        f"[{doc['file']}] {etype} entity missing valid 'cued' boolean flag: {ent}"
                    )
                else:
                    k = "cued" if ent["cued"] else "bare"
                    cued_stats["overall"][etype][k] += 1
                    cued_stats[split][etype][k] += 1

            # Verify PERSON "format" string
            if etype == "PERSON":
                if "format" not in ent or not isinstance(ent["format"], str):
                    all_errors.append(
                        f"[{doc['file']}] PERSON entity missing valid 'format' string: {ent}"
                    )
                else:
                    person_format_counts[ent["format"]] += 1

            # Verify PHONE "format" string
            if etype == "PHONE":
                if "format" not in ent or not isinstance(ent["format"], str):
                    all_errors.append(
                        f"[{doc['file']}] PHONE entity missing valid 'format' string: {ent}"
                    )
                else:
                    phone_format_counts[ent["format"]] += 1

        for dec in doc["decoys"]:
            dtype = dec["type"]
            by_doc_type[doc_type][f"DECOY:{dtype}"] += 1
            total_decoys += 1

            if dtype == "ORDER_ID":
                total_order_ids += 1
                order_ids_by_doc_type[doc_type] += 1
                # Check collision with PII in same doc
                if dec["text"] in pii_entity_texts:
                    all_errors.append(
                        f"[{doc['file']}] ORDER_ID decoy equals PII text in same document: {dec['text']}"
                    )

    # Constraint Check 1: exactly 150 ORDER_ID decoys
    if total_order_ids != 150:
        all_errors.append(
            f"ORDER_ID decoy count failure: expected exactly 150, found {total_order_ids}"
        )

    # Constraint Check 2: exactly 50 per doc_type
    for dt in ("health_report", "hr_intake", "vendor_invoice"):
        if order_ids_by_doc_type[dt] != 50:
            all_errors.append(
                f"ORDER_ID count failure for {dt}: expected 50, found {order_ids_by_doc_type[dt]}"
            )

    # Fail immediately if any assertion failed
    if all_errors:
        print(f"\n{'='*70}", file=sys.stderr)
        print(f"VERIFICATION FAILED ({len(all_errors)} error(s)):", file=sys.stderr)
        for err in all_errors[:20]:
            print(f"  ERROR: {err}", file=sys.stderr)
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more errors", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)
        return 1

    # ---------------------------------------------------------------------------
    # Print formatted verification report
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("VERIFY GROUND TRUTH - ALL CHECKS PASSED")
    print("=" * 70)

    print(f"\nDocuments: {total_docs} total (dev={split_counts['dev']}, test={split_counts['test']})")
    print(f"Total entities: {total_ents}")
    print(f"Total decoys  : {total_decoys}")

    print("\n" + "-" * 70)
    print("ORDER_ID DECOY COUNTS (Constraint: exactly 150 total, 50 per doc_type)")
    print("-" * 70)
    for dt, count in sorted(order_ids_by_doc_type.items()):
        print(f"  {dt:<20}: {count:>4} / 50")
    print(f"  {'TOTAL':<20}: {total_order_ids:>4} / 150  [PASS]")

    print("\n" + "-" * 70)
    print("CUED vs BARE ID SPLIT (Aim: ~60% cued, ~40% bare)")
    print("-" * 70)
    for scope in ("overall", "dev", "test"):
        stats = cued_stats[scope]
        bvn_c = stats["BVN"]["cued"]
        bvn_b = stats["BVN"]["bare"]
        bvn_tot = bvn_c + bvn_b
        bvn_pct = (bvn_c / bvn_tot * 100) if bvn_tot else 0

        nin_c = stats["NIN"]["cued"]
        nin_b = stats["NIN"]["bare"]
        nin_tot = nin_c + nin_b
        nin_pct = (nin_c / nin_tot * 100) if nin_tot else 0

        id_c = bvn_c + nin_c
        id_b = bvn_b + nin_b
        id_tot = id_c + id_b
        id_pct = (id_c / id_tot * 100) if id_tot else 0

        print(f"  [{scope.upper()}]")
        print(f"    BVN : {bvn_c:>4} cued ({bvn_pct:>5.1f}%) | {bvn_b:>4} bare | {bvn_tot:>4} total")
        print(f"    NIN : {nin_c:>4} cued ({nin_pct:>5.1f}%) | {nin_b:>4} bare | {nin_tot:>4} total")
        print(f"    ID  : {id_c:>4} cued ({id_pct:>5.1f}%) | {id_b:>4} bare | {id_tot:>4} total")

    print("\n" + "-" * 70)
    print("PERSON FORMAT COUNTS")
    print("-" * 70)
    for fmt, count in sorted(person_format_counts.items(), key=lambda x: -x[1]):
        print(f"  {fmt:<22}: {count:>4}")

    print("\n" + "-" * 70)
    print("PHONE FORMAT COUNTS")
    print("-" * 70)
    for fmt, count in sorted(phone_format_counts.items(), key=lambda x: -x[1]):
        print(f"  {fmt:<22}: {count:>4}")

    print("\n" + "-" * 70)
    print("ALL ENTITY COUNTS BY TYPE")
    print("-" * 70)
    for etype, count in sorted(by_type.items()):
        print(f"  {etype:<15}: {count:>5}")

    print("\n" + "-" * 70)
    print("COUNTS BY DOCUMENT TYPE")
    print("-" * 70)
    for doc_type in sorted(by_doc_type):
        print(f"\n  [{doc_type}]")
        for label, count in sorted(by_doc_type[doc_type].items()):
            print(f"    {label:<25} {count:>5}")

    print("\n" + "=" * 70)
    print("ALL GATE ASSERTIONS VERIFIED SUCCESSFULLY")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
