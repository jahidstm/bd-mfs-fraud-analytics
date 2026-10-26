"""
src/ml/score_writer.py
----------------------
Loads trained Isolation Forest model, scores ALL 56K+ transactions,
and writes fraud_score (0.0-1.0) and rule_score (0-7) back to PostgreSQL.

Columns written:
  fact_transactions.fraud_score  DOUBLE PRECISION (0=clean, 1=max anomaly)
  fact_transactions.rule_score   INTEGER (0-7, count of rules triggered)

After writeback, updates the KPI views to include fraud scores for Power BI.

Usage:
    python -m src.ml.score_writer
"""

import logging
import sys
import time

import numpy as np
import pandas as pd
from psycopg2.extras import execute_values

from src.db.connection import get_conn, get_engine
from src.ml.features import build_features, FEATURE_COLS
from src.ml.model import load_model, scores_to_fraud_prob
from src.ml.rules import RuleBasedDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ml.score_writer")


def write_scores():
    logger.info("Loading model artifact...")
    artifact  = load_model()
    model     = artifact["model"]
    scaler    = artifact["scaler"]
    threshold = artifact["threshold"]

    logger.info(f"Model loaded | PR-AUC={artifact['test_pr_auc']:.4f} | threshold={threshold:.4f}")

    # --- Load FULL dataset (train + test combined) for scoring ---------
    logger.info("Loading full dataset for scoring (all 56K+ transactions)...")
    engine = get_engine()

    # We need transaction_id alongside features - load from view
    df_full = pd.read_sql("SELECT * FROM vw_transaction_detail", engine)
    logger.info(f"Loaded {len(df_full):,} rows for scoring")

    # Rebuild features on full dataset (no split)
    import numpy as np_
    df_full["txn_timestamp"] = pd.to_datetime(df_full["txn_timestamp"])
    df_full = df_full.sort_values(["customer_code", "txn_timestamp"]).reset_index(drop=True)

    # Amount features
    df_full["amount_log"]            = np_.log1p(df_full["amount_bdt"])
    df_full["amount_zscore"]         = df_full.groupby("txn_type")["amount_bdt"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )
    df_full["amount_near_threshold"] = ((df_full["amount_bdt"] >= 20000) & (df_full["amount_bdt"] < 25000)).astype(int)
    df_full["fee_ratio"]             = (df_full["fee_bdt"] / (df_full["amount_bdt"] + 1e-9)).clip(0, 1)

    # Velocity
    df_full["prev_txn_time"]         = df_full.groupby("customer_code")["txn_timestamp"].shift(1)
    df_full["mins_since_last_txn"]   = (
        (df_full["txn_timestamp"] - df_full["prev_txn_time"]).dt.total_seconds() / 60
    ).clip(0, 10080).fillna(9999)
    df_full["txn_date"]              = df_full["txn_timestamp"].dt.date
    df_full["cust_txn_count_24h"]    = df_full.groupby(["customer_code", "txn_date"]).cumcount() + 1
    df_full["cust_amount_sum_24h"]   = df_full.groupby(["customer_code", "txn_date"])["amount_bdt"].cumsum()
    df_full["cust_txn_count_7d"]     = df_full.groupby("customer_code").cumcount() + 1

    # Time
    df_full["is_midnight"]           = df_full["hour"].apply(lambda h: 1 if h <= 4 else 0)
    df_full["is_cross_district"]     = df_full["is_cross_district"].astype(int)
    df_full["is_away_from_home"]     = (df_full["customer_district"] != df_full["sender_district"]).astype(int)

    # Account
    df_full["is_new_account_30d"]    = (df_full["account_age_days"] < 30).astype(int)
    df_full["is_new_account_90d"]    = (df_full["account_age_days"] < 90).astype(int)
    df_full["kyc_tier_encoded"]      = df_full["kyc_tier"].map({"tier1": 1, "tier2": 2, "tier3": 3}).fillna(1)
    df_full["channel_encoded"]       = df_full["channel"].map({"app": 0, "ussd": 1, "agent": 2}).fillna(0)
    df_full["txn_type_encoded"]      = df_full["txn_type"].map(
        {"add_money": 0, "send_money": 1, "payment": 2, "cash_in": 3, "cash_out": 4}
    ).fillna(0)
    df_full["has_agent"]             = (df_full["agent_code"] != "N/A").astype(int)

    X_all = df_full[FEATURE_COLS].fillna(0)

    # --- Score with Isolation Forest ------------------------------------
    logger.info("Scoring all transactions with Isolation Forest...")
    X_scaled    = scaler.transform(X_all)
    raw_scores  = model.decision_function(X_scaled)
    fraud_probs = scores_to_fraud_prob(raw_scores)

    # --- Score with Rule Engine -----------------------------------------
    logger.info("Scoring all transactions with Rule Engine...")
    detector   = RuleBasedDetector(threshold=3)
    rule_scores = detector.score(X_all)

    # --- Writeback to PostgreSQL ----------------------------------------
    logger.info("Writing fraud_score and rule_score back to fact_transactions...")
    start = time.time()

    # Pair transaction_id with scores
    records = list(zip(
        fraud_probs.tolist(),
        [int(s) for s in rule_scores.tolist()],
        df_full["transaction_id"].tolist()
    ))

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                UPDATE fact_transactions AS f
                SET fraud_score = data.fraud_score,
                    rule_score  = data.rule_score
                FROM (VALUES %s) AS data(fraud_score, rule_score, transaction_id)
                WHERE f.transaction_id = data.transaction_id
                """,
                records,
                template="(%s::double precision, %s::integer, %s::bigint)",
                page_size=5000,
            )
        conn.commit()
        elapsed = time.time() - start
        logger.info(f"Writeback complete: {len(records):,} rows updated in {elapsed:.2f}s")
    finally:
        conn.close()

    # --- Validation stats -----------------------------------------------
    conn2 = get_conn()
    with conn2.cursor() as cur:
        thresh_val = float(threshold)
        cur.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(fraud_score) as scored,
                ROUND(AVG(fraud_score)::numeric, 4) as mean_score,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY fraud_score)::numeric, 4) as p95_score,
                ROUND(PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY fraud_score)::numeric, 4) as p99_score,
                SUM(CASE WHEN fraud_score >= %s THEN 1 ELSE 0 END) as flagged_count
            FROM fact_transactions
        """, (thresh_val,))
        stats = cur.fetchone()
    conn2.close()

    total, scored, mean_s, p95, p99, flagged = stats
    print(f"\n{'='*55}")
    print(f"{'FRAUD SCORE WRITEBACK COMPLETE':^55}")
    print(f"{'='*55}")
    print(f"  Total rows:          {total:,}")
    print(f"  Scored rows:         {scored:,}")
    print(f"  Mean fraud_score:    {mean_s}")
    print(f"  P95 fraud_score:     {p95}")
    print(f"  P99 fraud_score:     {p99}")
    print(f"  Flagged (>={threshold:.3f}): {flagged:,} transactions")
    print(f"  Flag rate:           {100*flagged/total:.2f}%")
    print(f"{'='*55}\n")

    logger.info("Score writeback pipeline complete.")


if __name__ == "__main__":
    write_scores()
