# Local Activepieces connection

This increment connects two manual operations to the existing review API. The observed executions are **native Code-step tests in two unpublished flows**, using Activepieces' `POST /api/v1/sample-data/test-step` endpoint. They are real worker executions in the `TESTING` environment, not a published end-to-end human workflow. Automatic action retries and continue-on-failure are disabled. Requests were invoked sequentially; status reads did not retrigger execution.

## Version and local setup

Tested: Docker Desktop 4.40.0, Engine 28.0.4, WSL 2.3.26.0, and **Activepieces 0.93.0**, image digest `sha256:151c2a4326c30a6a8086297136644da9b58072212c35bca7c87dcb5724e7d687`.

The setup follows the official [0.93.0 Docker instructions](https://github.com/activepieces/activepieces/blob/0.93.0/docs/install/options/docker.mdx) and [0.93.0 environment reference](https://github.com/activepieces/activepieces/blob/0.93.0/docs/install/reference/environment-variables.mdx). API configuration/execution/export were checked against that version's [flow controller](https://github.com/activepieces/activepieces/blob/0.93.0/packages/server/api/src/app/flows/flow/flow.controller.ts), [sample-data controller](https://github.com/activepieces/activepieces/blob/0.93.0/packages/server/api/src/app/flows/step-run/sample-data.controller.ts), and [Code-action schema](https://github.com/activepieces/activepieces/blob/0.93.0/packages/core/execution/src/lib/flows/actions/action.ts).

PowerShell, repository root:

```powershell
Start-Process -FilePath 'C:/Program Files/Docker/Docker/Docker Desktop.exe' -WindowStyle Hidden
docker version
.\demo\.venv\Scripts\python.exe -m demo
# A separate terminal, after Docker is ready (existing task container):
docker start pii-demo-activepieces
Invoke-RestMethod http://127.0.0.1:8080/api/v1/health
docker exec pii-demo-activepieces node -e "fetch('http://host.docker.internal:8000/health').then(async r=>console.log(r.status,await r.json()))"
```

Both services were left running for the outstanding manual browser check. Do not launch a second demo process on an occupied port. The supplied Python launcher binds `127.0.0.1:8000`; Activepieces publishes only `127.0.0.1:8080`. Actual host listeners and container port bindings were checked. Other existing containers were left unchanged.

The task container was created with:

```powershell
docker run -d --name pii-demo-activepieces `
  --publish 127.0.0.1:8080:80 `
  --add-host=host.docker.internal:host-gateway `
  --mount type=volume,source=pii-demo-activepieces-data,target=/root/.activepieces `
  --env-file demo/.cache/activepieces/runtime.env `
  activepieces/activepieces@sha256:151c2a4326c30a6a8086297136644da9b58072212c35bca7c87dcb5724e7d687
```

For a fresh container, create the ignored `runtime.env` using these nonsecret settings plus locally generated `AP_ENCRYPTION_KEY` (16 random bytes, hex) and `AP_JWT_SECRET` (32 random bytes, hex). Preserve the existing keys when reusing its data volume. The existing file and generated local account/session are under ignored `demo/.cache/activepieces/`; they must stay out of Git. There is no default admin password. The first local account becomes administrator; this task used `local-demo@example.invalid` with a generated password, newsletter disabled, and tracking opted out.

| Setting | Tested value |
| --- | --- |
| `AP_DB_TYPE`, `AP_REDIS_TYPE` | `PGLITE`, `MEMORY` |
| `AP_FRONTEND_URL` | `http://127.0.0.1:8080` |
| `AP_CONFIG_PATH` | `/root/.activepieces` |
| `AP_TELEMETRY_ENABLED` | `false` |
| `AP_WORKER_CONCURRENCY`, `AP_DEFAULT_CONCURRENT_JOBS_LIMIT` | `1`, `1` |
| `AP_EXECUTION_DATA_RETENTION_DAYS`, `AP_PAUSED_FLOW_TIMEOUT_DAYS` | `2`, `1` |
| `AP_FLOW_TIMEOUT_SECONDS` | `120` |
| `AP_EXECUTION_MODE`, `AP_NETWORK_MODE` | `UNSANDBOXED`, `UNRESTRICTED` |

This is a local synthetic demonstration, not a production setup. Activepieces' flow timeout does not implement cancellation of FastAPI inference. FastAPI still has no processing deadline or bounded request queue. No public tunnel, LAN binding, OCR, cloud-model call, timing trial, or video was added.

## Failed checks and their resolution

- Initially Docker returned a missing `dockerDesktopLinuxEngine` pipe. Starting the installed Docker Desktop made the engine available; no WSL install or machine restart was needed.
- The first container could not resolve `host.docker.internal` (`ENOTFOUND`); its resolver used `8.8.8.8`/`8.8.4.4`. Recreating only this task's container with `--add-host=host.docker.internal:host-gateway` resolved the alias to Docker's internal gateway and produced HTTP 200 from the actual Activepieces runtime to FastAPI. No global DNS/firewall changes or broader FastAPI binding were used. See Docker's [host-gateway option](https://docs.docker.com/reference/cli/docker/container/run/#add-entries-to-container-hosts-file---add-host).
- Later the worker logged “Poll loop stalled” and the container exited with code 1 (`OOMKilled=false`). A subsequent API configuration request was refused. `docker start pii-demo-activepieces`, followed by a successful health check, restored it. This was a manual service recovery, not a retried flow. If it recurs, inspect `docker inspect pii-demo-activepieces` and its local logs, then start that container and verify health before triggering a step.

## Reproduce the two manual operations

Open Activepieces at **http://127.0.0.1:8080/** and the reviewer at **http://127.0.0.1:8000/**. The agent's Browser connector had no available browser; UI navigation/import/download was not inspected. Native exports were obtained through the version-pinned API and are provided as [Create review](create_review.flow.json) and [Retrieve approved output](retrieve_output.flow.json). Their template-wrapper `status: PUBLISHED` is the export format; the actual local flows remain `DISABLED`/unpublished. Nothing was uploaded to an Activepieces cloud service.

The exports include the intentional synthetic fixture and recorded, expiring test IDs. Replace retrieval inputs for a fresh review. They contain no account credentials, bearer tokens, or connection secrets.

| Operation | Exact Code-step configuration |
| --- | --- |
| Create review | Source [create_review.ts](create_review.ts); package JSON `{}`; input `text` is `data/raw/health_report_007.txt` (first lexicographic dev ID). It posts `synthetic_input: true` and returns the review ID, revision, configuration, and `http://127.0.0.1:8000/?review_id=...` link. |
| Retrieve approved output | Source [retrieve_output.ts](retrieve_output.ts); package JSON `{}`; inputs `review_id` and `expected_revision` are the exact current approved values. It never substitutes a newer revision for a stale one. Success returns `masked_text`; denial fails the step with a static HTTP/code message. |
| Both | Manual Trigger piece `@activepieces/piece-manual-trigger` version `0.0.8`; one native `CODE` action named `step_1`; `retryOnFailure.value=false`, `continueOnFailure.value=false`. Flow schema version `28`. |

The observed API sequence was:

1. Sign in to the local instance (`POST /api/v1/authentication/sign-in`) and keep its token private. Create each flow with `POST /api/v1/flows` (`displayName`, `projectId`).
2. Apply `IMPORT_FLOW` using `POST /api/v1/flows/{id}` with the exported `flows[0]` fields `displayName`, `trigger`, `schemaVersion`, and `notes`.
3. Invoke one Code step once with `POST /api/v1/sample-data/test-step`, body `{"projectId":"...","flowVersionId":"...","stepName":"step_1"}`. Read that returned run via `GET /api/v1/flow-runs/{id}` until `finishTime` is set. Polling reads are not execution retries. Run output is under `steps.step_1.output`.
4. Open Create review's returned link. Correct and explicitly approve in the browser. Read the approved revision with `GET http://127.0.0.1:8000/reviews/{review_id}`; confirm `status=approved` before copying `revision_id` into retrieval inputs.
5. Update retrieval inputs through its Code-step settings, or apply `UPDATE_ACTION` to `POST /api/v1/flows/{id}` (the native action schema omits `lastUpdatedDate` and `sampleData` for updates). Manually invoke that step once. Compare its output with the approved mask.

UI actions in steps 4–5 remain to be verified interactively. In observed runs, Create review succeeded; pending, stale, and rejected retrieval probes each failed with HTTP 409 and their expected reason. A separate **API-approved** dev-copy fixture verified positive retrieval and exact output equality. Its approval/corrections were made through the API, not by a person in the browser. It does not complete the outstanding human-review demonstration. The original human-review link was not modified by these probes.

On this configured machine, the following invokes Create review **once** using the private local session and recorded flow IDs. If the session expired, sign in again first; after a fresh import, replace the IDs. Do not print or commit the session token.

```powershell
$apLocal = Get-Content demo/.cache/activepieces/account.json -Raw | ConvertFrom-Json
$apFlows = Get-Content demo/.cache/activepieces/flows.json -Raw | ConvertFrom-Json
$apHeaders = @{ Authorization = "Bearer $($apLocal.session.token)" }
$apRequest = @{
    projectId = $apLocal.session.projectId
    flowVersionId = $apFlows.'create_review.ts'.version_id
    stepName = 'step_1'
} | ConvertTo-Json
$apRun = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8080/api/v1/sample-data/test-step -Headers $apHeaders -ContentType 'application/json' -Body $apRequest
$apResult = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v1/flow-runs/$($apRun.id)" -Headers $apHeaders
$apResult | Select-Object id, status, finishTime
# If still running, repeat only the GET read until finishTime is set:
$apResult.steps.step_1.output.review_url
```

For the manual download comparison, before making another correction, fetch the approved review snapshot and compare the downloaded file's SHA-256 with the SHA-256 of UTF-8 `masked_text`. A visual match alone can miss newline differences. This file check was not performed by the agent because no browser download was available.

## Retained content and clearing it

Observed through the run API:

- Create review retains the complete synthetic `text` input, plus returned IDs, revision, configuration, and review URL. Its flow settings/export also contain the fixture.
- Successful retrieval retains the complete masked text and revision. Denied runs retain their IDs/revisions and static error/stack data. The Code steps do not print request text.
- `GET /sample-data` returned `{}` in the creation check, while `GET /flow-runs/{id}` still returned complete step input/output. An empty sample response is not evidence of empty history.
- An archive request for the `TESTING` Create run returned HTTP 200 but left `archivedAt=null` and its full input retrievable. In [0.93.0 source](https://github.com/activepieces/activepieces/blob/0.93.0/packages/server/api/src/app/flows/flow-run/flow-run-service.ts), archive targeting filters to `PRODUCTION`; archiving is not deletion of logs. Do not use it to claim this test history was cleared.

Execution retention is configured to two days, with PGLite/files on the named Docker volume. Expiry/purging was not observed during this task and requires the service's cleanup jobs to run. This does not remove input copied into flow settings, exports, or local client/cache files. FastAPI's 30-minute review expiry does not clear Activepieces history.

To fully reset **this task's local instance**, export anything needed, then run:

```powershell
docker stop pii-demo-activepieces
docker rm pii-demo-activepieces
docker volume rm pii-demo-activepieces-data
```

These commands remove this demo's account, flows, and persisted history together; they were not executed, so the configured instance remains available. They do not delete unrelated Docker volumes, exported synthetic fixtures, or ignored local cache copies. Remove ignored `*-run.json`, `account.json`, and any downloaded outputs separately if those copies are no longer wanted. The benchmark and its historical evidence must remain untouched.

Actual browser and workflow results are separate in [browser_check.json](browser_check.json) and [workflow_evidence.json](workflow_evidence.json). No browser pass, human approval, accuracy improvement, or productivity finding is inferred from backend tests.
