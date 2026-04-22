# Salesforce Data Consistency Pipeline - Business Story

## Executive Summary
The biggest blocker to successful AI marketing is not model selection. It is dirty customer data.

This project was built as AI marketing readiness infrastructure: a repeatable system that detects, quantifies, and tracks Salesforce data inconsistency before those defects degrade segmentation, personalization, lead scoring, cross-marketing execution, predictive marketing, and campaign automation.

## The Core Business Problem
AI marketing systems depend on clean identity and reliable attributes. When CRM data is inconsistent, AI outputs become unreliable.

1. Segmentation breaks
- The same customer can appear under multiple names or categories, causing incorrect audience targeting.

2. Personalization quality drops
- Inconsistent profile attributes produce irrelevant content, lower engagement, and reduced conversion.

3. Cross-marketing underperforms
- Without a reliable unified customer view, cross-sell and upsell motions miss context and target the wrong accounts.

4. Predictive marketing weakens
- Propensity and next-best-action models lose accuracy when identity and category fields are inconsistent.

5. Attribution and measurement degrade
- Duplicate and conflicting records distort campaign ROI and funnel metrics.

6. Automation confidence collapses
- Teams avoid scaling AI-driven workflows when they cannot trust underlying data.

## Why This Project Matters
This is not a reporting exercise. It is a control layer that makes AI marketing implementation feasible.

The system answers critical pre-AI questions:
1. Do we have a data consistency problem?
2. How large is it?
3. Where is it concentrated?
4. Is quality improving over time?

## What The System Delivers
The solution is implemented in five operational phases.

1. Phase 1 - Profiling
- Captures baseline snapshots and quantifies field coverage/cardinality.

2. Phase 2 - Normalization
- Standardizes names and category-like values with before/after evidence.

3. Phase 3 - Entity Resolution
- Detects likely duplicates using deterministic and fuzzy matching, then builds confidence clusters.

4. Phase 4 - Conflict Detection
- Detects disagreements within resolved entities and produces a severity-scored conflict queue.

5. Phase 5 - Scorecard and Trends
- Aggregates KPIs across runs so quality can be managed as a continuous process.

## Business Outcome Framing
This pipeline reduces AI adoption risk by improving data trust before model-dependent programs are scaled.

1. AI initiative acceleration
- Teams can move from pilot to production with a measurable data quality baseline.

2. Better campaign economics
- Cleaner entities reduce waste in targeting and improve personalization relevance.

3. Stronger cross-marketing performance
- Unified and consistent customer records increase cross-sell/upsell precision across channels and teams.

4. Better predictive marketing accuracy
- Cleaner feature fields improve model signal quality for propensity scoring, next-best-action, and forecast quality.

5. Better decision confidence
- KPI and attribution views are less distorted by duplicate/conflicting records.

6. Governance readiness
- Timestamped evidence supports stakeholder alignment and remediation planning.

## Scope Clarification
This system intentionally focuses on detection and measurement.

- It does not adjudicate canonical truth.
- It does not auto-correct Salesforce records.
- It does not train an ML model.

That boundary is deliberate: first establish data trust and observability, then layer policy-driven remediation and AI-dependent business automation.

## Current Demonstrated Outcome
The full five-phase pipeline is operational with evidence artifacts at every stage. This proves the organization can measure and govern data quality as a prerequisite to effective AI marketing.

## Portfolio Positioning
This project demonstrates strategic engineering: building the enabling system that removes the primary blocker to AI marketing value realization.
