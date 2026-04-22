# Salesforce Data Consistency Pipeline - Technical Story

## Technical Objective
Build an end-to-end, evidence-first pipeline that detects and measures Salesforce data inconsistency across multiple objects.

## Architecture Overview
The implementation is split into phase-oriented Python modules with explicit outputs and contracts.

1. Phase 1 - Ingestion and Profiling
- Discovers schema and extracts object snapshots.
- Computes field coverage and cardinality metrics.
- Produces timestamped text and JSON evidence.

2. Phase 2 - Normalization
- Applies deterministic normalization for company names, person names, and category-like values.
- Writes normalized snapshots and before/after change logs.

3. Phase 3 - Entity Resolution
- Combines deterministic matching and fuzzy scoring.
- Uses similarity signals such as sequence matching, token overlap, and phonetic signal.
- Assigns confidence tiers and builds clusters from candidate links.

4. Phase 4 - Conflict Detection
- Evaluates cluster members for field-level disagreement.
- Scores conflict severity mechanically using confidence, spread, and field criticality.

5. Phase 5 - Scorecard and Trends
- Aggregates cross-phase artifacts into KPI snapshots and trend rows.
- Produces machine-readable and human-readable outputs.

## What Powers The Matching
1. Deterministic Logic
- Exact-key matching where strong identifiers exist.

2. Fuzzy Logic
- Weighted similarity scoring from multiple textual signals.

3. Phonetic Assistance
- Soundex-style signal to tolerate name variation.

4. Confidence Tiering
- Threshold-based high, medium, low labels for candidate quality.

5. Clustering
- Pair links are composed into entity clusters for downstream analysis.

## Engineering Practices Demonstrated
1. Phased System Design
- Clear separation of concerns and stage-by-stage contracts.

2. Read-Only Safety Model
- No writeback to Salesforce during development validation.

3. Evidence-First Execution
- Each run creates timestamped artifacts for replay and audit.

4. Iterative Hardening
- Matching logic was refined after observing over-clustering behavior.

5. Reproducibility
- Consistent naming conventions and run IDs across outputs.

## Important Scope Clarification
This implementation is a detection-and-measurement system.

- It does not adjudicate canonical truth.
- It does not auto-correct source records.
- It does not train a machine learning model.

That boundary is deliberate: establish reliable detection and observability before introducing adjudication or automation.

## Portfolio Positioning
This project highlights practical AI-assisted engineering with strong technical governance.

- Complex pipeline shipped in phases
- Measurable and explainable outputs
- Safety and traceability prioritized
- Technical rigor over one-off scripting
