-- =============================================================================
-- sql/analysis/10_cashout_ring_detection.sql
-- Cash-Out Ring Detection
-- =============================================================================
-- Detects coordinated cash-out rings: multiple different customers cashing out
-- through the SAME agent within a short window (30-60 minutes), often at unusual
-- hours, with similar transaction amounts.
-- Classic money laundering pattern in Bangladesh MFS.

WITH agent_cashout_windows AS (
    SELECT
        f.agent_id,
        a.agent_code,
        a.district                                           AS agent_district,
        f.customer_id,
        f.transaction_id,
        f.txn_ref,
        f.amount_bdt,
        f.is_fraud,
        f.fraud_pattern,
        t.ts                                                 AS txn_time,
        t.hour,
        -- Count distinct customers at same agent within 1-hour rolling window
        COUNT(DISTINCT f.customer_id) OVER (
            PARTITION BY f.agent_id
            ORDER BY t.ts
            RANGE BETWEEN INTERVAL '30 minutes' PRECEDING
                      AND INTERVAL '30 minutes' FOLLOWING
        )                                                    AS customers_in_window
    FROM fact_transactions f
    JOIN dim_agent a ON f.agent_id = a.agent_id
    JOIN dim_time  t ON f.time_id  = t.time_id
    WHERE f.txn_type_id = 3   -- cash_out only
      AND f.agent_id IS NOT NULL
)
SELECT
    agent_id,
    agent_code,
    agent_district,
    COUNT(*)                                                 AS total_cashouts,
    COUNT(DISTINCT customer_id)                              AS unique_customers,
    SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END)                AS confirmed_fraud_txns,
    ROUND(SUM(amount_bdt), 2)                                AS total_cashout_bdt,
    ROUND(AVG(amount_bdt), 2)                                AS avg_cashout_bdt,
    MAX(customers_in_window)                                 AS peak_customers_in_window,
    MIN(txn_time)                                            AS first_txn,
    MAX(txn_time)                                            AS last_txn
FROM agent_cashout_windows
GROUP BY agent_id, agent_code, agent_district
HAVING SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END) > 0
ORDER BY confirmed_fraud_txns DESC, total_cashout_bdt DESC
LIMIT 25;
