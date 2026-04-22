# Salesforce Data Consistency Pipeline

This repository contains a phased, evidence-first pipeline for Salesforce data consistency analysis.

The system is designed to detect, quantify, and track data quality issues that block AI marketing readiness.

## Scope

Current scope is read-only detection and measurement:

- Profiling
- Normalization
- Entity resolution
- Conflict detection
- KPI scorecard and trends

Out of scope for current implementation:

- Truth adjudication
- Auto-remediation in Salesforce
- ML model training

## Project Structure

- `phase1_profiler.py`: Ingestion and profiling
- `phase2_normalizer.py`: Standardization/normalization
- `phase3_entity_resolution.py`: Deterministic + fuzzy matching and clustering
- `phase4_conflict_detection.py`: Cluster-level conflict detection
- `phase5_scorecard.py`: Cross-phase KPI scorecard and trends
- `reports/`: Generated run artifacts
- `Business_Story.md`: Business-facing narrative
- `Technical_Story.md`: Technical narrative
- `Business_Story_Deck.pptx`: Business slide deck
- `Business_Story_Deck_Executive.pptx`: Executive slide deck

## Environment

Use the local virtual environment in `.venv`.

Example commands from project root:

```powershell
# Optional: activate venv
(Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned) ; (& ".\.venv\Scripts\Activate.ps1")

# Or run directly with venv python
& ".\.venv\Scripts\python.exe" .\phase1_profiler.py
```

## Runbook

Run phases in sequence.

### Phase 1

```powershell
& ".\.venv\Scripts\python.exe" .\phase1_profiler.py
```

Outputs:

- `reports/phase1_scorecard_<timestamp>.txt`
- `reports/<Object>_<timestamp>.json`

### Phase 2

```powershell
& ".\.venv\Scripts\python.exe" .\phase2_normalizer.py
```

Outputs:

- `reports/normalized_<Object>_<timestamp>.json`
- `reports/phase2_changes_<timestamp>.csv`
- `reports/phase2_normalization_report_<timestamp>.txt`

### Phase 3

```powershell
& ".\.venv\Scripts\python.exe" .\phase3_entity_resolution.py
```

Outputs:

- `reports/phase3_candidate_pairs_<timestamp>.csv`
- `reports/phase3_clusters_<timestamp>.json`
- `reports/phase3_resolution_report_<timestamp>.txt`

### Phase 4

```powershell
& ".\.venv\Scripts\python.exe" .\phase4_conflict_detection.py
```

Outputs:

- `reports/phase4_conflicts_<timestamp>.csv`
- `reports/phase4_conflicts_<timestamp>.json`
- `reports/phase4_conflict_report_<timestamp>.txt`

### Phase 5

```powershell
& ".\.venv\Scripts\python.exe" .\phase5_scorecard.py
```

Outputs:

- `reports/phase5_scorecard_<timestamp>.txt`
- `reports/phase5_scorecard_<timestamp>.json`
- `reports/phase5_trend_<timestamp>.csv`

## Slide Decks

Build scripts:

- `build_business_ppt.py`
- `build_business_ppt_executive.py`

Generated decks:

- `Business_Story_Deck.pptx`
- `Business_Story_Deck_Executive.pptx`

## Security Note

Do not keep real Salesforce credentials in source files. Move secrets to environment variables or a secure secret store.
