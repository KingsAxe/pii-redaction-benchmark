# Local synthetic-text masking proposals

This first Phase 6 increment exposes the frozen `custom_generic` analyzer through FastAPI. It produces a proposal awaiting human review. It has no correction, approval, or final-output endpoint and does not establish that all PII has been found.

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

The first command uses injected analyzers and tiny synthetic fixtures. It checks unions, partial and unnecessary masking, unmapped labels, Unicode/newlines, limits, errors, freeze/startup refusal, analyzer reuse, and proposal-only semantics. The second command uses the existing benchmark environment. It does not run benchmark inference.

All 19 demo tests and 45 benchmark tests passed in this increment. Starlette emits a deprecation warning for the installed HTTPX TestClient integration; it still passed. An initial sandboxed test run could not write a temporary fixture; the run with normal temporary-directory access passed. [verification.json](verification.json) records these results and the evidence checks.

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

`GET /health` returns `ready` and the fixed configuration, with 200 when initialized and 503 when unavailable. Startup failure aborts application startup, so a failed startup may have no listening HTTP endpoint. Readiness is not a statement about detection quality.

`POST /mask` accepts only `text` and the Boolean `synthetic_input: true`. Empty or whitespace-only input, a missing/false acknowledgement, extra fields (including configuration), malformed JSON, and invalid Unicode return 422 without echoing the input. The acknowledgement does not verify the origin or language of the text.

The demo design limit is **20,000 Python Unicode code points in the submitted text, before newline normalization**. This is a text-field limit, not a transport-level request-body cap. CRLF and CR become LF before analysis. Offsets and length refer to that canonical original. Non-BMP characters occupy one code point; combining characters occupy separate code points. JavaScript clients must convert UTF-16 indices before any future offset-based editing. This increment provides no editing client.

## Proposal semantics

The service verifies `custom_generic` against [freeze.json](../results/freeze.json) before constructing the analyzer once at application startup. It imports analyzer construction and the scorer's label map. `custom_generic` avoids the generator-dependent leading-zero exclusion; choosing it is a design decision, not a newly measured performance advantage.

Every raw span must have a string label and integer boundaries satisfying `0 <= start < end <= len(canonical_original)`, including spans with ignored labels. The mask is the union of all mapped span positions, independently of greedy entity assignment and label correctness. Each covered non-LF code point becomes `#`; LF positions and total canonical string length remain unchanged. Unmapped labels contribute no masking. Partial detection can leave PII visible and predictions can cover non-PII characters.

The response contains:

| Field | Meaning |
| --- | --- |
| `canonical_original`, `masked_proposal` | Aligned text for later human review. |
| `configuration`, `frozen_source_sha256` | Fixed `custom_generic` and its verified source digest. |
| `document_id` | SHA-256 of the canonical UTF-8 input, not a benchmark document ID. |
| `revision_id` | SHA-256 binding configuration, source digest, canonical input, and proposed text. |
| `review_required` | Always `true`, including zero detections. |
| `detection_counts.raw_span_count` | All analyzer results, before label mapping. |
| `detection_counts.mapped_span_count`, `ignored_span_count` | Raw spans retained or ignored by the existing label map. |
| `detection_counts.spans_by_mapped_label` | Span counts by mapped label; overlaps are still separate spans. |
| `detection_counts.covered_code_point_count` | Size of the mapped character-position union, including LF. |
| `detection_counts.masked_code_point_count`, `covered_lf_count` | Non-LF union positions masked and covered LF positions preserved. Their sum equals the union size. |

These counts are neither unique entities nor an estimate of all PII present. An unchanged proposal with no detections is still awaiting review. The identifiers are deterministic content digests, not authorization or approval tokens. There is no revision store or approval mechanism yet.

Unavailable analyzer state returns 503. Analysis failures or invalid span data return 500 with a generic error code and message, without a proposal or submitted text. A processing failure never falls back to an unmasked success response.

## Concurrency, timeouts, and logging

One analyzer is reused, with calls serialized by an application lock. Inference runs in a thread so health checks remain responsive. There is **no application processing deadline, inference cancellation, or bounded request queue** in this increment. The smoke client's 120-second HTTP timeout limits its wait; it does not cancel underlying inference. Uvicorn's connection keep-alive timeout is not an inference deadline. Do not infer successful processing or cancellation from a client disconnect or timeout.

The supplied launcher disables access logging and uses warning-level server logs. Application validation/analysis errors are sanitized without logging request bodies, analyzer exceptions, or their arguments. Responses carry `Cache-Control: no-store`. The service has no request persistence; original/proposed text exists in memory and is returned to the caller, which may save or display it. Do not enable request-body debugging or assume the caller retains nothing. Both redirected server logs were empty during the recorded real-analyzer smoke test; fake error tests also check text-free responses and absence of error logs. This is bounded verification, not a retention guarantee for future integrations.

## Reproduce the real-analyzer smoke test

With the service running:

```powershell
.\demo\.venv\Scripts\python.exe -m demo.smoke_test
```

This selects the first development document in lexicographic document-ID order: `data/raw/health_report_007.txt`, configuration `custom_generic`. Selection is by ID, not performance. It checks HTTP readiness, a proposal's source hash, canonical text, length, LF positions and counts, plus a text-free acknowledgement error. It does not evaluate accuracy or workflow completion time.

The default output, `demo/output/smoke.json`, is ignored by Git and contains metadata, counts, and digests rather than request/response text. The implementation run was saved with `--output demo/smoke_evidence.json`; [that record](smoke_evidence.json) reports health/masking 200 and invalid acknowledgement 422. Demo JSON uses LF Git attributes to preserve its recorded file digest across checkout. It is separate from benchmark predictions and results. Do not overwrite the recorded evidence when rerunning casually.

## Environment findings and remaining work

Ports 8000, 8001, 8080, and 3000 could be bound on loopback during inspection; availability can change. The actual smoke listener was verified at `127.0.0.1:8000`, with one serving process.

Docker client 28.0.4 is installed, but its Linux-engine named pipe was unavailable. No Podman or Activepieces/`ap` executable or existing repository workflow setup was found. No Activepieces instance was identified in the inspected locations; running-container inventory could not be checked without the daemon. Activepieces was not installed, started, configured, or connected. Its networking and history/retention remain unverified.

Human correction, explicit revision-bound approval, final output, Activepieces setup/export and retention checks, counterbalanced manual/assisted trials, and a recorded demonstration remain pending. No workflow improvement is measured. The published benchmark still shows missed PII; an API response cannot establish suitability for unrestricted further use. Cloud models, OCR, production deployment, and expanded governance work remain separate.
