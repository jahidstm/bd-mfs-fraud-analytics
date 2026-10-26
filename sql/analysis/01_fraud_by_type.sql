-- =============================================================================
-- sql/analysis/01_fraud_by_type.sql
-- Fraud Pattern Distribution Analysis
-- =============================================================================
-- Shows total volume, fraud count, fraud rate, and avg amount per fraud pattern.
-- Use case: Executive summary KPI, dashboard headline numbers.

SELECT
    COALESCE(f.fraud_pattern, 'legitimate')         AS fraud_pattern,
    COUNT(*)                                         AS total_transactions,
    SUM(f.amount_bdt)                                AS total_amount_bdt,
    ROUND(AVG(f.amount_bdt), 2)                      AS avg_amount_bdt,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_all_txns
FROM fact_transactions f
GROUP BY f.fraud_pattern
ORDER BY total_transactions DESC;

-- Fraud rate by transaction type (e.g., cash_out has highest fraud risk)
SELECT
    tt.type_name                                     AS txn_type,
    COUNT(*)                                         AS total_txns,
    SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)      AS fraud_count,
    ROUND(
        100.0 * SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END) / COUNT(*), 2
    )                                                AS fraud_rate_pct,
    ROUND(AVG(f.amount_bdt), 2)                      AS avg_amount_bdt
FROM fact_transactions f
JOIN dim_transaction_type tt ON f.txn_type_id = tt.txn_type_id
GROUP BY tt.type_name
ORDER BY fraud_rate_pct DESC;
