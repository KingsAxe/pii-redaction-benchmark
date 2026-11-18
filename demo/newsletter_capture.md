# Capture the actual local review workflow

The original Browser connection returned `No browser is available` and discovery `[]`. A later standalone Playwright check captured a separate automated dev review, with inspected PNGs and a played five-second 1080p WebM; see [the current capture notes](README.md#light-colours-and-recording-check). Those trial files are not the human-session shots below. Capture the real human workflow; do not recreate states in an image editor. PNGs belong in ignored `demo/output/newsletter/`, separately from benchmark figures.

The original human review `0804860fed2e41d3af796c1beab08461` was approved and its browser download matched Activepieces output byte for byte. It then expired. That expired view must not be used to imply a current approval or a verified stale-revision result. Use the fresh review supplied with this handoff.

## Example and common framing

Use `data/raw/health_report_007.txt`, the first development document in lexicographic ID order, with frozen `custom_generic`. This is a fresh review of an existing synthetic example, selected by ID rather than performance; it is not claimed representative. No held-out test document is used.

Use a desktop viewport about 1440 pixels wide at normal zoom. The create-input panel collapses when a review loads. Keep diagnostics collapsed. Frame the review header and the two document panels; include the correction controls where useful. The status badge spells out Pending review, Approved, or Rejected, independently of colour. On narrow screens the panels stack; do not imply that a desktop capture verifies mobile layout.

Keep browser account controls, developer tools, unrelated tabs/windows, and local account/session files outside the capture. Review IDs and revision identifiers are not user authorization, but account tokens must never appear. Do not include Activepieces account settings in any shot.

## 01-automatic-proposal.png

**State:** a newly created review; Pending review; no human corrections or approval. The original and current proposal must both be visible from the patient line through Order Ref. Leave intervals/counts collapsed.

**Visible examples:** `Promise Udoh` appears unmasked in the automatic proposal (a missed PERSON), while the ORDER_ID decoy `09063713925` is masked unnecessarily. Verify those observations against the fresh proposal before capturing; do not modify predictions to manufacture them. This example has other detection gaps too.

**Frame:** crop around the sticky review header, both complete text panels, and the first correction controls. Keep both the patient and Order Ref lines legible. Save:

`C:\Users\pc\Desktop\Pro_Jets\pii-redaction-benchmark\demo\output\newsletter\01-automatic-proposal.png`

## 02-human-correction.png

**State:** still Pending review. In Canonical original, select `Promise Udoh` and choose Add masking; select the digits `09063713925` and choose Remove masking. These selections correspond to code-point intervals [107,119) and [243,254) in this fixed canonical example. Make any further corrections you intend to demonstrate, but do not approve yet.

**Frame:** use the same two-panel framing as shot 01. Show the corrected comparison, Pending review badge, and correction controls. Download must still be disabled. Describe these as selected human corrections, not proof that the whole document is free of PII. Save:

`C:\Users\pc\Desktop\Pro_Jets\pii-redaction-benchmark\demo\output\newsletter\02-human-correction.png`

## 03-approved-output.png

**State:** inspect the current proposal, check the explicit approval acknowledgement, approve, then choose Retrieve and download approved output. The badge must read Approved and the retrieved output must be present. Do not make another correction yet.

**Frame:** scroll to the approval/download cards and Retrieved approved output. Keep the sticky Approved header visible above them. Include the returned text, rather than only an enabled button. Keep diagnostics collapsed. Save:

`C:\Users\pc\Desktop\Pro_Jets\pii-redaction-benchmark\demo\output\newsletter\03-approved-output.png`

Confirm approval/download to the agent immediately, giving this fresh review's ID and the exact new download path. Browser duplicate filenames may have a numeric suffix; do not assume the previous download was replaced. The agent will capture the current approved revision, invoke Activepieces retrieval for the same ID, and compare actual bytes before the next correction. Reviews expire 30 minutes from creation, including while approved; do not wait until the expiry boundary.

## 04-activepieces-retrieval.png

**State:** after the agent reports a successful Activepieces retrieval for this same fresh review and approved revision. Open the local Activepieces run/action result at `http://127.0.0.1:8080/` using the supplied run ID. The observed operations use Code-step tests in unpublished flows (`TESTING`), not a published full-flow run.

**Frame:** capture only the successful Retrieve approved output action/result, its run ID, review ID, revision, and returned masked text. Crop out account menus, settings, authorization headers, and tokens. Native UI navigation was not inspected by the agent. If that result cannot be displayed in the browser, omit this PNG and record the blocker; an API JSON file is not a substitute screenshot. Save, if available:

`C:\Users\pc\Desktop\Pro_Jets\pii-redaction-benchmark\demo\output\newsletter\04-activepieces-retrieval.png`

## Complete the invalidation check after the captures

After the successful retrieval is recorded, select a small range in the same Canonical original and add or remove masking once more. Do not reapprove. Confirm the correction to the agent. The agent will retain the previously approved token and run Activepieces retrieval with that old token: expected result is HTTP 409 `stale_revision`, with the current review Pending. A 404 due to expiry does not verify this case. The previously downloaded file cannot be recalled by a later correction.

The agent's automated trial uses separate timestamped `colour-check-*` filenames. The four expected human-session paths above do not establish that those captures exist or passed visual inspection. Do not overwrite an unrelated existing image. Record the actual review/run IDs and capture state with the final files.
