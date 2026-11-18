"""HTTP smoke test of a running local service, using the first dev ID only."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from demo.masking import CONFIGURATION, canonicalize
from scripts.runner_common import CUSTOM_SOURCES, ROOT, document_id, load_doc_text, load_ground_truth, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "demo/output/smoke.json")
    args = parser.parse_args(argv)
    doc = next(doc for doc in load_ground_truth() if doc["split"] == "dev")
    original = load_doc_text(doc)
    canonical = canonicalize(original)
    source_hash = hashlib.sha256(CUSTOM_SOURCES[CONFIGURATION].read_bytes()).hexdigest()
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120.0, trust_env=False) as client:
        health = client.get("/health")
        health.raise_for_status()
        assert health.json() == {"ready": True, "configuration": CONFIGURATION}
        response = client.post("/mask", json={"text": original, "synthetic_input": True})
        response.raise_for_status()
        result = response.json()
        assert result["configuration"] == CONFIGURATION
        assert result["canonical_original"] == canonical
        assert result["review_required"] is True
        assert result["frozen_source_sha256"] == source_hash
        assert len(result["masked_proposal"]) == len(canonical)
        assert [i for i, c in enumerate(result["masked_proposal"]) if c == "\n"] == [i for i, c in enumerate(canonical) if c == "\n"]
        assert all(new == old or new == "#" for old, new in zip(canonical, result["masked_proposal"]))
        counts = result["detection_counts"]
        assert counts["masked_code_point_count"] + counts["covered_lf_count"] == counts["covered_code_point_count"]
        canary = "SYNTHETIC_VALIDATION_CANARY"
        invalid = client.post("/mask", json={"text": canary, "synthetic_input": False})
        assert invalid.status_code == 422 and canary not in invalid.text
    record = {"observed_utc": datetime.now(timezone.utc).isoformat(),
              "document_id": document_id(doc), "split": "dev",
              "selection_rule": "First development document in lexicographic document-ID order",
              "input_sha256": hashlib.sha256((ROOT / doc["file"]).read_bytes()).hexdigest(),
              "configuration": CONFIGURATION, "frozen_source_sha256": source_hash,
              "health_http_status": health.status_code, "mask_http_status": response.status_code,
              "invalid_acknowledgement_http_status": invalid.status_code,
              "canonical_code_points": len(canonical), "detection_counts": counts,
              "proposal_sha256": hashlib.sha256(result["masked_proposal"].encode("utf-8")).hexdigest(),
              "document_digest": result["document_id"], "revision_id": result["revision_id"],
              "review_required": result["review_required"],
              "checks": "Canonical text, aligned proposal, LF positions, source hash, counts, and text-free validation error passed",
              "scope": "Real frozen analyzer HTTP smoke only; no accuracy or workflow timing trial"}
    write_json(args.output, record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
