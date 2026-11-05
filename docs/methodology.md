# Evaluation Methodology

This document details the scoring protocol, matching algorithms, and formal metric definitions used in the Nigerian business document PII redaction benchmark.

---

## 1. Tuning and Split Protocol

To prevent overfitting and maintain verifiable evaluation integrity:
- **Dev Split (100 documents)**: Used strictly for development, regex pattern refinement, recognizer tuning, and threshold selection.
- **Test Split (200 documents)**: Held out and frozen. Evaluated only once per configuration to produce publishable benchmark results.
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

---

## 4. Match Categories and Confusion Matrix

Matched pairs are categorized as follows:
- **Strict Match**: The mapped predicted type matches the ground truth type, and the start and end offsets are identical ($p.\text{start} = g.\text{start}$ and $p.\text{end} = g.\text{end}$).
- **Partial Match**: The mapped predicted type matches the ground truth type, with $\text{overlap} > 0$, but offsets do not exactly match.
- **Type Confusion**: A prediction overlaps a ground truth entity, but the mapped labels differ (e.g., predicting `ADDRESS` over a `PERSON` span).
- **Miss (False Negative)**: A ground truth entity with no overlapping prediction.
- **False Positive**: A prediction that does not overlap any ground truth entity.

### Confusion Matrix Structure
The confusion matrix includes rows for each canonical ground-truth type plus `NONE` (false positives), and columns for each canonical predicted type plus `NONE` (misses):

| Ground Truth \ Predicted | `ADDRESS` | `EMAIL` | `ID` | `PERSON` | `PHONE` | `NONE` (Miss) |
|---|---|---|---|---|---|---|
| `ADDRESS` | Strict + Partial | Type Confusion | Type Confusion | Type Confusion | Type Confusion | Misses |
| `EMAIL` | Type Confusion | Strict + Partial | Type Confusion | Type Confusion | Type Confusion | Misses |
| `ID` | Type Confusion | Type Confusion | Strict + Partial | Type Confusion | Type Confusion | Misses |
| `PERSON` | Type Confusion | Type Confusion | Type Confusion | Strict + Partial | Type Confusion | Misses |
| `PHONE` | Type Confusion | Type Confusion | Type Confusion | Type Confusion | Strict + Partial | Misses |
| `NONE` (False Positives) | Extra Preds | Extra Preds | Extra Preds | Extra Preds | Extra Preds | 0 |

---

## 5. Leak Rate (Type-Agnostic Character Union)

Leak rate evaluates whether sensitive character positions remain exposed, regardless of whether the predicted label was correct:

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
- **Fully Leaked**: Entities where 0 characters are covered by any prediction ($|C_g \cap C_{\text{pred}}| = 0$).
- **Partially Exposed**: Entities where at least one character is covered, but at least one character remains exposed ($0 < |C_g \cap C_{\text{pred}}| < |C_g|$).
- **Total Exposed Entities**: $\text{Fully Leaked} + \text{Partially Exposed}$.
- **Exposure Rate**: Total exposed entities divided by total ground truth entities.

---

## 7. Over-Redaction

Over-redaction quantifies unnecessary masking of non-sensitive text:
$$\text{Over-Redaction Rate} = \frac{|C_{\text{pred}} \setminus C_{\text{PII}}|}{|C_{\text{doc}} \setminus C_{\text{PII}}|}$$
where $C_{\text{PII}} = \bigcup_{g} C_g$ is the set of all PII character positions and $C_{\text{doc}}$ is the set of all character positions in the document.

---

## 8. Precision, Recall, and F1

Metrics are reported per canonical type and micro-averaged overall, under two evaluation standards:

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

- Predictions that overlap no ground truth entity are classified as false positives.
- A false positive that overlaps a decoy span is recorded as a **Decoy Hit**.
- Decoy hits are tracked in total and broken down by decoy category (`ORDER_ID`, `INVOICE_NUMBER`, `PO_NUMBER`, `AMOUNT`).

---

## 10. ID Recall: Cued vs. Bare

Ground truth `ID` entities (BVN and NIN) are flagged as:
- **Cued**: Preceded immediately on the same line by a contextual cue (e.g., `BVN:`, `NIN No:`).
- **Bare**: Preceded by generic or non-cue labels (e.g., `ID:`, `Record No:`) or appearing without context words.

Strict and overlap recall are reported independently for cued and bare subsets to measure the model's reliance on context cues versus token patterns.

---

## 11. Latency Measurement

- Execution time in milliseconds (`ms`) is recorded per document by the pipeline runners.
- The first 5 documents are excluded from latency aggregation as a warm-up period.
- Latency is reported as:
  - **Median (p50)**: Middle document processing time.
  - **95th Percentile (p95)**: Tail latency excluding extreme outliers.
