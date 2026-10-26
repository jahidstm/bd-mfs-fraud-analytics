-- =============================================================================
-- sql/analysis/08_top_flagged_transactions.sql
-- Top Flagged Transactions — Investigation Queue
-- =============================================================================
-- Produces a prioritised list of high-value fraud transactions for analyst review.
-- Combines amount, pattern severity, time-of-day risk, and cross-district flag
-- into a composite investigation priority score.
-- Use case: Daily fraud analyst work queue, case management feed.

WITH txn_risk AS (
    SELECT
        f.transaction_id,
        f.txn_ref,
        c.customer_code,
        c.kyc_tier,
        c.district                                           AS customer_district,
        COALESCE(a.agent_code, 'N/A')                        AS agent_code,
        COALESCE(a.district, 'N/A')                          AS agent_district,
        tt.type_name                                         AS txn_type,
        f.amount_bdt,
        f.fee_bdt,
        f.channel,
        f.status,
        f.sender_district,
        f.receiver_district,
        t.ts                                                 AS txn_timestamp,
        t.hour,
        t.day_name,
        f.is_fraud,
        COALESCE(f.fraud_pattern, 'legitimate')              AS fraud_pattern,
        -- Risk scoring factors
        CASE WHEN f.amount_bdt > 20000 THEN 3
             WHEN f.amount_bdt > 10000 THEN 2
             ELSE 1 END                                      AS amount_risk,
        CASE WHEN t.hour BETWEEN 0 AND 4 THEN 3
             WHEN t.hour BETWEEN 22 AND 23 THEN 2
             ELSE 1 END                                      AS time_risk,
        CASE WHEN f.sender_district <> f.receiver_district THEN 2
             ELSE 1 END                                      AS geo_risk,
        CASE WHEN c.account_age_days < 30 THEN 3
             WHEN c.account_age_days < 90 THEN 2
             ELSE 1 END                                      AS account_age_risk
    FROM fact_transactions f
    JOIN dim_customer         c  ON f.customer_id = c.customer_id
    JOIN dim_time             t  ON f.time_id = t.time_id
    JOIN dim_transaction_type tt ON f.txn_type_id = tt.txn_type_id
    LEFT JOIN dim_agent       a  ON f.agent_id = a.agent_id
    WHERE f.is_fraud = TRUE
)
SELECT
    transaction_id,
    txn_ref,
    customer_code,
    kyc_tier,
    customer_district,
    agent_code,
    txn_type,
    amount_bdt,
    channel,
    sender_district,
    receiver_district,
    txn_timestamp,
    hour,
    day_name,
    fraud_pattern,
    (amount_risk + time_risk + geo_risk + account_age_risk) AS priority_score,
    CASE
        WHEN (amount_risk + time_risk + geo_risk + account_age_risk) >= 9  THEN 'CRITICAL'
        WHEN (amount_risk + time_risk + geo_risk + account_age_risk) >= 7  THEN 'HIGH'
        WHEN (amount_risk + time_risk + geo_risk + account_age_risk) >= 5  THEN 'MEDIUM'
        ELSE 'LOW'
    END AS investigation_priority
FROM txn_risk
ORDER BY priority_score DESC, amount_bdt DESC
LIMIT 100;
