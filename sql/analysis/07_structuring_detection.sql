-- =============================================================================
-- sql/analysis/07_structuring_detection.sql
-- Structuring / Smurfing Detection
-- =============================================================================
-- Structuring = breaking large amounts into smaller transactions just below
-- regulatory reporting thresholds to avoid detection.
-- In BD MFS: Daily limit is 25,000 BDT. Structurers send 20,000-24,999 BDT
-- multiple times per day from the same account.
-- Uses Window Functions to aggregate daily totals and spot threshold hugging.

WITH daily_totals AS (
    SELECT
        f.customer_id,
        DATE(t.ts)                                           AS txn_date,
        COUNT(*)                                             AS daily_txn_count,
        SUM(f.amount_bdt)                                    AS daily_total_bdt,
        MAX(f.amount_bdt)                                    AS max_single_txn_bdt,
        SUM(CASE WHEN f.amount_bdt BETWEEN 20000 AND 24999
            THEN 1 ELSE 0 END)                               AS near_threshold_txns,
        SUM(CASE WHEN f.is_fraud AND f.fraud_pattern = 'structuring'
            THEN 1 ELSE 0 END)                               AS confirmed_structuring
    FROM fact_transactions f
    JOIN dim_time t ON f.time_id = t.time_id
    GROUP BY f.customer_id, DATE(t.ts)
)
SELECT
    customer_id,
    COUNT(txn_date)                                          AS active_days,
    SUM(daily_txn_count)                                     AS total_txns,
    ROUND(AVG(daily_txn_count), 1)                           AS avg_daily_txns,
    ROUND(SUM(daily_total_bdt), 2)                           AS lifetime_volume_bdt,
    SUM(near_threshold_txns)                                 AS near_threshold_txns,
    SUM(confirmed_structuring)                               AS confirmed_structuring_txns,
    MAX(daily_txn_count)                                     AS peak_txns_in_one_day
FROM daily_totals
WHERE near_threshold_txns > 0
GROUP BY customer_id
ORDER BY confirmed_structuring_txns DESC, near_threshold_txns DESC
LIMIT 30;

-- Structuring signature: amount distribution just below 25K
SELECT
    CASE
        WHEN amount_bdt BETWEEN 20000 AND 21999 THEN '20K-22K'
        WHEN amount_bdt BETWEEN 22000 AND 23999 THEN '22K-24K'
        WHEN amount_bdt BETWEEN 24000 AND 24999 THEN '24K-24.9K (suspicious)'
        WHEN amount_bdt >= 25000               THEN '>=25K'
        ELSE 'Below 20K'
    END AS amount_band,
    COUNT(*)                                                  AS txn_count,
    SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END)                 AS fraud_count,
    ROUND(100.0 * SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 2)                     AS fraud_rate_pct
FROM fact_transactions
GROUP BY amount_band
ORDER BY MIN(amount_bdt);
