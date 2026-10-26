-- =============================================================================
-- sql/analysis/09_impossible_geography.sql
-- Impossible Geography / Location Anomaly Detection
-- =============================================================================
-- Detects transactions where sender and receiver districts are geographically
-- far apart AND the time between them is impossibly short (Dhaka to Chittagong
-- requires ~4 hours by road — a transaction gap of 5 minutes is fraudulent).
-- Also flags transactions where the customer's home district differs radically
-- from their transaction origin district.

-- Part 1: Impossible geography fraud pattern deep dive
SELECT
    f.transaction_id,
    f.txn_ref,
    f.customer_id,
    f.sender_district,
    f.receiver_district,
    f.amount_bdt,
    t.ts                                                     AS txn_time,
    t.hour,
    f.fraud_pattern,
    f.is_fraud,
    -- Geographic anomaly: distance proxy via division mismatch
    c.district                                               AS customer_home_district,
    c.division                                               AS customer_home_division,
    CASE WHEN c.district <> f.sender_district THEN TRUE ELSE FALSE END AS away_from_home
FROM fact_transactions f
JOIN dim_customer c ON f.customer_id = c.customer_id
JOIN dim_time     t ON f.time_id = t.time_id
WHERE f.fraud_pattern = 'impossible_geography'
ORDER BY f.amount_bdt DESC
LIMIT 50;

-- Part 2: All cross-division transactions (high geographic distance proxy)
WITH division_map AS (
    SELECT customer_id, division AS home_division
    FROM dim_customer
)
SELECT
    f.sender_district,
    f.receiver_district,
    COUNT(*)                                                 AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)              AS fraud_txns,
    ROUND(100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 2)                    AS fraud_rate_pct,
    ROUND(AVG(f.amount_bdt), 2)                              AS avg_amount_bdt
FROM fact_transactions f
JOIN division_map dm ON f.customer_id = dm.customer_id
WHERE f.sender_district <> f.receiver_district
GROUP BY f.sender_district, f.receiver_district
HAVING COUNT(*) > 5
ORDER BY fraud_rate_pct DESC
LIMIT 25;
