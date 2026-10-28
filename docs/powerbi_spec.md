# Power BI Dashboard — Complete Specification
## bd-mfs-fraud-analytics | Bangladesh MFS Fraud Detection

> **Audience:** This document guides you through connecting Power BI Desktop to your local PostgreSQL database, building a 4-page dashboard, and copy-pasting all DAX measures.

---

## 1. PostgreSQL Connection Setup (Power BI Desktop)

### Step 1 — Install the PostgreSQL ODBC Driver
Download **npgsql** (recommended, free):
- URL: https://github.com/npgsql/npgsql/releases → download `Npgsql-X.X.X.msi`
- Install with default settings, restart Power BI Desktop

### Step 2 — Connect in Power BI Desktop
1. Open Power BI Desktop → **Get Data** → search `PostgreSQL`
2. Fill in:

   | Field    | Value       |
   |----------|-------------|
   | Server   | `localhost` |
   | Database | `mfs_fraud` |

3. Click **OK** → choose **Database** tab (not Windows):

   | Field    | Value      |
   |----------|------------|
   | Username | `mfs_user` |
   | Password | *(your password from `.env`)* |

4. Click **Connect**

### Step 3 — Select Tables / Views
In the Navigator, tick these **views**:

| View | Purpose |
|------|---------|
| `vw_transaction_detail` | Main fact table (56,468 rows, 34 cols) |
| `vw_daily_fraud_summary` | Daily KPI aggregates |
| `vw_agent_risk_score` | Agent-level risk ranking |
| `vw_district_summary` | 64-district heatmap data |
| `vw_hourly_pattern` | Hour-of-day fraud patterns |
| `vw_fraud_pattern_summary` | 5 fraud type breakdown |
| `vw_fraud_score_summary` | ML fraud scores (0-1) |
| `vw_customer_risk_profile` | Customer-level risk |

> **Import Mode** is fine for 56K rows. Use **DirectQuery** only if you plan to refresh daily.

### Step 4 — Set Data Types in Power Query
Open **Transform Data** and verify:

| Column | Type |
|--------|------|
| `txn_timestamp` | Date/Time |
| `amount_bdt` | Decimal Number |
| `fraud_score` | Decimal Number |
| `is_fraud` | True/False |
| `rule_score` | Whole Number |
| `hour` | Whole Number |

---

## 2. Star Schema Data Model (in Power BI)

After loading, verify in **Model view**:

```
                    +---------------------------+
                    |  vw_transaction_detail    |
         +----------+        (FACT)             +----------+
         |          |      56,468 rows          |          |
         |          +------------+--------------+          |
         |                       |                         |
         v                       v                         v
 vw_agent_risk_score   vw_daily_fraud_summary   vw_district_summary
 (agent_code FK)        (txn_date FK)           (sender_district FK)
```

**Manual relationships to create** (if not auto-detected):

| From Table | From Column | To Table | To Column | Cardinality |
|---|---|---|---|---|
| `vw_transaction_detail` | `txn_date` | `vw_daily_fraud_summary` | `txn_date` | Many:1 |
| `vw_transaction_detail` | `agent_code` | `vw_agent_risk_score` | `agent_code` | Many:1 |
| `vw_transaction_detail` | `sender_district` | `vw_district_summary` | `sender_district` | Many:1 |
| `vw_transaction_detail` | `hour` | `vw_hourly_pattern` | `hour` | Many:1 |

---

## 3. DAX Measures — Complete Code

Create a dedicated **Measures Table**: Home → Enter Data → Name it `_Measures` → Load.

Add each measure below via **New Measure** on the `_Measures` table.

---

### 3.1 Base KPI Measures

```dax
// Total Transactions
Total Transactions =
COUNTROWS( vw_transaction_detail )

// Total Volume (BDT)
Total Volume BDT =
SUM( vw_transaction_detail[amount_bdt] )

// Total Fraud Cases
Total Fraud Cases =
CALCULATE(
    COUNTROWS( vw_transaction_detail ),
    vw_transaction_detail[is_fraud] = TRUE()
)

// Fraud Rate %
Fraud Rate % =
DIVIDE(
    [Total Fraud Cases],
    [Total Transactions],
    0
) * 100

// Fraud Volume BDT
Fraud Volume BDT =
CALCULATE(
    SUM( vw_transaction_detail[amount_bdt] ),
    vw_transaction_detail[is_fraud] = TRUE()
)

// Average Fraud Score
Avg Fraud Score =
AVERAGE( vw_transaction_detail[fraud_score] )

// ML High Risk Count (fraud_score >= 0.639)
ML High Risk Count =
CALCULATE(
    COUNTROWS( vw_transaction_detail ),
    vw_transaction_detail[fraud_score] >= 0.639
)

// ML High Risk Rate %
ML High Risk Rate % =
DIVIDE(
    [ML High Risk Count],
    [Total Transactions],
    0
) * 100
```

---

### 3.2 Fraud Pattern Measures

```dax
// OTP/SIM-Swap Fraud Count
OTP SIM Swap Count =
CALCULATE(
    [Total Fraud Cases],
    vw_transaction_detail[fraud_pattern] = "otp_sim_swap"
)

// Mule Account Chain Count
Mule Account Count =
CALCULATE(
    [Total Fraud Cases],
    vw_transaction_detail[fraud_pattern] = "mule_account_chain"
)

// Cash-Out Ring Count
Cashout Ring Count =
CALCULATE(
    [Total Fraud Cases],
    vw_transaction_detail[fraud_pattern] = "cashout_ring"
)

// Structuring Count
Structuring Count =
CALCULATE(
    [Total Fraud Cases],
    vw_transaction_detail[fraud_pattern] = "structuring"
)

// Impossible Geography Count
Impossible Geo Count =
CALCULATE(
    [Total Fraud Cases],
    vw_transaction_detail[fraud_pattern] = "impossible_geography"
)

// Fraud % by Pattern (for donut/bar)
Fraud Pattern % =
DIVIDE(
    CALCULATE( [Total Fraud Cases] ),
    CALCULATE( [Total Fraud Cases], ALL( vw_transaction_detail[fraud_pattern] ) ),
    0
) * 100
```

---

### 3.3 Time Intelligence Measures

```dax
// Prior Month Transactions
Prior Month Transactions =
CALCULATE(
    [Total Transactions],
    DATEADD( vw_daily_fraud_summary[txn_date], -1, MONTH )
)

// MoM Transaction Growth %
MoM Transaction Growth % =
DIVIDE(
    [Total Transactions] - [Prior Month Transactions],
    [Prior Month Transactions],
    0
) * 100

// Prior Month Fraud Rate
Prior Month Fraud Rate =
CALCULATE(
    [Fraud Rate %],
    DATEADD( vw_daily_fraud_summary[txn_date], -1, MONTH )
)

// Fraud Rate MoM Change (percentage points)
Fraud Rate MoM Change pp =
[Fraud Rate %] - [Prior Month Fraud Rate]

// 7-Day Rolling Fraud Count
Rolling 7D Fraud Count =
CALCULATE(
    [Total Fraud Cases],
    DATESINPERIOD(
        vw_daily_fraud_summary[txn_date],
        LASTDATE( vw_daily_fraud_summary[txn_date] ),
        -7, DAY
    )
)

// Midnight Fraud Rate % (hours 0-4)
Midnight Fraud Rate % =
CALCULATE(
    [Fraud Rate %],
    vw_transaction_detail[hour] <= 4
)
```

---

### 3.4 Agent & Geography Measures

```dax
// High Risk Agent Count (avg_fraud_score > 0.5)
High Risk Agent Count =
CALCULATE(
    COUNTROWS( vw_agent_risk_score ),
    vw_agent_risk_score[avg_fraud_score] > 0.5
)

// Cross-District Fraud Rate %
Cross District Fraud Rate % =
CALCULATE(
    [Fraud Rate %],
    vw_transaction_detail[is_cross_district] = TRUE()
)
```

---

### 3.5 ML Model Performance Measures

```dax
// ML Precision (confirmed frauds among ML-flagged)
ML Precision % =
DIVIDE(
    CALCULATE(
        COUNTROWS( vw_transaction_detail ),
        vw_transaction_detail[fraud_score] >= 0.639,
        vw_transaction_detail[is_fraud] = TRUE()
    ),
    [ML High Risk Count],
    0
) * 100

// ML Recall (ML-caught among all actual frauds)
ML Recall % =
DIVIDE(
    CALCULATE(
        COUNTROWS( vw_transaction_detail ),
        vw_transaction_detail[fraud_score] >= 0.639,
        vw_transaction_detail[is_fraud] = TRUE()
    ),
    [Total Fraud Cases],
    0
) * 100

// ML vs Rule Agreement Rate %
ML Rule Agreement % =
DIVIDE(
    CALCULATE(
        COUNTROWS( vw_transaction_detail ),
        vw_transaction_detail[fraud_score] >= 0.639,
        vw_transaction_detail[rule_score] >= 3
    ),
    [ML High Risk Count],
    0
) * 100

// Rule-Only High Risk (caught by rules, missed by ML)
Rule Only High Risk =
CALCULATE(
    COUNTROWS( vw_transaction_detail ),
    vw_transaction_detail[rule_score] >= 3,
    vw_transaction_detail[fraud_score] < 0.639
)

// ML-Only High Risk (caught by ML, missed by rules)
ML Only High Risk =
CALCULATE(
    COUNTROWS( vw_transaction_detail ),
    vw_transaction_detail[fraud_score] >= 0.639,
    vw_transaction_detail[rule_score] < 3
)

// P95 Fraud Score
P95 Fraud Score =
PERCENTILEINC( vw_transaction_detail[fraud_score], 0.95 )
```

---

### 3.6 Conditional Formatting Measures

```dax
// Fraud Rate Color: Green <2%, Amber 2-4%, Red >4%
Fraud Rate Color =
SWITCH(
    TRUE(),
    [Fraud Rate %] > 4, "#E74C3C",
    [Fraud Rate %] > 2, "#F39C12",
    "#27AE60"
)

// ML Risk Tier Label
ML Risk Tier =
SWITCH(
    TRUE(),
    SELECTEDVALUE( vw_fraud_score_summary[fraud_score] ) >= 0.639, "HIGH",
    SELECTEDVALUE( vw_fraud_score_summary[fraud_score] ) >= 0.40,  "MEDIUM",
    "LOW"
)
```

---

## 4. Dashboard Layout — 4 Pages

### Page 1: Executive Overview

**Purpose:** C-suite / management summary.

| Visual | Type | Data |
|--------|------|------|
| Total Transactions | KPI Card | `[Total Transactions]` |
| Total Volume (BDT) | KPI Card | `[Total Volume BDT]` |
| Fraud Rate % | KPI Card | `[Fraud Rate %]` + color format |
| Total Fraud Cases | KPI Card | `[Total Fraud Cases]` |
| Fraud by Pattern | Donut Chart | `vw_fraud_pattern_summary` — fraud_count by fraud_pattern |
| Daily Fraud Trend | Line Chart | `vw_daily_fraud_summary` — txn_date vs fraud_count |
| Channel Breakdown | Stacked Bar | channel vs transactions / fraud cases |
| Date Slicer | Date Range | `vw_daily_fraud_summary[txn_date]` |

---

### Page 2: Fraud Investigation

**Purpose:** Analyst drill-through on individual transactions.

| Visual | Type | Data |
|--------|------|------|
| Fraud Pattern Slicer | Dropdown | `fraud_pattern` |
| ML Risk Tier Slicer | Dropdown | `ml_risk_tier` |
| Transaction Table | Table | `vw_fraud_score_summary` — sort by fraud_score DESC |
| ML Score Distribution | Clustered Bar | fraud_score binned (bin=0.05) |
| Rule vs ML Scatter | Scatter | X=rule_score, Y=fraud_score, Color=is_fraud |
| Hourly Fraud Pattern | Bar | `vw_hourly_pattern` — hour vs fraud_count |

---

### Page 3: Agent & Geography Risk

**Purpose:** Compliance — find risky agents and hot districts.

| Visual | Type | Data |
|--------|------|------|
| District Heatmap | Filled Map | `vw_district_summary` — sender_district, fraud_count |
| Top 10 Risky Agents | Bar Chart | `vw_agent_risk_score` — agent_code vs avg_fraud_score |
| Agent Risk Table | Table | `vw_agent_risk_score` all columns |
| Cross-District Rate | KPI Card | `[Cross District Fraud Rate %]` |
| Impossible Geo Count | KPI Card | `[Impossible Geo Count]` |

> **Map Tip:** Add a Power Query column: `= [sender_district] & ", Bangladesh"` and set Geography category to "City".

---

### Page 4: ML Model Performance

**Purpose:** Portfolio showcase — model metrics vs baseline.

| Visual | Type | Data |
|--------|------|------|
| ML Precision % | KPI Card | `[ML Precision %]` |
| ML Recall % | KPI Card | `[ML Recall %]` |
| PR-AUC | KPI Card | Static value: **0.611** |
| vs Baseline | KPI Card | Static text: **+53.5%** |
| Score Distribution | Clustered Bar | `vw_fraud_score_summary` — fraud_score bins, colored by is_fraud |
| ML vs Rule | Clustered Bar | Rule-Only, ML-Only, Both (3 bars) |
| Feature Importance | Bar Chart | Manual table (see below) |
| Risk Tier Donut | Donut | `vw_fraud_score_summary[ml_risk_tier]` |

**Feature Importance table** (Home → Enter Data):

| Feature | Correlation |
|---------|------------|
| amount_bdt | 0.5432 |
| amount_zscore | 0.5349 |
| cust_amount_sum_24h | 0.4820 |
| is_new_account_30d | 0.4136 |
| is_new_account_90d | 0.4058 |
| is_midnight | 0.4002 |
| cust_txn_count_24h | 0.3329 |
| amount_near_threshold | 0.3192 |
| amount_log | 0.3110 |
| mins_since_last_txn | 0.3101 |

---

## 5. Theme & Color Palette

| Element | Color |
|---------|-------|
| Fraud / Alert | `#E74C3C` (red) |
| Safe / Clean | `#27AE60` (green) |
| Warning | `#F39C12` (amber) |
| Primary accent | `#2980B9` (blue) |
| Neutral | `#7F8C8D` (grey) |

- Report title: **Segoe UI Bold 16pt**
- KPI card values: **28pt Bold**

---

## 6. Publishing to Power BI Service

**Free path — Publish to Web:**
1. File → Publish → Power BI (free Microsoft account)
2. In Power BI Service: open report → File → **Publish to web**
3. Copy embed link → paste into `README.md`

**Alternative — Screenshots + PDF:**
- Power BI Desktop → Export → Export to PDF
- Screenshots: `Win + Shift + S` → save to `docs/screenshots/`

---

## 7. Troubleshooting

| Problem | Fix |
|---------|-----|
| PostgreSQL not in Get Data | Install Npgsql, restart Power BI |
| "Cannot connect to server" | Check PostgreSQL is running: `pg_ctl status` |
| Relationship not detected | Create manually in Model view |
| Map shows wrong location | Add `", Bangladesh"` suffix in Power Query |
| Date intelligence not working | Mark `txn_date` as Date type; set date table via Table Tools |
| `fraud_score` shows as text | Set column to Decimal in Power Query |
| Blank visuals after filter | Check slicer connected to correct table/column |

---

## 8. CV-Ready Portfolio Bullets

```
- Designed and deployed a 4-page Power BI fraud analytics dashboard
  consuming 56,000+ Bangladesh MFS transactions from a PostgreSQL
  Star Schema, achieving 2.61% fraud detection rate at 0.64 threshold

- Engineered 30+ DAX measures including time-intelligence (MoM growth,
  7-day rolling counts), ML-vs-rule comparison metrics, and conditional
  color formatting for executive KPI cards

- Trained Isolation Forest (PR-AUC 0.611, +53.5% vs rule baseline)
  with score writeback to PostgreSQL; surfaced fraud_score in Power BI
  to enable analyst drill-through on 1,471 high-risk transactions

- Built 8 optimised PostgreSQL views connecting directly to Power BI,
  covering 64 Bangladesh districts, 5 fraud topology patterns (OTP/SIM-swap,
  mule chains, structuring, cash-out rings, impossible geography),
  and 24-hour time-of-day patterns
```

---

*Spec v1.0 | 2026-10-28 | bd-mfs-fraud-analytics*

