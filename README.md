# pii-redaction-benchmark

Reproducible benchmark of local PII redaction (spaCy vs Microsoft Presidio) on synthetic Nigerian-format business documents.

## Status

In progress: dataset and scoring complete, results pending.

## Why this exists

Many automated privacy pipelines rely on off-the-shelf NER systems trained predominantly on Western demographic names, addresses, and administrative formats. When applied to Nigerian business documents, these pipelines frequently miss localized names, national identifiers like BVN and NIN, and regional phone conventions. This benchmark provides an empirical, verifiable comparison of local redaction approaches on Nigerian business records to quantify actual exposure and over-redaction tradeoffs.

## Dataset

The benchmark contains 300 synthetic business documents structured across 3 business domains:

- **100 Health Field Reports**: Community outreach records, clinical intake notes, immunization tracking.
- **100 HR Intake Forms**: Employee onboarding, benefit enrolment, disciplinary hearing records.
- **100 Vendor Invoices**: Local purchase orders, service contracts, goods receipt notes, proforma invoices.

Each domain is built from 5 distinct templates (15 templates total). All text is constructed with incremental span tracking (no post-hoc substring searching).

### Entities (1,840 total)
- **`PERSON`** (640): Nigerian first names and surnames (Yoruba, Igbo, Hausa, and other regional groups) formatted across multiple conventions (`Title First Last`, `LAST, First`, `First Last`, `F. Last`, `Last, First F.`).
- **`PHONE`** (320): Nigerian mobile formats (`+234 803 123 4567`, `08031234567`, `+234-803-123-4567`).
- **`EMAIL`** (200): Business and personal email addresses.
- **`ADDRESS`** (300): Street addresses and administrative areas across Abuja, Lagos, Port Harcourt, and Kano.
- **`ID`** (380): 11-digit national identity numbers representing BVN (180) and NIN (200). Approximately 60% are cued (preceded by cues such as `BVN:` or `NIN No:`) and 40% are bare.

### Decoys (550 total)
Non-PII lookalike tokens designed to test false-positive behavior:
- **`ORDER_ID`** (150 total; exactly 50 per document type): 11-digit decoys spanning mobile-like prefixes, `22`-prefixes, and random numbers; cued and bare. None collide with PII values in the same document.
- **`INVOICE_NUMBER`** (220): Alphanumeric reference codes.
- **`PO_NUMBER`** (60): Purchase order references.
- **`AMOUNT`** (120): Currency figures formatted in Nigerian Naira (`NGN`).

### Split
- **Dev Split**: 100 documents (stratified: 33 health, 33 HR, 34 vendor invoice).
- **Test Split**: 200 documents (stratified: 67 health, 67 HR, 66 vendor invoice).

## Methodology

Detailed mathematical definitions and procedures are documented in [docs/methodology.md](docs/methodology.md).

- **Strict Match**: Exact span offsets and identical mapped label.
- **Partial Match**: Overlapping span ($\text{overlap} > 0$) with identical mapped label.
- **Type Confusion**: Overlapping span with mismatched label.
- **Leak Rate (Headline)**: Type-agnostic character union. Uncovered PII characters divided by total PII characters across the split. Reported overall, per entity type, and per document domain.
- **Entity Exposure**: Share of entities with zero characters covered (fully leaked) and partial coverage (partially exposed).
- **Over-Redaction**: Proportion of non-PII characters covered by predictions.
- **Decoy Hits**: False positives that overlap non-PII decoy tokens.
- **ID Recall**: Evaluated separately for cued and bare 11-digit identifiers.
- **Latency**: Median and 95th percentile (p95) execution time in milliseconds, excluding the first 5 documents as warm-up.

### Tuning Protocol
All pattern tuning, context word configuration, and threshold adjustments are restricted exclusively to the 100-document development split. Once finalized, configurations are frozen and evaluated on the 200-document test split without modification. The scoring harness refuses to score development data unless `split="dev"` is explicitly specified.

## Reproduce

Run the following commands in PowerShell from the repository root:

```powershell
# 1. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# 3. Generate synthetic documents and ground truth
python scripts/generate_data.py

# 4. Verify ground truth gate
python scripts/verify_ground_truth.py

# 5. Run test suite
python -m unittest discover -s tests -v
```

## Results

Pending (evaluation runners will be executed in Phase 3 and Phase 4).

## Limitations

- **Synthetic Data**: Generated using structured templates rather than organic historical records.
- **Scale**: A focused benchmark of 300 business documents.
- **Model Diversity**: Baseline evaluated against `en_core_web_sm`; larger transformer-based models are not evaluated.
- **Text Only**: Clean text evaluation; scanned image noise and OCR degradation are currently out of scope.

## Data Note

All personal names, addresses, identification numbers, telephone numbers, and corporate references are entirely synthetic. Generated values are synthesized using predefined demographic name lists and pseudo-random generators. No actual personal records or real-world account data are included.
