# Custom dev experiment log

Seed 42; full en_core_web_sm; dev only. At the time of these experiments no freeze had been approved or written; see the accepted review addendum below.

ID recall and overall micro precision use the unchanged Phase 2 scorer. Strict means exact span and mapped type; overlap also accepts partial spans. Raw unmapped labels are retained in predictions and ignored by that scorer.

Each experiment archives source, SHA-256, predictions, label counts, and dev metrics under results/tuning/<experiment>/. Only custom_recognizers.py is tuned.

## 01-initial

Change: Initial 11-digit pattern, base score 0.05 and original BVN/NIN contexts; no tuning yet.

Source SHA-256: `1cc272db3674b3e3d59cc8a8ed791419a3f45457fdfdfde69389f965b79b06f1`

Dev documents: 100

- id_recall_strict: 0.959350
- precision_strict: 0.336709
- id_recall_overlap: 0.959350
- precision_overlap: 0.543038

Artifacts: `results/tuning/01-initial/`

## 02-nonzero

Change: Exclude zero-leading 11-digit candidates to avoid local phone formats; dev ID values all start nonzero. Keep base score, context words, and boost unchanged.

Source SHA-256: `a10d7fa8e88be4633c998c294a540ee00ce90dc6a1f7f9eb2edfc4a36f6fde18`

Dev documents: 100

- id_recall_strict: 0.959350
- precision_strict: 0.420408
- id_recall_overlap: 0.959350
- precision_overlap: 0.642177

Artifacts: `results/tuning/02-nonzero/`

## 03-cued-only

Change: Require a same-line explicit BVN/NIN cue seen in dev; variable-length lookbehind preserves digit-only spans. Retain nonzero-leading rule, base score, contexts, and boost. Measure recall loss versus precision.

Source SHA-256: `b860551bd5b06ef58e47f7a91314a4933ab291d797d5d32b0bd5498a5980937e`

Dev documents: 100

- id_recall_strict: 0.593496
- precision_strict: 0.401826
- id_recall_overlap: 0.593496
- precision_overlap: 0.649924

Artifacts: `results/tuning/03-cued-only/`

## Review recommendation (not a freeze)

Selected for review: `02-nonzero` using highest observed strict dev ID recall, then overall strict micro precision. This comparison rule was applied after the three experiments.

| Experiment | Strict ID recall | Strict precision | Overlap ID recall | Overlap precision |
|---|---:|---:|---:|---:|
| 01-initial | 0.959350 | 0.336709 | 0.959350 | 0.543038 |
| 02-nonzero | 0.959350 | 0.420408 | 0.959350 | 0.642177 |
| 03-cued-only | 0.593496 | 0.401826 | 0.593496 | 0.649924 |

Restored the selected archived source and its predictions without another evaluation. The standard dev prediction file now matches the selected experiment.

The nonzero-leading rule is supported by this synthetic dev set; it is not a claim about every real BVN/NIN. Bare random order IDs remain ambiguous. No test errors were inspected, no custom test predictions were generated, and no freeze was created. User approval is required before freezing and custom test execution.

## Accepted review: ID-only archived dev diagnostics

Computed from archived predictions only; no new inference or tuning runs.

ID precision is the Phase 2 per-ID precision using its full, type-aware greedy assignment. PHONE means an ID entity assigned to a PHONE prediction by that matcher. Coverage is the union of every mapped prediction, regardless of its type. Uncovered means at least one ID character exposed; fully uncovered means no character covered. ORDER_ID counts distinct decoy annotations touched by an ID prediction, once per decoy.

| Experiment | ID precision strict | ID precision overlap | ORDER_ID decoys hit by ID | IDs assigned PHONE | Fully uncovered IDs | Partly uncovered IDs | Any uncovered IDs | PHONE or any uncovered IDs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 01-initial | 0.559242 | 0.559242 | 45 | 0 | 0 | 0 | 0 | 0 |
| 02-nonzero | 0.756410 | 0.756410 | 33 | 0 | 0 | 0 | 0 | 0 |
| 03-cued-only | 0.935897 | 0.935897 | 0 | 7 | 38 | 0 | 38 | 45 |

Experiment 02's rule works because gen_11digit() in scripts/generate_data.py draws from 10_000_000_000 through 99_999_999_999: the generator never emits BVN/NIN IDs starting with 0. This assumption excludes phone-shaped numbers without excluding generated IDs; it is not evidence that real identifiers obey that restriction. The user accepted review and authorized freezing both 01 (custom_generic) and 02 (custom), without any new tuning experiments.
