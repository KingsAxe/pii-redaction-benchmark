# PHASE 3 SPEC (supersedes Phase 3 in PROJECT_BRIEF.md)
Files: scripts/run_spacy.py, run_presidio.py, custom_recognizers.py, validate_predictions.py, tests/test_runners.py

Common rules
1. Read data/ground_truth.json; text from data/raw/ (--raw-dir is authoritative if given). Sort by doc_id. Keys are the ground-truth doc_id exactly.
2. --splits accepts only dev and/or test. Output: data/predictions/<config>__<split>.json (one file per split), UTF-8, LF newlines.
3. Schema: {"doc_id": {"spans": [{"label","start","end"}], "ms": float}}. Keep every span with its raw label; no filtering.
4. Timing: process 5 throwaway dev documents first (never test), unrecorded. Then record perf_counter ms around the analysis call only, never model loading.
5. Seed 42. Write package versions to results/environment.txt.
6. Default spaCy pipeline for both tools, no components disabled.

Configs: spacy | presidio default | presidio ng_phone (default + NG phone recognizer) | presidio custom (ng_phone + BVN/NIN PatternRecognizers in custom_recognizers.py)

Tuning protocol
- Only custom_recognizers.py may be tuned (regex, base score, context words, boost), using dev only.
- Log every dev experiment (change, dev ID recall, dev precision) in results/tuning_log.md.
- Freeze: commit "freeze custom config" and write results/freeze.json with the sha256 of custom_recognizers.py.
- `run_presidio.py --config custom --splits test` must refuse unless freeze.json exists and the hash matches.
- spacy, default and ng_phone involve no tuning and may run on both splits any time. Nobody may view test error records or error analysis, for any config, before the freeze.

validate_predictions.py: per file, every doc_id of that split present, no extras, 0 <= start < end <= len(text), labels are str, ms is float. Print label counts; exit non-zero on failure.
tests/test_runners.py: validator (good file, missing doc, out-of-range span), split rejection, freeze check (refuses without freeze.json, refuses on hash mismatch).
