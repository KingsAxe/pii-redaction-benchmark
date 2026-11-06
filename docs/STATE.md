# Current phase

Phase 3, Stage A: implementation authorized; handoff documentation prepared.

## Done

- Read-only audit completed; existing scoring tests and ground-truth verification pass.
- User-supplied Phase 3 specification saved; brief points to it.
- Existing environment record retained pending regeneration by the runners.

## Next

- Implement runners, custom recognizer module, validator, and runner tests.
- Run and validate spaCy, Presidio default, and ng_phone on dev and test.
- Commit Stage A as `phase 3a: baseline runners`.
- Tune custom on dev only, log every experiment, and show the log to the user.
- Stop before freezing or running custom on test; both require further approval.

## Decisions

- Phase 1-2 files remain unchanged; no pushes.
- Default spaCy pipeline stays enabled; NG phone recognition is additive.
- Before freeze, test predictions may be structurally validated, but no test error analysis is viewed.
- This file is updated in every commit. Each entry describes its containing commit by subject; its hash is recorded in the next commit to avoid self-referential hashes.

## Commit hashes

- `7d980a1`: Phase 1 data.
- `e80c671`: Phase 2 scoring.
- `431d6b6`: Repository setup, parent of the handoff commit.
- Containing commit: `docs: agent handoff files`.

## Open questions

- Ground truth has no doc_id field. Asked whether its exact file value may serve as the legacy document ID without changing Phase 1 data; waiting for the user's answer.
