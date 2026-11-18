"""Live, annotation-assisted API walkthrough on the first development ID.

This verifies workflow behavior, not blind human review or timing performance.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from demo.masking import canonicalize, interval_positions
from scripts.runner_common import ROOT, document_id, load_doc_text, load_ground_truth, write_json


def check_output(client, review):
    response = client.get(f'/reviews/{review["review_id"]}/output', params={"expected_revision": review["revision_id"]})
    response.raise_for_status()
    text = review["canonical_original"]
    positions = interval_positions(review["mask_intervals"], len(text))
    expected = "".join("#" if i in positions and char != "\n" else char for i, char in enumerate(text))
    assert response.text == expected == review["masked_text"]
    assert response.headers["X-Review-Revision"] == review["revision_id"]
    assert len(response.text) == len(text)
    return {"http_status": response.status_code, "revision_id": review["revision_id"],
            "output_sha256": hashlib.sha256(response.content).hexdigest(), "matches_approved_mask": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "demo/output/review_walkthrough.json")
    args = parser.parse_args(argv)
    doc = next(doc for doc in load_ground_truth() if doc["split"] == "dev")
    text = canonicalize(load_doc_text(doc))
    address = next(entity for entity in doc["entities"] if entity["type"] == "ADDRESS")
    decoy = next(decoy for decoy in doc["decoys"] if decoy["type"] == "ORDER_ID")
    steps = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120, trust_env=False) as client:
        created = client.post("/reviews", json={"text": text, "synthetic_input": True})
        assert created.status_code == 201
        review = created.json()
        assert review["canonical_original"] == text and review["configuration"] == "custom_generic"
        initial = review
        review_path = f'/reviews/{review["review_id"]}'
        inspected = client.get(review_path)
        assert inspected.status_code == 200 and inspected.json()["revision_id"] == review["revision_id"]
        denied = client.get(review_path + "/output", params={"expected_revision": review["revision_id"]})
        assert denied.status_code == 409
        steps.append({"action": "create_inspect_and_deny_unapproved_output", "create_status": created.status_code,
                      "inspect_status": inspected.status_code, "output_status": denied.status_code})

        for operation, entity in [("add", address), ("remove", decoy)]:
            selected = set(range(entity["start"], entity["end"]))
            covered = interval_positions(review["mask_intervals"], len(text))
            assert selected - covered if operation == "add" else selected & covered
            response = client.patch(review_path + "/mask", json={"expected_revision": review["revision_id"],
                                      "operation": operation, "intervals": [[entity["start"], entity["end"]]]})
            assert response.status_code == 200
            review = response.json()
            steps.append({"action": operation, "annotation_type": entity["type"],
                          "interval": [entity["start"], entity["end"]], "http_status": response.status_code,
                          "revision_id": review["revision_id"]})

        stale = client.post(review_path + "/approve", json={"expected_revision": initial["revision_id"]})
        assert stale.status_code == 409
        approved_response = client.post(review_path + "/approve", json={"expected_revision": review["revision_id"]})
        assert approved_response.status_code == 200
        approved = approved_response.json()
        first_output = check_output(client, approved)
        steps.append({"action": "approve_and_retrieve", "stale_approval_status": stale.status_code, **first_output})

        # A covered LF is invisible in display; removing it must still invalidate approval.
        lf = next(i for i in interval_positions(approved["mask_intervals"], len(text)) if text[i] == "\n")
        correction = client.patch(review_path + "/mask", json={"expected_revision": approved["revision_id"],
                                    "operation": "remove", "intervals": [[lf, lf + 1]]})
        assert correction.status_code == 200
        review = correction.json()
        assert review["masked_text"] == approved["masked_text"]
        assert review["revision_id"] != approved["revision_id"] and review["status"] == "pending"
        old_output = client.get(review_path + "/output", params={"expected_revision": approved["revision_id"]})
        new_output = client.get(review_path + "/output", params={"expected_revision": review["revision_id"]})
        assert old_output.status_code == new_output.status_code == 409
        steps.append({"action": "remove_covered_lf_and_invalidate", "interval": [lf, lf + 1],
                      "display_unchanged": True, "revision_changed": True,
                      "old_output_status": old_output.status_code, "pending_output_status": new_output.status_code})
        response = client.post(review_path + "/approve", json={"expected_revision": review["revision_id"]})
        assert response.status_code == 200
        final = response.json()
        steps.append({"action": "approve_current_and_retrieve", **check_output(client, final)})
    record = {"observed_utc": datetime.now(timezone.utc).isoformat(), "document_id": document_id(doc), "split": "dev",
              "selection_rule": "First development document in lexicographic document-ID order, not performance",
              "correction_selection": "Annotation-assisted inspection: complete the first ADDRESS and remove coverage of the first ORDER_ID decoy; then test covered-LF invalidation",
              "input_sha256": hashlib.sha256((ROOT / doc["file"]).read_bytes()).hexdigest(),
              "annotation_key_sha256": hashlib.sha256((ROOT / "data/ground_truth.json").read_bytes()).hexdigest(),
              "configuration": final["configuration"], "frozen_source_sha256": final["frozen_source_sha256"],
              "review_id": final["review_id"], "initial_mask_intervals": initial["mask_intervals"],
              "final_mask_intervals": final["mask_intervals"], "detection_counts": final["detection_counts"],
              "final_coverage_counts": final["coverage_counts"], "steps": steps,
              "final_status_at_verification": final["status"],
              "scope": "Real analyzer and live HTTP review workflow verification; not a blind human review, accuracy evaluation, productivity study, or timing trial",
              "browser_status": "Browser connection unavailable; no interactive browser or visual inspection claimed. Actual JS offset/text-rendering helpers tested separately."}
    write_json(args.output, record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
