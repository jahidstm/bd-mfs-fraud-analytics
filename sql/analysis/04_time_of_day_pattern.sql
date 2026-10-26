-- =============================================================================
-- sql/analysis/04_time_of_day_pattern.sql
-- Fraud Concentration by Hour of Day
-- =============================================================================
-- Reveals which hours have the highest fraud concentration.
-- OTP/SIM-swap fraud peaks at midnight; structuring peaks at salary-day evenings.
-- Use case: Real-time alert thresholds, shift scheduling for fraud analysts.

SELECT
    t.hour,
    COUNT(*)                                                  AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)               AS fraud_txns,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 2
    )                                                         AS fraud_rate_pct,
    ROUND(AVG(f.amount_bdt), 2)                               AS avg_amount_bdt,
    SUM(f.amount_bdt)                                         AS total_volume_bdt,
    CASE
        WHEN t.hour BETWEEN 0  AND 4  THEN 'Midnight (0-4am)'
        WHEN t.hour BETWEEN 5  AND 8  THEN 'Early Morning (5-8am)'
        WHEN t.hour BETWEEN 9  AND 12 THEN 'Morning (9am-12pm)'
        WHEN t.hour BETWEEN 13 AND 16 THEN 'Afternoon (1-4pm)'
        WHEN t.hour BETWEEN 17 AND 20 THEN 'Evening (5-8pm)'
        ELSE                               'Late Night (9-11pm)'
    END AS time_block
FROM fact_transactions f
JOIN dim_time t ON f.time_id = t.time_id
GROUP BY t.hour
ORDER BY t.hour;

-- Monthly trend of fraud rate
SELECT
    t.year,
    t.month,
    t.month_name,
    COUNT(*)                                                  AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)               AS fraud_txns,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 2
    )                                                         AS fraud_rate_pct,
    ROUND(SUM(f.amount_bdt) / 1000000, 2)                     AS total_vol_million_bdt
FROM fact_transactions f
JOIN dim_time t ON f.time_id = t.time_id
GROUP BY t.year, t.month, t.month_name
ORDER BY t.year, t.month;
