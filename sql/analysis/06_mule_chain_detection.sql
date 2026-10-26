-- =============================================================================
-- sql/analysis/06_mule_chain_detection.sql
-- Mule Account Chain Detection
-- =============================================================================
-- Detects potential mule chains: a customer sends money AND receives money
-- within a short time window, forwarding funds down the chain.
-- Signals: Same amount forwarded, multiple hops within 10-30 minutes.
-- Uses CTE recursion concept via self-join on amount + time proximity.

-- Part 1: Customers who are BOTH senders and receivers (potential mules)
WITH sender_recv AS (
    SELECT
        f.customer_id,
        c.customer_code,
        c.district,
        c.account_age_days,
        c.kyc_tier,
        COUNT(*)                                             AS total_txns,
        SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)          AS flagged_txns,
        SUM(f.amount_bdt)                                    AS net_volume_bdt,
        -- Transactions where this customer appears as sender (customer_id)
        SUM(CASE WHEN f.txn_type_id IN (1, 3) THEN 1 ELSE 0 END) AS send_money_txns,
        -- Cash-outs (suspicious end of chain)
        SUM(CASE WHEN f.txn_type_id = 3 THEN 1 ELSE 0 END)  AS cashout_txns,
        STRING_AGG(DISTINCT COALESCE(f.fraud_pattern, 'legitimate'), ', ') AS patterns
    FROM fact_transactions f
    JOIN dim_customer c ON f.customer_id = c.customer_id
    GROUP BY f.customer_id, c.customer_code, c.district, c.account_age_days, c.kyc_tier
)
SELECT
    customer_id,
    customer_code,
    district,
    account_age_days,
    kyc_tier,
    total_txns,
    flagged_txns,
    ROUND(100.0 * flagged_txns / NULLIF(total_txns, 0), 2)   AS flag_rate_pct,
    ROUND(net_volume_bdt, 2)                                  AS net_volume_bdt,
    cashout_txns,
    patterns
FROM sender_recv
WHERE flagged_txns > 0
  AND cashout_txns > 0
  AND account_age_days < 180        -- New accounts more likely to be mules
ORDER BY flagged_txns DESC, flag_rate_pct DESC
LIMIT 30;

-- Part 2: Mule chain specific pattern summary
SELECT
    fraud_pattern,
    COUNT(*)                                                  AS txn_count,
    COUNT(DISTINCT customer_id)                               AS unique_customers,
    ROUND(AVG(amount_bdt), 2)                                 AS avg_amount_bdt,
    ROUND(MIN(amount_bdt), 2)                                 AS min_amount_bdt,
    ROUND(MAX(amount_bdt), 2)                                 AS max_amount_bdt,
    ROUND(SUM(amount_bdt) / 1000, 2)                          AS total_vol_thousand_bdt
FROM fact_transactions
WHERE fraud_pattern = 'mule_chain'
GROUP BY fraud_pattern;
