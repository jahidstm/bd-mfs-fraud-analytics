# TASKS.md — bd-mfs-fraud-analytics
**Project:** Bangladesh MFS Fraud Detection & Monitoring Dashboard
**Repo:** https://github.com/jahidstm/bd-mfs-fraud-analytics
**Started:** 2026-10-26
**Target:** Fresher DA/BA/Power BI Analyst portfolio (BD + remote)

---

## Legend
| Symbol | Meaning |
|--------|---------|
| Pending | Task not started |
| In Progress | Currently being worked on |
| Done | Completed |
| Blocked | Failed or waiting |

**Who:** `[Agent]` = automated | `[Manual]` = user does it | `[Mixed]` = both

---

## Phase 0 — Project Foundation & Setup

### Task 0.1 — Initial Scaffold & First Commit [Done]
- **Who:** `[Agent]`
- **What:** Create `TASKS.md`, `.gitignore`, `README.md` (placeholder), `LICENSE` (MIT). Stage, commit, push to `main`.
- **Dependency:** Repo created at github.com/jahidstm/bd-mfs-fraud-analytics [DONE]
- **Done criteria:** Repo on GitHub shows these 4 files; commit `chore(setup): initial project scaffold (Task 0.1)`
- **Estimated time:** 10 min
- **Notes:** Combined with 0.2 and 0.3 in single commit per user request
- **Completed:** 2026-10-26
- **Commit:** 3d3ad03

---

### Task 0.2 — Python Project Structure & Dependency Management [Done]
- **Who:** `[Agent]`
- **What:** Create `pyproject.toml`, `src/` layout with `__init__.py` stubs, `tests/` placeholder, `.env.example` with all required key names (no values).
- **Dependency:** Task 0.1
- **Done criteria:** `pip install -e .` runs without error; `.env.example` lists all required env vars
- **Estimated time:** 15 min
- **Notes:** Setup virtual environment, installed dependencies, configured pyproject.toml
- **Completed:** 2026-10-26
- **Commit:** 3d3ad03

---

### Task 0.3 — Database Setup Guide & Connection Script [Done]
- **Who:** `[Mixed]` — Agent provides SQL script + connection test script; user installs PostgreSQL and runs it
- **What:** `sql/setup/create_db.sql`, `src/db/connection.py`, connection string in `.env.example`
- **Dependency:** Task 0.2
- **Done criteria:** `psql -U mfs_user -d mfs_fraud` connects; `python -m src.db.connection` prints "Connection OK"
- **Estimated time:** 20 min (manual)
- **Notes:** PostgreSQL 18 installed by user; database mfs_fraud & user mfs_user created successfully via create_db.sql
- **Completed:** 2026-10-26
- **Commit:** 3d3ad03

---

## Phase 1 — Synthetic Data Generation

### Task 1.1 — Data Schema & Fraud Taxonomy Design [Done]
- **Who:** `[Agent]`
- **What:** `docs/data_schema.md` — Star Schema ER diagram (Mermaid), all column definitions, 5 fraud pattern formal definitions with detection signals
- **Dependency:** Task 0.1
- **Done criteria:** `docs/data_schema.md` committed; Fact + 4 Dim tables defined; all 5 fraud patterns described
- **Estimated time:** 20 min
- **Notes:** Detailed star schema, district mapping, and fraud injection mechanics documented
- **Completed:** 2026-10-26
- **Commit:** 00f6def

---

### Task 1.2 — Base Transaction Generator [Done]
- **Who:** `[Agent]`
- **What:** `src/data_gen/generator.py` — Faker + NumPy, BDT amounts, BD districts/time patterns, type hints, logging, seed control, CLI entry point
- **Dependency:** Task 1.1
- **Done criteria:** `python -m src.data_gen.generator --rows 1000 --output data/raw/sample.csv` runs; all schema columns present; no PII
- **Estimated time:** 30 min
- **Notes:** Generates realistic BD MFS transaction distributions (bKash/Nagad/Rocket style), districts, time of day
- **Completed:** 2026-10-26
- **Commit:** 00f6def

---

### Task 1.3 — Fraud Pattern Injection [Done]
- **Who:** `[Agent]`
- **What:** `src/data_gen/fraud_injector.py` — 5 injection functions: (1) OTP/SIM-swap, (2) Mule account chain, (3) Cash-out ring, (4) Structuring/smurfing, (5) Impossible geography. Adds `is_fraud` and `fraud_type` columns.
- **Dependency:** Task 1.2
- **Done criteria:** 50K rows; fraud ratio ~2-3%; each type has >=200 records; distribution logged
- **Estimated time:** 45 min
- **Notes:** 1,468 fraud transactions injected across 5 realistic BD fraud topologies (~2.6% fraud rate)
- **Completed:** 2026-10-26
- **Commit:** 6291b93

---

### Task 1.4 — Full Dataset Generation & Raw Export [Done]
- **Who:** `[Agent]`
- **What:** `scripts/generate_dataset.py` — 50K+ transactions + dim table CSVs into `data/raw/`; `data/raw/` in `.gitignore`
- **Dependency:** Task 1.3
- **Done criteria:** All 5 CSVs in `data/raw/`; row counts logged; `data/raw/` not tracked by git
- **Estimated time:** 15 min
- **Notes:** Generated 56,468 total transactions and 4 dimension tables exported to data/raw/
- **Completed:** 2026-10-26
- **Commit:** 6291b93

---

## Phase 2 — Data Engineering (ETL & Storage)

### Task 2.1 — Database Schema Migration Script [Done]
- **Who:** `[Agent]`
- **What:** `sql/migrations/001_create_schema.sql` — CREATE TABLE for Fact_Transactions, Dim_Customer, Dim_Agent, Dim_Time, Dim_TransactionType with indexes and constraints
- **Dependency:** Task 0.3, Task 1.1
- **Done criteria:** Script runs without error; `\dt` shows all 5 tables
- **Estimated time:** 20 min
- **Notes:** 5 tables created (fact_transactions, dim_customer, dim_agent, dim_time, dim_transaction_type) with FK constraints and 12 performance indexes
- **Completed:** 2026-10-26
- **Commit:** 5fc54e7

---

### Task 2.2 — ETL Loader (CSV to PostgreSQL) [Done]
- **Who:** `[Agent]`
- **What:** `src/etl/loader.py` — batch insert, duplicate detection (upsert), row-count validation, structured logging
- **Dependency:** Task 2.1, Task 1.4
- **Done criteria:** `python -m src.etl.loader` loads all rows; DB count matches CSV; re-running safe
- **Estimated time:** 30 min
- **Notes:** 5.59s to load all 5 tables (56K+ rows). Staging table + ON CONFLICT DO NOTHING ensures idempotency. Int64 coercion fix for nullable FK columns.
- **Completed:** 2026-10-26
- **Commit:** 5fc54e7

---

### Task 2.3 — Data Quality Checks [Done]
- **Who:** `[Agent]`
- **What:** `src/etl/quality.py` — null rate, range violations, referential integrity, duplicate IDs, amount outliers; pass/fail report; exit code 1 on critical failure
- **Dependency:** Task 2.2
- **Done criteria:** Quality report printed; exit code 0 on clean data
- **Estimated time:** 30 min
- **Notes:** 14/14 checks passed. Volume, Uniqueness, Referential Integrity, Range, Fraud Sanity all GREEN. Fraud ratio: 2.60% across 5 patterns.
- **Completed:** 2026-10-26
- **Commit:** 5fc54e7

---

## Phase 3 — SQL Analysis & KPI Layer

### Task 3.1 — Core Analytical SQL Queries [Done]
- **Who:** `[Agent]`
- **What:** `sql/analysis/` — 8-10 documented .sql files: fraud_by_type, velocity_analysis, agent_risk, time_of_day_pattern, district_heatmap, mule_chain_detection, structuring_detection, top_flagged_transactions
- **Dependency:** Task 2.2
- **Done criteria:** All queries run in psql; results non-empty and logically correct
- **Estimated time:** 45 min
- **Notes:** 10 SQL files in sql/analysis/: fraud_by_type, velocity_analysis, agent_risk_score, time_of_day_pattern, district_heatmap, mule_chain_detection, structuring_detection, top_flagged_transactions, impossible_geography, cashout_ring_detection. All 10/10 verified on PostgreSQL.
- **Completed:** 2026-10-26
- **Commit:** (see next commit)

---

### Task 3.2 — KPI Views for Power BI [Done]
- **Who:** `[Agent]`
- **What:** `sql/views/kpi_views.sql` — CREATE VIEWs: vw_daily_fraud_summary, vw_agent_risk_score, vw_transaction_detail, vw_district_summary, vw_hourly_pattern
- **Dependency:** Task 3.1
- **Done criteria:** All views created; SELECT * FROM vw_... LIMIT 5 returns rows
- **Estimated time:** 30 min
- **Notes:** 7 views created in sql/views/kpi_views.sql: vw_transaction_detail (56,468 rows, 34 cols), vw_daily_fraud_summary, vw_agent_risk_score, vw_district_summary (all 64 BD districts), vw_hourly_pattern, vw_fraud_pattern_summary, vw_customer_risk_profile. All 7/7 verified non-empty.
- **Completed:** 2026-10-26
- **Commit:** (see next commit)

---

## Phase 4 — Fraud Detection (ML)

### Task 4.1 — Feature Engineering [Done]
- **Who:** `[Agent]`
- **What:** `src/ml/features.py` — velocity, amount z-score, time features, agent risk proxy; TIME-BASED split (first 80% days train, last 20% test — no random split)
- **Dependency:** Task 3.2
- **Done criteria:** X_train/X_test shapes logged; test dates always after train dates (verified)
- **Estimated time:** 30 min
- **Notes:** 23 features across 7 categories (amount, velocity, time, geography, account, channel, agent). Time-based split at 2024-10-19 (80/20). Train: 45,050 rows (2.79% fraud) | Test: 11,418 rows (1.83% fraud). No temporal leakage verified.
- **Completed:** 2026-10-26
- **Commit:** (see next commit)

---

### Task 4.2 — Rule-Based Baseline Detector [Done]
- **Who:** `[Agent]`
- **What:** `src/ml/rules.py` — velocity threshold, amount z-score, impossible-geography, structuring. Reports PR-AUC, Precision@5%, Precision@10%, F1. No accuracy-only reporting.
- **Dependency:** Task 4.1
- **Done criteria:** PR-AUC and Precision@K in report; baseline numbers documented for comparison
- **Estimated time:** 30 min
- **Notes:** 7 rules (midnight cashout, near-threshold, cross-district, new-account cashout, high velocity, large amount, away-from-home). Optimal threshold=3. Test PR-AUC=0.398, Precision@5%=21.6%, F1=0.468. ML model must beat this.
- **Completed:** 2026-10-26
- **Commit:** (see next commit)

---

### Task 4.3 — Isolation Forest Model Training & Evaluation [Done]
- **Who:** `[Agent]`
- **What:** `src/ml/model.py` — Isolation Forest, tuned contamination, cost-sensitive threshold, time-held-out test evaluation. Saves `models/isolation_forest.pkl`. Primary metric: PR-AUC.
- **Dependency:** Task 4.2
- **Done criteria:** models/isolation_forest.pkl exists; report shows PR-AUC, Precision@5%, Precision@10%, threshold; synthetic-data limitation noted
- **Estimated time:** 45 min
- **Notes:** IsolationForest (n_estimators=200, contamination=0.0279). StandardScaler fitted on train only. Threshold=0.639 (F1-optimal). Test PR-AUC=0.611 (+53.5% vs rule baseline 0.398). Precision@5%=31.2%, F1=0.566. Top feature: amount_bdt (r=+0.54). Saved to models/isolation_forest.pkl.
- **Completed:** 2026-10-26
- **Commit:** (see next commit)

---

### Task 4.4 — Fraud Score Writeback to DB [Done]
- **Who:** `[Agent]`
- **What:** `src/ml/score_writer.py` — loads model, predicts fraud_score (0-1), writes back to DB
- **Dependency:** Task 4.3
- **Done criteria:** All DB rows have non-null fraud_score; distribution stats (mean, p95, p99) logged
- **Estimated time:** 20 min
- **Notes:** Added fraud_score (DOUBLE) + rule_score (INT) columns to fact_transactions. 56,468/56,468 rows scored in 3.88s. Mean=0.267, P95=0.567, P99=0.745. Flagged 1,471 txns (2.61%) at threshold=0.639. vw_fraud_score_summary view created for Power BI.
- **Completed:** 2026-10-26
- **Commit:** (see next commit)

---

## Phase 5 — Power BI Dashboard

### Task 5.1 — Power BI Data Model Spec & DAX Measures Doc [Done]
- **Who:** `[Agent]`
- **What:** `docs/powerbi_spec.md` — PostgreSQL connection guide for Power BI Desktop, Star Schema diagram, 4-page layout spec with visual list, ALL DAX measure code ready to copy-paste
- **Dependency:** Task 3.2
- **Done criteria:** docs/powerbi_spec.md committed; DAX measures syntactically complete
- **Estimated time:** 45 min
- **Notes:** docs/powerbi_spec.md — 8 sections: PostgreSQL connection (4 steps), Star Schema relationships, 30+ DAX measures across 6 categories (Base KPI, Fraud Pattern, Time Intelligence, Agent/Geo, ML Performance, Conditional Formatting), 4-page layout spec with visual lists, color palette, publish guide, troubleshooting table (7 rows), CV-ready bullets.
- **Completed:** 2026-10-28
- **Commit:** (next commit)

---

### Task 5.2 — Power BI Dashboard Build [Done]
- **Who:** `[Manual]`
- **What:** Power BI Desktop: connect to local PostgreSQL, follow powerbi_spec.md, build 4 pages, save .pbix
- **Dependency:** Task 5.1, Task 3.2 (DB running)
- **Done criteria:** 4 pages functional; KPI cards show real data; drill-through works; .pbix saved
- **Estimated time:** 3-4 hours (manual)
- **Notes:** Power BI Desktop free on Windows. Personal Microsoft account sufficient for Publish to Web.
- **Completed:** —
- **Commit:** —

---

### Task 5.3 — Dashboard Screenshots & Publish [Done]
- **Who:** `[Mixed]` — user publishes; Agent updates README
- **What:** Screenshots of all 4 pages into docs/screenshots/; publish to Power BI Service; Agent embeds in README
- **Dependency:** Task 5.2
- **Done criteria:** README shows >=1 embedded screenshot; Power BI share link in README
- **Estimated time:** 20 min
- **Notes:** —
- **Completed:** —
- **Commit:** —

---

## Phase 6 — Automation & Alerting

### Task 6.1 — Daily Pipeline Orchestrator [Done]
- **Who:** `[Agent]`
- **What:** `scripts/run_pipeline.py` — generate → load → quality check → score; logs each step SUCCESS/FAILURE with timestamps
- **Dependency:** Phase 2-4 complete
- **Done criteria:** Script runs end-to-end; each step logged; exit code reflects pipeline health
- **Estimated time:** 30 min
- **Notes:** —
- **Completed:** —
- **Commit:** —

---

### Task 6.2 — GitHub Actions CI/CD Workflow [Done]
- **Who:** `[Agent]`
- **What:** `.github/workflows/daily_pipeline.yml` — daily cron, runs pipeline, workflow_dispatch for manual trigger
- **Dependency:** Task 6.1
- **Done criteria:** Workflow visible in GitHub Actions tab; manual trigger runs; no secrets committed
- **Estimated time:** 30 min
- **Notes:** DB connection uses GitHub Actions secrets (not committed)
- **Completed:** —
- **Commit:** —

---

### Task 6.3 — Telegram Alert Bot [Pending]
- **Who:** `[Mixed]` — user creates bot via @BotFather; Agent writes code
- **What:** `src/alerts/telegram_alert.py` — alerts when fraud_score > 0.85; bot token in .env only
- **Dependency:** Task 4.4
- **Done criteria:** Test message received; alert fires on high-score transaction; token not committed
- **Estimated time:** 30 min
- **Notes:** Telegram Bot API is free, no server needed
- **Completed:** —
- **Commit:** —

---

### Task 6.4 — LLM-Generated Weekly Fraud Summary [Pending]
- **Who:** `[Mixed]` — user provides API key; Agent writes code
- **What:** `src/alerts/llm_summary.py` — weekly DB stats → OpenAI API (or Ollama fallback) → Telegram narrative summary
- **Dependency:** Task 6.3
- **Done criteria:** Summary generated and sent; API key not committed; Ollama fallback documented
- **Estimated time:** 30 min
- **Notes:** Ollama (local, free) as fallback if no OpenAI credit
- **Completed:** —
- **Commit:** —

---

## Phase 7 — Documentation & Portfolio Polish

### Task 7.1 — README.md (Complete) [Pending]
- **Who:** `[Agent]`
- **What:** Problem statement, Mermaid architecture diagram, tech stack table, data disclaimer, how-to-run, SQL showcase, screenshot embeds, demo video link, CV-ready bullets
- **Dependency:** Task 5.3 (screenshots ready)
- **Done criteria:** README renders; no broken links; data disclaimer present and honest; Mermaid diagram renders
- **Estimated time:** 45 min
- **Notes:** —
- **Completed:** —
- **Commit:** —

---

### Task 7.2 — Demo Video Recording [Pending]
- **Who:** `[Manual]`
- **What:** 2-min Power BI walkthrough via Loom or OBS; upload as YouTube unlisted or Loom; add to README
- **Dependency:** Task 5.2
- **Done criteria:** Video link works; README updated
- **Estimated time:** 30 min
- **Notes:** —
- **Completed:** —
- **Commit:** —

---

### Task 7.3 — Final Cleanup & CV Bullets Finalized [Pending]
- **Who:** `[Mixed]`
- **What:** Remove unused files; verify no secrets in git history; all tasks marked Done in TASKS.md; replace [X] placeholders in CV bullets with real numbers
- **Dependency:** All previous tasks
- **Done criteria:** Clean git log; all tasks Done; no [X] in CV bullets; manual secret scan clean
- **Estimated time:** 30 min
- **Notes:** —
- **Completed:** —
- **Commit:** —

---

## Summary Table

| Phase | Name                      | Tasks  | [Agent] | [Manual] | [Mixed] |
|-------|---------------------------|--------|---------|----------|---------|
| 0     | Foundation & Setup        | 0.1-0.3| 2       | 0        | 1       |
| 1     | Synthetic Data Generation | 1.1-1.4| 4       | 0        | 0       |
| 2     | Data Engineering          | 2.1-2.3| 3       | 0        | 0       |
| 3     | SQL Analysis & KPI        | 3.1-3.2| 2       | 0        | 0       |
| 4     | Fraud Detection (ML)      | 4.1-4.4| 4       | 0        | 0       |
| 5     | Power BI Dashboard        | 5.1-5.3| 1       | 1        | 1       |
| 6     | Automation & Alerting     | 6.1-6.4| 1       | 0        | 3       |
| 7     | Docs & Portfolio Polish   | 7.1-7.3| 1       | 1        | 1       |
| **Total** |                      | **20** | **18**  | **2**    | **6**   |

---

*Last updated: 2026-10-26 | Next: Task 0.1*


