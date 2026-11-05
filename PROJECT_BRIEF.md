# PROJECT_BRIEF: pii-redaction-benchmark

## Purpose
A public, reproducible benchmark of local PII redaction on synthetic Nigerian-format business documents. Three configurations are compared: (A) spaCy en_core_web_sm NER only, (B) Presidio out-of-the-box, (C) Presidio plus custom BVN/NIN recognizers. The results will be published on LinkedIn, so every number must be honest and verifiable.

## Rules (always apply)
1. Never fabricate or hardcode results. Every number in any file must be produced by a script.
2. Never tune on the test split. Dev (100 docs) is for tuning; test (200 docs) is for reporting.
3. All data is synthetic. No real personal data anywhere.
4. Seed everything with 42. Runs must be deterministic.
5. Windows and PowerShell only. The venv already exists. No network except pip and the spaCy model download.
6. Do not use the words "compliant", "secure", "air-gapped", or "zero-leak" in any file.
7. Fix root causes. Never change scoring or data to improve a score.
8. Write requirements.txt with: pip freeze | Out-File requirements.txt -Encoding ascii
9. One small git commit per phase ("phase N: ..."). Do not push.
10. Be brief. After each phase report: what you built, the command to run, what to check, and any assumption in one line. Ask at most one question, and only if truly blocked. Stop at each gate.

## Phase 1: Data (gate: verify script passes)
Create scripts/nigerian_data.py, scripts/generate_data.py and scripts/verify_ground_truth.py.
- Use my own lists, not Faker locales: ~60 first names and ~60 surnames (Yoruba, Igbo, Hausa, others), ~25 street names, and areas in Abuja, Lagos, Port Harcourt and Kano. Faker is only for dates, companies and amounts.
- 300 documents: 100 health field reports, 100 HR intake forms, 100 vendor invoices, with at least 4 templates per type.
- Entities: PERSON (varied formats such as "Dr. Ngozi Okafor" and "OKAFOR, Ngozi"), PHONE (+234 803 123 4567, 08031234567, +234-803-123-4567), EMAIL, ADDRESS, BVN and NIN (11 digits). About 60% have a cue ("BVN:", "NIN:") and the rest are bare.
- Decoys (not PII), kept in a separate list: invoice numbers, PO numbers, 11-digit order IDs, amounts, dates.
- Build each document from segments and record start (inclusive) and end (exclusive) as each segment is inserted. Never search for substrings afterwards.
- Write files with encoding="utf-8", newline="\n".
- data/ground_truth.json per document: file, doc_type, split (100 dev, 200 test, stratified by doc_type), entities, decoys. Each item has type, start, end and text.
- verify_ground_truth.py asserts text[start:end] equals the stored text for every item, checks for overlaps, and prints counts by type and doc_type.

## Phase 2: Scoring (gate: tests pass)
Create scripts/metrics.py and tests/test_metrics.py (tiny hand-built cases: exact, partial, miss, decoy hit).
- Strict match: same type and exact span.
- Partial overlap: overlaps a ground-truth entity but not exact.
- Leak rate (headline, type-agnostic): PII characters not covered by any predicted span, divided by total PII characters. Also report entity-level exposure: entities with at least one uncovered character, divided by all entities.
- Precision: predicted spans that overlap no entity are false positives. Spans that hit decoys are reported separately as "decoy hits".
- Recall: type-aware, per entity type.
- Merge BVN and NIN into "ID" for per-type scores, since bare 11-digit numbers cannot be told apart by form.
- Latency: ms per document, median and p95, excluding warm-up.
- Label mapping: spaCy PERSON to PERSON, GPE/LOC/FAC to ADDRESS. Presidio PERSON to PERSON, PHONE_NUMBER to PHONE, EMAIL_ADDRESS to EMAIL, LOCATION to ADDRESS. Custom recognizers output ID.

## Phase 3: Runners
- scripts/run_spacy.py: en_core_web_sm NER only. Output data/predictions_spacy.json.
- scripts/run_presidio.py: configure the AnalyzerEngine with NlpEngineProvider to use en_core_web_sm explicitly, so both tools use the same spaCy model. Two configs: default recognizers, and default plus custom BVN/NIN PatternRecognizers with context words. Tune the custom ones on dev only.

## Phase 4: Evaluate
scripts/evaluate.py scores all three configs on the test split and writes results/results.csv and results/results.md. It also writes results/error_analysis.md listing misses and decoy hits with a short context snippet.

## Phase 5: README
Include methodology, how to reproduce (PowerShell commands), results (copied from the generated files), and limitations: synthetic, template-based, small scale, and one spaCy model.

## Out of scope for now
OCR noise (Tesseract and Poppler). Do not start it.