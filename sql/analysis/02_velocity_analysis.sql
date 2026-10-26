-- =============================================================================
-- sql/analysis/02_velocity_analysis.sql
-- Transaction Velocity (Speed) Analysis
-- =============================================================================
-- Identifies customers with unusually high transaction frequency in short windows.
-- SIM-swap and mule-chain frauds both show extreme velocity spikes.
-- Uses Window Functions: LAG + LEAD to compute inter-transaction intervals.

WITH ranked_txns AS (
    SELECT
        f.customer_id,
        f.transaction_id,
        f.txn_ref,
        f.amount_bdt,
        f.is_fraud,
        f.fraud_pattern,
        t.ts                                         AS txn_time,
        LAG(t.ts) OVER (
            PARTITION BY f.customer_id ORDER BY t.ts
        )                                            AS prev_txn_time,
        LEAD(t.ts) OVER (
            PARTITION BY f.customer_id ORDER BY t.ts
        )                                            AS next_txn_time
    FROM fact_transactions f
    JOIN dim_time t ON f.time_id = t.time_id
),
velocity_scored AS (
    SELECT
        customer_id,
        transaction_id,
        txn_ref,
        amount_bdt,
        is_fraud,
        fraud_pattern,
        txn_time,
        EXTRACT(EPOCH FROM (txn_time - prev_txn_time)) / 60  AS mins_since_prev_txn,
        EXTRACT(EPOCH FROM (next_txn_time - txn_time)) / 60  AS mins_until_next_txn
    FROM ranked_txns
)
SELECT
    customer_id,
    COUNT(*)                                          AS txn_count,
    ROUND(AVG(mins_since_prev_txn)::NUMERIC, 1)       AS avg_mins_between_txns,
    ROUND(MIN(mins_since_prev_txn)::NUMERIC, 1)       AS min_mins_between_txns,
    SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END)         AS fraud_txns,
    SUM(CASE WHEN mins_since_prev_txn < 5 THEN 1 ELSE 0 END) AS rapid_txns_under_5min
FROM velocity_scored
WHERE mins_since_prev_txn IS NOT NULL
GROUP BY customer_id
HAVING SUM(CASE WHEN mins_since_prev_txn < 5 THEN 1 ELSE 0 END) > 0
ORDER BY rapid_txns_under_5min DESC, fraud_txns DESC
LIMIT 50;
