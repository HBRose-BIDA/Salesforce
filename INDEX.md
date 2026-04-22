# Project Index

## Core Pipeline

1. `phase1_profiler.py` - Salesforce ingestion and profiling
2. `phase2_normalizer.py` - Data normalization and change evidence
3. `phase3_entity_resolution.py` - Candidate matching and clustering
4. `phase4_conflict_detection.py` - Conflict detection and severity
5. `phase5_scorecard.py` - KPI scorecard and trend aggregation

## Documentation

- `README.md` - Setup and runbook
- `Data_Consistency_Architecture.md` - Architecture overview
- `Business_Story.md` - Business narrative
- `Technical_Story.md` - Technical narrative

## Presentations

- `Business_Story_Deck.pptx`
- `Business_Story_Deck_Executive.pptx`

Deck generation scripts:
- `build_business_ppt.py`
- `build_business_ppt_executive.py`

## Inputs and Utilities

- `config.json` - Runtime configuration (contains sensitive values)
- `Read_One.py` - Salesforce connectivity/query sample
- `testoauth.py` - OAuth connectivity sample

## Output Artifacts

All generated evidence is written to `reports/`.

Main artifact families:
- Phase 1: `phase1_scorecard_*.txt`, `<Object>_*.json`
- Phase 2: `normalized_*.json`, `phase2_changes_*.csv`, `phase2_normalization_report_*.txt`
- Phase 3: `phase3_candidate_pairs_*.csv`, `phase3_clusters_*.json`, `phase3_resolution_report_*.txt`
- Phase 4: `phase4_conflicts_*.csv`, `phase4_conflicts_*.json`, `phase4_conflict_report_*.txt`
- Phase 5: `phase5_scorecard_*.txt`, `phase5_scorecard_*.json`, `phase5_trend_*.csv`
