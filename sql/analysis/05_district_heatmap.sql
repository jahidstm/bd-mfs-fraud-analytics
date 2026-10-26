-- =============================================================================
-- sql/analysis/05_district_heatmap.sql
-- District-Level Fraud Heatmap
-- =============================================================================
-- Aggregates fraud counts and volumes per Bangladesh district.
-- Enables choropleth map in Power BI (join with district shapefile by name).
-- Highlights origin vs destination district asymmetry (common in cash-out fraud).

-- Part 1: Fraud heatmap by SENDER district
SELECT
    f.sender_district,
    COUNT(*)                                                 AS total_txns_originated,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)              AS fraud_txns,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 2
    )                                                        AS fraud_rate_pct,
    ROUND(SUM(f.amount_bdt) / 1000, 2)                       AS total_vol_thousand_bdt,
    ROUND(AVG(f.amount_bdt), 2)                              AS avg_amount_bdt
FROM fact_transactions f
GROUP BY f.sender_district
ORDER BY fraud_txns DESC;

-- Part 2: Cross-district flow matrix (Top fraud corridor pairs)
SELECT
    f.sender_district,
    f.receiver_district,
    COUNT(*)                                                 AS fraud_count,
    ROUND(SUM(f.amount_bdt), 2)                              AS total_fraud_amount_bdt,
    STRING_AGG(DISTINCT f.fraud_pattern, ', ')               AS fraud_patterns
FROM fact_transactions f
WHERE f.is_fraud = TRUE
  AND f.sender_district <> f.receiver_district
GROUP BY f.sender_district, f.receiver_district
ORDER BY fraud_count DESC
LIMIT 20;
