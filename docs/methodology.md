# Evaluation Methodology

This document details the scoring protocol, matching algorithms, and formal metric definitions used in the Nigerian business document PII redaction benchmark.

---

## 1. Tuning and Split Protocol

To prevent overfitting and maintain verifiable evaluation integrity:
- **Dev Split (100 documents)**: Used strictly for development, regex pattern refinement, recognizer tuning, and threshold selection.
- **Test Split (200 documents)**: Used for reporting, not tuning. The recorded sequence includes baseline dev/test prediction generation for spaCy, Presidio default, and ng_phone in `dd6b474`; dev-only custom experiments in `26ed015`; two-source freeze in `853bcbb`; then test prediction regeneration for all five configurations in `da55731`. Phase 4 (`f3ba55c`) and subsequent reporting corrections rescore those archived predictions without running models. Prediction generation and rescoring are distinct operations; test error records were first generated after freeze. This history is not a single test prediction run per configuration.
- **Split Guard**: The scoring harness defaults to `split="test"` and explicitly forbids evaluating the development split unless `split="dev"` is passed directly. All documents within the target split must have predictions or evaluation raises an error.

---

## 2. Label Mapping and Scope

Ground truth and predictor label spaces are mapped to canonical benchmark entities:

| Canonical Entity | Ground Truth Sources | spaCy Sources | Presidio Sources |
|---|---|---|---|
| `PERSON` | `PERSON` | `PERSON` | `PERSON` |
| `PHONE` | `PHONE` | — | `PHONE_NUMBER` |
| `EMAIL` | `EMAIL` | — | `EMAIL_ADDRESS` |
| `ADDRESS` | `ADDRESS` | `GPE`, `LOC`, `FAC` | `LOCATION` |
| `ID` | `BVN`, `NIN` | — | Custom `BVN`, `NIN`, `ID` |

- **ID Unification**: BVN and NIN are merged into a single canonical `ID` label because bare 11-digit numbers cannot be distinguished by format alone.
- **Unmapped Predictions**: Only mapped labels participate in redaction matching and character coverage. Unmapped labels (such as `DATE`, `ORG`, or `MONEY`) are ignored during scoring and tracked in an unmapped prediction counter.

---

## 3. One-to-One Greedy Matching

Predictions and ground truth entities are matched using deterministic one-to-one greedy assignment:

1. **Overlap Calculation**: Overlap size between ground truth entity $g$ and prediction $p$ is defined as:
   $$\text{overlap}(g, p) = \max(0, \min(g.\text{end}, p.\text{end}) - \max(g.\text{start}, p.\text{start}))$$
2. **Candidate Ranking**: All pairs with $\text{overlap} > 0$ are ranked by:
   - Overlap size descending ($-\text{overlap}$)
   - Earlier ground truth start position ($g.\text{start}$)
   - Earlier prediction start position ($p.\text{start}$)
   - Lower ground truth entity index ($g.\text{idx}$)
   - Lower prediction index ($p.\text{idx}$)
3. **Assignment**: Candidates are selected iteratively. Once an entity or prediction is assigned, it cannot be matched to any other span. No span is counted twice.

Label correctness and exact-match status are checked only after assignment. Ranking does not prioritise correct labels or exact spans. If competing labels have equal spans and other ranking fields tie, prediction order can decide which label is assigned. The runners sort stored predictions by start, end, and raw label, so that stored order can affect such ties.

---

## 4. Match Categories and Confusion Matrix

Assignment outcomes and match categories are defined as follows:
- **Strict Match**: The mapped predicted type matches the ground truth type, and the start and end offsets are identical ($p.\text{start} = g.\text{start}$ and $p.\text{end} = g.\text{end}$).
- **Partial Match**: The mapped predicted type matches the ground truth type, with $\text{overlap} > 0$, but offsets do not exactly match.
- **Type Confusion**: An assigned prediction and entity have different mapped labels (e.g., predicting `ADDRESS` over a `PERSON` span).
- **Matcher Miss**: An entity left unmatched after one-to-one assignment. It can still have predicted characters covering it, for example when a spanning prediction was assigned to another entity.
- **Unmatched Prediction**: A mapped prediction left unassigned. It may overlap PII already assigned to another prediction. This category is distinct from strict/overlap false positives, which equal prediction count minus the corresponding true positives, as defined in Section 8. Assigned wrong-type or partial-span predictions can also contribute to those false-positive totals.

### Confusion Matrix Structure
The confusion matrix includes rows for each canonical ground-truth type plus `NONE` (unmatched predictions), and columns for each canonical predicted type plus `NONE` (matcher misses):

| Ground Truth \ Predicted | `ADDRESS` | `EMAIL` | `ID` | `PERSON` | `PHONE` | `NONE` (Miss) |
|---|---|---|---|---|---|---|
| `ADDRESS` | Strict + Partial | Type Confusion | Type Confusion | Type Confusion | Type Confusion | Misses |
| `EMAIL` | Type Confusion | Strict + Partial | Type Confusion | Type Confusion | Type Confusion | Misses |
| `ID` | Type Confusion | Type Confusion | Strict + Partial | Type Confusion | Type Confusion | Misses |
| `PERSON` | Type Confusion | Type Confusion | Type Confusion | Strict + Partial | Type Confusion | Misses |
| `PHONE` | Type Confusion | Type Confusion | Type Confusion | Type Confusion | Strict + Partial | Misses |
| `NONE` (Unmatched Predictions) | Extra Preds | Extra Preds | Extra Preds | Extra Preds | Extra Preds | 0 |

---

## 5. Leak Rate (Type-Agnostic Character Union)

Leak rate evaluates whether sensitive character positions remain exposed, regardless of whether the predicted label was correct:

Coverage uses the union of **all mapped predicted spans**, independently of matching assignment and label correctness. Both matched and unmatched predictions contribute. This same union is used for entity exposure and character-level over-redaction; unmapped labels do not contribute.

1. **Prediction Union**: For each document, all valid (mapped) predicted spans are flattened into a set of character index positions:
   $$C_{\text{pred}} = \bigcup_{p \in \text{preds}} [p.\text{start}, p.\text{end})$$
2. **Entity Exposure**: For each ground truth entity $g$ with character positions $C_g = [g.\text{start}, g.\text{end})$:
   $$\text{uncovered}(g) = |C_g \setminus C_{\text{pred}}|$$
3. **Leak Rate Calculation**:
   $$\text{Leak Rate} = \frac{\sum_{g} \text{uncovered}(g)}{\sum_{g} |C_g|}$$

Leak rates are reported:
- **Overall**: Aggregate across all PII characters in the benchmark split.
- **Per-Type**: Filtered by canonical entity type.
- **Per-Doc-Type**: Filtered by document domain (`health_report`, `hr_intake`, `vendor_invoice`).

---

## 6. Entity-Level Exposure

Beyond raw character counts, entity exposure measures how many individual records are exposed:
- **Fully Uncovered** (the scorer's `fully_leaked_count`): Entities where 0 characters are covered by mapped predictions ($|C_g \cap C_{\text{pred}}| = 0$).
- **Partially Exposed**: Entities where at least one character is covered, but at least one character remains exposed ($0 < |C_g \cap C_{\text{pred}}| < |C_g|$).
- **Total Exposed Entities**: Fully uncovered count plus partially exposed count.
- **Exposure Rate**: Total exposed entities divided by total ground truth entities.

The generated reports export fully uncovered and partially exposed counts alongside the total entity denominator. Exposure is a character-coverage measure, not the count of matcher misses.

---

## 7. Over-Redaction

Over-redaction quantifies unnecessary masking of non-sensitive text:
$$\text{Over-Redaction Rate} = \frac{|C_{\text{pred}} \setminus C_{\text{PII}}|}{|C_{\text{doc}} \setminus C_{\text{PII}}|}$$
where $C_{\text{PII}} = \bigcup_{g} C_g$ is the set of all PII character positions and $C_{\text{doc}}$ is the set of all character positions in the document.

This rate counts non-PII characters covered by the mapped prediction union. Decoy-hit prediction counts and distinct ORDER_ID decoys hit by ID predictions are separate counting measures; neither substitutes for character-level over-redaction.

---

## 8. Precision, Recall, and F1

Metrics are reported per canonical type and micro-averaged overall, under two evaluation standards:

True positives below are counted among pairs already selected by the overlap-first assignment. The matcher is not rerun to favour label correctness or exactness for either standard. `N_pred` counts mapped predictions, including those assigned to PII and those left unmatched.

### Strict Evaluation
- $\text{TP}_{\text{strict}}$: Correct type, exact start and end offsets.
- $\text{FP}_{\text{strict}} = N_{\text{pred}} - \text{TP}_{\text{strict}}$
- $\text{FN}_{\text{strict}} = N_{\text{gt}} - \text{TP}_{\text{strict}}$
- $\text{Precision}_{\text{strict}} = \frac{\text{TP}_{\text{strict}}}{N_{\text{pred}}}$
- $\text{Recall}_{\text{strict}} = \frac{\text{TP}_{\text{strict}}}{N_{\text{gt}}}$
- $\text{F1}_{\text{strict}} = \frac{2 \cdot P \cdot R}{P + R}$

### Overlap Evaluation
- $\text{TP}_{\text{overlap}}$: Correct type, $\text{overlap} > 0$ under 1-to-1 greedy assignment.
- $\text{FP}_{\text{overlap}} = N_{\text{pred}} - \text{TP}_{\text{overlap}}$
- $\text{FN}_{\text{overlap}} = N_{\text{gt}} - \text{TP}_{\text{overlap}}$
- $\text{Precision}_{\text{overlap}} = \frac{\text{TP}_{\text{overlap}}}{N_{\text{pred}}}$
- $\text{Recall}_{\text{overlap}} = \frac{\text{TP}_{\text{overlap}}}{N_{\text{gt}}}$
- $\text{F1}_{\text{overlap}} = \frac{2 \cdot P \cdot R}{P + R}$

---

## 9. Decoy Hits

Decoys represent non-PII numerical tokens (11-digit `ORDER_ID` strings, invoice references, PO numbers, currency amounts) designed to test over-triggering.

- The scorer inspects only **unmatched mapped predictions**. It checks decoys in their stored order and counts the first overlapping decoy per prediction, then stops inspecting that prediction's remaining decoys.
- These decoy-hit prediction counts are tracked in total and by decoy category (`ORDER_ID`, `INVOICE_NUMBER`, `PO_NUMBER`, `AMOUNT`). Multiple unmatched predictions can each count against the same decoy.
- Predictions matched to PII can also cover decoy characters without appearing in this count. Their covered non-PII characters still contribute to over-redaction.
- The separate **distinct ORDER_ID decoys hit by ID predictions** diagnostic counts each ORDER_ID annotation once if any mapped ID prediction touches it, regardless of assignment. Its unit, prediction scope, and assignment restriction differ from the scorer's decoy-hit measure. Neither count measures the share of non-PII characters redacted.

---

## 10. ID Recall: Cued vs. Bare

Ground truth `ID` entities (BVN and NIN) are flagged as:
- **Cued**: Preceded immediately on the same line by a contextual cue (e.g., `BVN:`, `NIN No:`).
- **Bare**: Preceded by generic or non-cue labels (e.g., `ID:`, `Record No:`) or appearing without context words.

Strict and overlap recall are reported independently for cued and bare subsets to measure the model's reliance on context cues versus token patterns.

The five evaluated configurations are spaCy, Presidio default, ng_phone, custom_generic (archived experiment 01), and custom (archived experiment 02). The generator's `gen_11digit()` never emits IDs starting with 0. Excluding such candidates improved custom's ID precision on this dataset. Both custom variants have equal reported character leakage and over-redaction rates; equal aggregate rates do not imply identical covered character positions. Historical experiment records retain their original timing and decisions.

---

## 11. Latency Measurement

- The shared runner sorts documents, selects the first five **dev** documents, and makes five preliminary analysis calls before the recorded loop. These calls are unrecorded and never use test documents, including when only test was requested.
- Each stored `ms` is measured with `perf_counter` around the analysis call only. Model loading, document reads, span extraction, and JSON writing are outside that interval.
- The main generated report uses **all stored test timings** after those preliminary warm-ups. Median and p95 use the existing Phase 2 percentile helper with linear interpolation on sorted timing values.
- The unchanged Phase 2 scorer separately drops the first five stored timings when more than five exist. Its original median/p95 and exclusion count remain in `evaluation_details.json` and the explicitly named `scorer_*` CSV columns. That extra exclusion and the main calculation are both preserved.
- **Median (p50)** is the 50th percentile; **p95** is the 95th percentile. Computing p95 does not remove outliers.
- Timings come from single sequential runs on this machine; host load, caches, and run order limit claims about relative speed. Regenerating reports reads existing timings and does not run models again.
