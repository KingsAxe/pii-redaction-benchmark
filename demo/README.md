# Local synthetic-text masking review

This Phase 6 demonstration exposes the frozen `custom_generic` analyzer through FastAPI and a plain HTML/JavaScript review page. Submit synthetic text, inspect the proposal, correct the mask, reject or explicitly approve the current revision, and retrieve its output. Neither detection nor human approval establishes that all PII has been found.

Use synthetic English text only. Development documents and tiny hand-built fixtures are used here; held-out test documents are excluded from demo development. The broader workflow remains in [the Phase 6 plan](../docs/PHASE6_DEMO_PLAN.md).

## Setup (PowerShell, repository root)

Keep the existing benchmark environment and root requirements unchanged. Create a separate environment without system site packages:

```powershell
python --version
python -m venv demo/.venv
.\demo\.venv\Scripts\python.exe -m pip install --cache-dir demo/.cache/pip --timeout 60 -r demo/requirements.txt
.\demo\.venv\Scripts\python.exe -m pip check
```

Tested on Windows 11 Pro with Python 3.12.6 and PowerShell 5.1. Exact installed package versions are pinned in [requirements.txt](requirements.txt); [environment.json](environment.json) records the inspection. Key versions: FastAPI 0.162.0, Uvicorn 0.54.0, Starlette 1.10.0, spaCy 3.8.18, Presidio Analyzer 2.2.366, and `en_core_web_sm` 3.8.0. Compatibility was checked with pip's resolver, `pip check`, tests, and the actual analyzer smoke test. Shared runtime packages were constrained to the benchmark's installed pins during resolution. The lock records the resulting separate environment.

Installation downloads packages and the hash-pinned model wheel. Runtime uses the installed model and the imported analyzer's offline email-validator handling. A missing model or mismatched recognizer freeze prevents startup. No benchmark runner entry point or environment/results writer is called.

The original model download succeeded, but a subsequent resolver download timed out. Installation used the cached wheel after verifying its SHA-256 against the existing model requirement; the lock retains the portable upstream URL, not a local cache path.

## Tests

```powershell
.\demo\.venv\Scripts\python.exe -m unittest discover -s demo/tests -v
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The first command uses injected analyzers and tiny synthetic fixtures. It checks unions, partial and unnecessary masking, unmapped labels, Unicode/newlines, limits, errors, freeze/startup refusal, analyzer reuse, and stateless proposal behavior. The second command uses the existing benchmark environment. It does not run benchmark inference.

All 41 demo tests and 45 benchmark tests passed in the connection increment. Starlette emits a deprecation warning for the installed HTTPX TestClient integration; it still passed. Tests cover revision collisions, correction validation, approval/rejection, stale/replayed and competing updates, atomic output, expiry/capacity, safe text rendering, validated review links, and the Activepieces Code-step contracts with no action retries. Actual JavaScript helpers run with installed Node v22.23.1; no npm packages or frontend build are needed. The running FastAPI service itself does not require Node. [connection_verification.json](connection_verification.json) records current checks. Earlier [review_verification.json](review_verification.json), [verification.json](verification.json), and [environment.json](environment.json) remain historical records and were not rewritten.

## Launch and request

Run one worker, without reload, on loopback only:

```powershell
.\demo\.venv\Scripts\python.exe -m demo
```

From another PowerShell terminal at the repository root:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
$demoBody = @{
    text = "Name: Ada Example`r`nBVN: 12345678901"
    synthetic_input = $true
} | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/mask -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($demoBody))
```

Stop the foreground service with Ctrl+C. Do not change the binding to a public interface or add workers for this increment. The smoke-test server used during implementation was stopped after verification.

Open **http://127.0.0.1:8000/** for local review:

1. Paste synthetic English text, check the synthetic acknowledgement, and create a review.
2. Compare the canonical original and current proposed mask. Expand the coverage details to inspect detected marks, the initial automatic proposal, canonical intervals, and counts.
3. Select text in the read-only canonical original. Use **Add masking** or **Remove masking**; the source is never rewritten. Covered LF and original `#` positions remain explicit in the intervals even when their displayed text is unchanged.
4. Inspect the current revision, check the explicit approval acknowledgement, and approve; alternatively reject the review. Rejection is terminal for that review.
5. Retrieve/download the approved output. Each click fetches the expected current revision from the server; it does not download a cached proposal. Any later correction requires fresh approval. Changing input clears the page's current review/output and requires a new review.

The page uses text nodes, textarea values, and `textContent`, never submitted HTML. Its UTF-16 selection indices are converted to Python Unicode code-point offsets; selections splitting a surrogate pair are rejected. Combining code points remain separate. Input changes invalidate in-flight page responses; a stale-state error hides approval/output controls until refresh. No login or user authorization is implemented. Review IDs and revision digests do not establish identity or authority.

An externally created review opens at `http://127.0.0.1:8000/?review_id=<id>`. The server and page validate a lowercase 32-character hexadecimal ID; the page accepts only that one query parameter, fetches the current snapshot, and leaves approval unchecked. It does not resubmit input or infer approval from the link. A missing/expired review shows the existing error. Input changes remove the old review URL; successful snapshots update it to the current review. Live page HTTP and helper/API validation checks passed; interactive browser navigation remains unverified.

For the manual check, use the first development fixture (not test data):

```powershell
Get-Content data/raw/health_report_007.txt -Raw | Set-Clipboard
```

Paste it at the root page, create a review, select a range in **Canonical original**, add/remove masking, correct and approve, then download. Compare the UTF-8 file with that review's current `masked_text`. Make another correction and confirm retrieval requires reapproval; reject and confirm output is unavailable. The agent's Browser connection returned **“No browser is available”** with discovery `[]`, so these interactive checks are not claimed complete. A supplied review link may expire; create a fresh review rather than reusing an expired ID.

`GET /health` returns `ready` and the fixed configuration, with 200 when initialized and 503 when unavailable. Startup failure aborts application startup, so a failed startup may have no listening HTTP endpoint. Readiness is not a statement about detection quality.

`POST /mask` accepts only `text` and the Boolean `synthetic_input: true`. Empty or whitespace-only input, a missing/false acknowledgement, extra fields (including configuration), malformed JSON, and invalid Unicode return 422 without echoing the input. The acknowledgement does not verify the origin or language of the text.

The demo design limit is **20,000 Python Unicode code points in the submitted text, before newline normalization**. This is a text-field limit, not a transport-level request-body cap. CRLF and CR become LF before analysis. Offsets and length refer to that canonical original. Non-BMP characters occupy one code point; combining characters occupy separate code points. Other clients using UTF-16 indices must convert them as the supplied page does.

## Proposal semantics

The service verifies `custom_generic` against [freeze.json](../results/freeze.json) before constructing the analyzer once at application startup. It imports analyzer construction and the scorer's label map. `custom_generic` avoids the generator-dependent leading-zero exclusion; choosing it is a design decision, not a newly measured performance advantage.

Every raw span must have a string label and integer boundaries satisfying `0 <= start < end <= len(canonical_original)`, including spans with ignored labels. The mask is the union of all mapped span positions, independently of greedy entity assignment and label correctness. Each covered non-LF code point becomes `#`; LF positions and total canonical string length remain unchanged. Unmapped labels contribute no masking. Partial detection can leave PII visible and predictions can cover non-PII characters.

The response contains:

| Field | Meaning |
| --- | --- |
| `canonical_original`, `masked_proposal` | Aligned text for later human review. |
| `configuration`, `frozen_source_sha256` | Fixed `custom_generic` and its verified source digest. |
| `document_id` | SHA-256 of the canonical UTF-8 input, not a benchmark document ID. |
| `mask_intervals` | Sorted, merged half-open code-point intervals for all mapped coverage, including covered LF/original `#`. |
| `revision_id` | Version-2 SHA-256 binding configuration, source digest, canonical input, and explicit canonical coverage. |
| `review_required` | Always `true`, including zero detections. |
| `detection_counts.raw_span_count` | All analyzer results, before label mapping. |
| `detection_counts.mapped_span_count`, `ignored_span_count` | Raw spans retained or ignored by the existing label map. |
| `detection_counts.spans_by_mapped_label` | Span counts by mapped label; overlaps are still separate spans. |
| `detection_counts.covered_code_point_count` | Size of the mapped character-position union, including LF. |
| `detection_counts.masked_code_point_count`, `covered_lf_count` | Non-LF union positions masked and covered LF positions preserved. Their sum equals the union size. |

These counts are neither unique entities nor an estimate of all PII present. An unchanged proposal with no detections is still awaiting review. `POST /mask` remains stateless and usable without creating a review. Its revision identity now distinguishes different coverage that displays identically, such as an original `#` or a preserved covered LF. Equivalent reordered/overlapping/adjacent coverage yields the same intervals and proposal digest. Prior proposal digests change under this version; historical smoke records remain untouched. Identifiers are not user identity or authorization tokens.

Unavailable analyzer state returns 503. Analysis failures or invalid span data return 500 with a generic error code and message, without a proposal or submitted text. A processing failure never falls back to an unmasked success response.

## Review API and state

| Method and path | Contract |
| --- | --- |
| `POST /reviews` | Same body as `/mask`; analyze successfully, then create a pending review (201). No review is created on analysis failure. |
| `GET /reviews/{review_id}` | Return a current review snapshot. |
| `PATCH /reviews/{review_id}/mask` | Body: `expected_revision`, `operation` (`add` or `remove`), `intervals` (nonempty list of `[start,end]` code-point pairs). Union/subtract selected positions. Overlapping, adjacent, and reordered ranges are canonicalized. |
| `POST /reviews/{review_id}/approve` | Body: `expected_revision`. Explicitly approve only the current pending revision; return its new approved revision. |
| `POST /reviews/{review_id}/reject` | Body: `expected_revision`. Reject the review and deny further edits, approval, and output. |
| `GET /reviews/{review_id}/output?expected_revision=...` | Require the current approved revision. Return aligned UTF-8 plain text with attachment filename and `X-Review-Revision`. |

Every review response includes the proposal fields plus `review_id`, `revision_number`, `status`, `proposal_revision_id`, `detected_mask_intervals`, current `mask_intervals`, current `masked_text`, `coverage_counts`, and `expires_in_seconds`. `masked_proposal`, detected intervals, and `detection_counts` retain the automatic detections; corrections change only current coverage/counts. `review_required` is false only for approved state; it does not certify detection completeness.

Review identity additionally binds its random review ID and increasing revision number. Every edit, including a no-op, invalidates approval and advances the revision. Approval and rejection also consume the old revision. Editing back to earlier coverage cannot revive an earlier token. Competing actions use one state lock: one consumes a revision and later actions with it return 409. Repeated output retrieval is allowed only while that exact revision remains approved. Repeated approval is rejected. All review mutations require the expected revision; the page uses the latest response.

Output status/revision checks and copying the entire output occur under the same lock. A download is a snapshot valid at that check. A subsequent edit/rejection cannot recall bytes already delivered to a client. Stale tokens return 409 rather than fetching a different newly approved revision. Current unapproved/rejected state also returns 409. Missing or expired IDs both return 404 `review_missing_or_expired`; malformed contracts return sanitized 422. Errors contain no submitted text.

Capacity is **32 reviews**, including approved and rejected ones. Each expires **1,800 seconds after creation**, without renewal on reads, edits, or approval. Full capacity returns 503 without evicting live reviews; the check occurs after successful analysis. Expired entries are purged on the next review operation; idle expired content may therefore remain in process memory until that operation or shutdown, although expired reviews cannot be retrieved. No intermediate revision history or database is retained. Shutdown/restart loses all reviews and approvals, including the IDs recorded in walkthrough evidence. There is no delete endpoint yet; wait for expiry or stop the process to clear state. Keep one worker.

Example PowerShell contract (inspect the current source/mask before the approval command):

```powershell
$review = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/reviews -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($demoBody))
$review | Select-Object canonical_original, masked_text, mask_intervals, revision_id, status
# For the tiny Name: Ada Example fixture above, [6,17) selects Ada Example.
$edit = @{ expected_revision = $review.revision_id; operation = 'add'; intervals = @(, @(6,17)) } | ConvertTo-Json -Depth 4
$review = Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/reviews/$($review.review_id)/mask" -ContentType 'application/json' -Body $edit
$approval = @{ expected_revision = $review.revision_id } | ConvertTo-Json
$review = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/reviews/$($review.review_id)/approve" -ContentType 'application/json' -Body $approval
New-Item -ItemType Directory -Force -Path demo/output | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/reviews/$($review.review_id)/output?expected_revision=$($review.revision_id)" -OutFile demo/output/reviewed.txt
```

## Concurrency, timeouts, and logging

One analyzer is reused, with calls serialized by an application lock. Inference runs in a thread so health checks remain responsive. There is **no application processing deadline, inference cancellation, or bounded request queue** in this increment. The smoke client's 120-second HTTP timeout limits its wait; it does not cancel underlying inference. Uvicorn's connection keep-alive timeout is not an inference deadline. Do not infer successful processing or cancellation from a client disconnect or timeout.

The page's fetch calls have no explicit processing timeout. A stalled request can leave controls busy until it fails or completes. Changing input clears the local review view and ignores an older response; it does not cancel inference. The review-store capacity bounds retained records, not requests waiting for analysis.

The supplied launcher disables access logging and uses warning-level server logs. Application validation/analysis errors are sanitized without logging request bodies, analyzer exceptions, or their arguments. Responses carry `Cache-Control: no-store`; the page restricts scripts/styles to local files. `/mask` has no request persistence; `/reviews` retains canonical originals, the initial proposal, current mask, and state only in the bounded process-local store described below. Clients can retain displayed or downloaded text beyond server expiry; the page does not write local/session storage. Do not enable request-body debugging or assume the caller retains nothing. Both redirected server logs were empty during the recorded live walkthrough; fake error tests also check text-free responses and absence of error logs. This is bounded verification, not a retention guarantee for future integrations.

## Reproduce the real-analyzer smoke test

With the service running:

```powershell
.\demo\.venv\Scripts\python.exe -m demo.smoke_test
```

This selects the first development document in lexicographic document-ID order: `data/raw/health_report_007.txt`, configuration `custom_generic`. Selection is by ID, not performance. It checks HTTP readiness, a proposal's source hash, canonical text, length, LF positions and counts, plus a text-free acknowledgement error. It does not evaluate accuracy or workflow completion time.

The default output, `demo/output/smoke.json`, is ignored by Git and contains metadata, counts, and digests rather than request/response text. The implementation run was saved with `--output demo/smoke_evidence.json`; [that record](smoke_evidence.json) reports health/masking 200 and invalid acknowledgement 422. Demo JSON uses LF Git attributes to preserve its recorded file digest across checkout. It is separate from benchmark predictions and results. Do not overwrite the recorded evidence when rerunning casually.

## Reproduce the review walkthrough

With the service running:

```powershell
.\demo\.venv\Scripts\python.exe -m demo.review_walkthrough
```

This live API verification selects the same first development ID and uses its existing annotation key to choose corrections: add the incomplete ADDRESS range and remove the ORDER_ID decoy range. It verifies denied pre-approval output, rejects stale approval, approves/retrieves the exact mask, and then removes a covered LF to verify invisible-change invalidation before reapproval/retrieval. Selection is by ID, not performance. It is annotation-assisted functional verification, **not a blind human trial, accuracy evaluation, or productivity measurement**. Other PII may still be visible after these limited corrections.

The recorded run used `--output demo/review_walkthrough_evidence.json`; [the record](review_walkthrough_evidence.json) contains intervals, counts, status codes, source/output hashes, and revisions without original/output text. Default reruns write ignored `demo/output/review_walkthrough.json`. The output matched the approved mask exactly; stale and pending output returned 409. The service was verified on loopback and stopped after testing, clearing its temporary reviews. Temporary input/key/proposal inspection copies were removed; server logs were empty.

The Browser connection was unavailable. No interactive page walkthrough, visual inspection, or browser download verification is claimed. Tests execute the actual browser offset and text-node helpers with Node and verify the HTML/API contract; the live walkthrough verifies server processing, review, and output over HTTP. Interactive browser verification remains a limitation to address before presenting the demo.

## Environment findings and remaining work

Ports 8000, 8001, 8080, and 3000 could be bound on loopback during inspection; availability can change. The actual smoke listener was verified at `127.0.0.1:8000`, with one serving process.

The increment-1 inspection found Docker client 28.0.4 with an unavailable engine and no identified Activepieces instance. The connection increment subsequently started Docker Desktop 4.40.0, verified Engine 28.0.4, and installed pinned Activepieces 0.93.0 locally. Both actual listeners remain on loopback. The Activepieces runtime reached FastAPI `/health` after adding Docker's explicit host-gateway alias; no broader FastAPI binding was used.

Two manual Activepieces Code operations are configured and exported: Create review succeeded; pending/stale/rejected output was denied; a separate API-approved fixture verified positive output equality. Observed runs used its native step-test endpoint in unpublished flows, not a completed browser/human workflow. Full setup, exact configuration, failures/recovery, retained content, and reset commands are in [activepieces/README.md](activepieces/README.md). Actual browser and workflow records are separate there. Services were left running locally for manual verification; previous smoke-test shutdown notes refer to the earlier increments.

Interactive browser selection/correction/approval/download, the complete human-to-Activepieces loop, counterbalanced manual/assisted trials, and video remain pending. No workflow improvement is measured. The published benchmark still shows missed PII; an API response cannot establish suitability for unrestricted further use. Cloud models, OCR, production deployment, and expanded governance work remain separate.
