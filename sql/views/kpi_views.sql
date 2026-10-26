-- =============================================================================
-- sql/views/kpi_views.sql
-- Power BI KPI Views for Bangladesh MFS Fraud Detection Dashboard
-- =============================================================================
-- Run once against mfs_fraud database:
--   psql -U mfs_user -d mfs_fraud -f sql/views/kpi_views.sql
-- All views are SELECT-only and safe for Power BI DirectQuery.

DROP VIEW IF EXISTS vw_transaction_detail     CASCADE;
DROP VIEW IF EXISTS vw_daily_fraud_summary    CASCADE;
DROP VIEW IF EXISTS vw_agent_risk_score       CASCADE;
DROP VIEW IF EXISTS vw_district_summary       CASCADE;
DROP VIEW IF EXISTS vw_hourly_pattern         CASCADE;
DROP VIEW IF EXISTS vw_fraud_pattern_summary  CASCADE;
DROP VIEW IF EXISTS vw_customer_risk_profile  CASCADE;

-- ---------------------------------------------------------------------------
-- 1. vw_transaction_detail
--    Full denormalised transaction view (star schema flattened for Power BI)
-- ---------------------------------------------------------------------------
CREATE VIEW vw_transaction_detail AS
SELECT
    f.transaction_id,
    f.txn_ref,
    -- Customer
    c.customer_code,
    c.district                   AS customer_district,
    c.division                   AS customer_division,
    c.kyc_tier,
    c.account_age_days,
    -- Agent
    COALESCE(a.agent_code, 'N/A')          AS agent_code,
    COALESCE(a.district, 'N/A')            AS agent_district,
    COALESCE(a.agent_type, 'N/A')          AS agent_type,
    -- Transaction Type
    tt.type_name                 AS txn_type,
    -- Fact columns
    f.amount_bdt,
    f.fee_bdt,
    f.channel,
    f.status,
    f.sender_district,
    f.receiver_district,
    f.is_fraud,
    COALESCE(f.fraud_pattern, 'legitimate') AS fraud_pattern,
    -- Time
    t.ts                         AS txn_timestamp,
    t.hour,
    t.day_of_week,
    t.day_name,
    t.week_of_year,
    t.month,
    t.month_name,
    t.quarter,
    t.year,
    t.is_weekend,
    t.is_peak_hour,
    t.is_month_end,
    -- Derived risk flags
    CASE WHEN f.sender_district <> f.receiver_district THEN TRUE ELSE FALSE END AS is_cross_district,
    CASE WHEN t.hour BETWEEN 0 AND 4 THEN TRUE ELSE FALSE END                   AS is_midnight_txn,
    CASE WHEN c.account_age_days < 90  THEN TRUE ELSE FALSE END                 AS is_new_account
FROM fact_transactions      f
JOIN dim_customer           c  ON f.customer_id  = c.customer_id
JOIN dim_time               t  ON f.time_id       = t.time_id
JOIN dim_transaction_type   tt ON f.txn_type_id   = tt.txn_type_id
LEFT JOIN dim_agent         a  ON f.agent_id      = a.agent_id;

-- ---------------------------------------------------------------------------
-- 2. vw_daily_fraud_summary
--    Daily aggregated KPIs — headline card metrics for Power BI
-- ---------------------------------------------------------------------------
CREATE VIEW vw_daily_fraud_summary AS
SELECT
    DATE(t.ts)                                               AS txn_date,
    t.month,
    t.month_name,
    t.quarter,
    t.year,
    t.is_weekend,
    COUNT(*)                                                 AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)              AS fraud_txns,
    SUM(CASE WHEN NOT f.is_fraud THEN 1 ELSE 0 END)          AS legit_txns,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 4
    )                                                        AS fraud_rate_pct,
    ROUND(SUM(f.amount_bdt), 2)                              AS total_volume_bdt,
    ROUND(SUM(CASE WHEN f.is_fraud THEN f.amount_bdt ELSE 0 END), 2) AS fraud_volume_bdt,
    ROUND(AVG(f.amount_bdt), 2)                              AS avg_txn_amount_bdt,
    COUNT(DISTINCT f.customer_id)                            AS unique_customers,
    COUNT(DISTINCT CASE WHEN f.is_fraud THEN f.customer_id END) AS fraudulent_customers
FROM fact_transactions f
JOIN dim_time t ON f.time_id = t.time_id
GROUP BY DATE(t.ts), t.month, t.month_name, t.quarter, t.year, t.is_weekend
ORDER BY txn_date;

-- ---------------------------------------------------------------------------
-- 3. vw_agent_risk_score
--    Per-agent risk scorecard for Power BI agent watchlist page
-- ---------------------------------------------------------------------------
CREATE VIEW vw_agent_risk_score AS
WITH agent_stats AS (
    SELECT
        f.agent_id,
        a.agent_code,
        a.district,
        a.division,
        a.agent_type,
        a.is_active,
        COUNT(*)                                             AS total_txns,
        SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)          AS fraud_txns,
        ROUND(SUM(f.amount_bdt), 2)                          AS total_volume_bdt,
        SUM(CASE WHEN t.hour BETWEEN 22 AND 23 OR t.hour BETWEEN 0 AND 4
            THEN 1 ELSE 0 END)                               AS night_txns,
        SUM(CASE WHEN f.sender_district <> f.receiver_district
            THEN 1 ELSE 0 END)                               AS cross_district_txns,
        COUNT(DISTINCT f.customer_id)                        AS unique_customers_served
    FROM fact_transactions f
    JOIN dim_agent a ON f.agent_id = a.agent_id
    JOIN dim_time  t ON f.time_id  = t.time_id
    WHERE f.agent_id IS NOT NULL
    GROUP BY f.agent_id, a.agent_code, a.district, a.division, a.agent_type, a.is_active
)
SELECT
    agent_id,
    agent_code,
    district,
    division,
    agent_type,
    is_active,
    total_txns,
    fraud_txns,
    unique_customers_served,
    ROUND(100.0 * fraud_txns / NULLIF(total_txns, 0), 4)        AS fraud_rate_pct,
    ROUND(100.0 * night_txns / NULLIF(total_txns, 0), 4)        AS night_ratio_pct,
    ROUND(100.0 * cross_district_txns / NULLIF(total_txns, 0), 4) AS cross_dist_pct,
    total_volume_bdt,
    ROUND(
        (50.0 * fraud_txns / NULLIF(total_txns, 0))
      + (30.0 * night_txns / NULLIF(total_txns, 0))
      + (20.0 * cross_district_txns / NULLIF(total_txns, 0))
    , 6)                                                        AS risk_score,
    CASE
        WHEN (50.0 * fraud_txns / NULLIF(total_txns, 0)
            + 30.0 * night_txns / NULLIF(total_txns, 0)
            + 20.0 * cross_district_txns / NULLIF(total_txns, 0)) > 0.15 THEN 'HIGH'
        WHEN (50.0 * fraud_txns / NULLIF(total_txns, 0)
            + 30.0 * night_txns / NULLIF(total_txns, 0)
            + 20.0 * cross_district_txns / NULLIF(total_txns, 0)) > 0.05 THEN 'MEDIUM'
        ELSE 'LOW'
    END                                                         AS risk_tier
FROM agent_stats
WHERE total_txns >= 5;

-- ---------------------------------------------------------------------------
-- 4. vw_district_summary
--    District-level fraud aggregation for choropleth map in Power BI
-- ---------------------------------------------------------------------------
CREATE VIEW vw_district_summary AS
SELECT
    f.sender_district                                        AS district,
    COUNT(*)                                                 AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)              AS fraud_txns,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 4
    )                                                        AS fraud_rate_pct,
    ROUND(SUM(f.amount_bdt) / 1000000, 4)                    AS total_vol_million_bdt,
    ROUND(AVG(f.amount_bdt), 2)                              AS avg_amount_bdt,
    COUNT(DISTINCT f.customer_id)                            AS unique_customers,
    COUNT(DISTINCT f.agent_id)                               AS unique_agents,
    -- Top fraud pattern in this district
    MODE() WITHIN GROUP (ORDER BY COALESCE(f.fraud_pattern, 'legitimate')) AS dominant_fraud_pattern
FROM fact_transactions f
GROUP BY f.sender_district;

-- ---------------------------------------------------------------------------
-- 5. vw_hourly_pattern
--    Hourly fraud concentration — for heatmap calendar visual
-- ---------------------------------------------------------------------------
CREATE VIEW vw_hourly_pattern AS
SELECT
    t.hour,
    t.day_of_week,
    t.day_name,
    COUNT(*)                                                  AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)               AS fraud_txns,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 4
    )                                                         AS fraud_rate_pct,
    ROUND(AVG(f.amount_bdt), 2)                               AS avg_amount_bdt,
    CASE
        WHEN t.hour BETWEEN 0  AND 4  THEN 'Midnight'
        WHEN t.hour BETWEEN 5  AND 8  THEN 'Early Morning'
        WHEN t.hour BETWEEN 9  AND 12 THEN 'Morning'
        WHEN t.hour BETWEEN 13 AND 16 THEN 'Afternoon'
        WHEN t.hour BETWEEN 17 AND 20 THEN 'Evening'
        ELSE                               'Late Night'
    END AS time_block
FROM fact_transactions f
JOIN dim_time t ON f.time_id = t.time_id
GROUP BY t.hour, t.day_of_week, t.day_name
ORDER BY t.day_of_week, t.hour;

-- ---------------------------------------------------------------------------
-- 6. vw_fraud_pattern_summary
--    Fraud pattern breakdown — for donut/bar chart in Power BI
-- ---------------------------------------------------------------------------
CREATE VIEW vw_fraud_pattern_summary AS
SELECT
    COALESCE(fraud_pattern, 'legitimate')                     AS fraud_pattern,
    COUNT(*)                                                  AS txn_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)        AS pct_of_all,
    ROUND(SUM(amount_bdt), 2)                                 AS total_amount_bdt,
    ROUND(AVG(amount_bdt), 2)                                 AS avg_amount_bdt,
    COUNT(DISTINCT customer_id)                               AS unique_customers_involved
FROM fact_transactions
GROUP BY fraud_pattern;

-- ---------------------------------------------------------------------------
-- 7. vw_customer_risk_profile
--    Customer-level risk summary — for customer deep-dive page
-- ---------------------------------------------------------------------------
CREATE VIEW vw_customer_risk_profile AS
SELECT
    c.customer_id,
    c.customer_code,
    c.district,
    c.division,
    c.kyc_tier,
    c.account_age_days,
    COUNT(f.transaction_id)                                    AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)                AS fraud_txns,
    ROUND(100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
                / NULLIF(COUNT(f.transaction_id), 0), 4)       AS fraud_rate_pct,
    ROUND(SUM(f.amount_bdt), 2)                                AS lifetime_volume_bdt,
    ROUND(AVG(f.amount_bdt), 2)                                AS avg_txn_bdt,
    MAX(f.amount_bdt)                                          AS max_single_txn_bdt,
    STRING_AGG(DISTINCT COALESCE(f.fraud_pattern, ''), ', '
        ORDER BY COALESCE(f.fraud_pattern, ''))                AS fraud_patterns_seen,
    CASE
        WHEN SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END) > 5  THEN 'HIGH'
        WHEN SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END) > 0  THEN 'MEDIUM'
        ELSE 'CLEAN'
    END                                                        AS risk_category
FROM dim_customer c
LEFT JOIN fact_transactions f ON c.customer_id = f.customer_id
GROUP BY c.customer_id, c.customer_code, c.district, c.division, c.kyc_tier, c.account_age_days;
