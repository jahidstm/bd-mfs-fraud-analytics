-- =============================================================================
-- sql/analysis/03_agent_risk_score.sql
-- Agent Risk Scoring (Composite Risk Model)
-- =============================================================================
-- Ranks agents by a composite risk score based on:
--   1. Fraud transaction count through agent
--   2. Fraud rate (% of their transactions flagged)
--   3. Night-time transaction ratio (10pm - 5am)
--   4. Cross-district transaction ratio (sender != receiver district)
-- Use case: Compliance team watchlist, agent audit prioritisation.

WITH agent_stats AS (
    SELECT
        f.agent_id,
        a.agent_code,
        a.district                                        AS agent_district,
        a.agent_type,
        a.is_active,
        COUNT(*)                                          AS total_txns,
        SUM(CASE WHEN f.is_fraud THEN 1 ELSE 0 END)       AS fraud_txns,
        SUM(f.amount_bdt)                                 AS total_volume_bdt,
        SUM(CASE WHEN t.hour BETWEEN 22 AND 23 OR t.hour BETWEEN 0 AND 4
            THEN 1 ELSE 0 END)                            AS night_txns,
        SUM(CASE WHEN f.sender_district <> f.receiver_district
            THEN 1 ELSE 0 END)                            AS cross_district_txns
    FROM fact_transactions f
    JOIN dim_agent a       ON f.agent_id = a.agent_id
    JOIN dim_time  t       ON f.time_id  = t.time_id
    WHERE f.agent_id IS NOT NULL
    GROUP BY f.agent_id, a.agent_code, a.district, a.agent_type, a.is_active
),
scored AS (
    SELECT
        agent_id,
        agent_code,
        agent_district,
        agent_type,
        is_active,
        total_txns,
        fraud_txns,
        ROUND(total_volume_bdt, 2)                         AS total_volume_bdt,
        ROUND(100.0 * fraud_txns / NULLIF(total_txns, 0), 2) AS fraud_rate_pct,
        ROUND(100.0 * night_txns / NULLIF(total_txns, 0), 2) AS night_ratio_pct,
        ROUND(100.0 * cross_district_txns / NULLIF(total_txns, 0), 2) AS cross_dist_pct,
        -- Composite risk score (weighted: fraud rate 50%, night 30%, cross-dist 20%)
        ROUND(
            (50.0 * fraud_txns / NULLIF(total_txns, 0))
          + (30.0 * night_txns / NULLIF(total_txns, 0))
          + (20.0 * cross_district_txns / NULLIF(total_txns, 0))
        , 4) AS risk_score
    FROM agent_stats
    WHERE total_txns >= 10
)
SELECT
    RANK() OVER (ORDER BY risk_score DESC)             AS risk_rank,
    agent_code,
    agent_district,
    agent_type,
    is_active,
    total_txns,
    fraud_txns,
    fraud_rate_pct,
    night_ratio_pct,
    cross_dist_pct,
    risk_score,
    CASE
        WHEN risk_score > 0.15 THEN 'HIGH'
        WHEN risk_score > 0.05 THEN 'MEDIUM'
        ELSE 'LOW'
    END AS risk_tier
FROM scored
ORDER BY risk_score DESC
LIMIT 30;
