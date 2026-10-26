"""
src/ml/features.py
------------------
Feature engineering pipeline for Bangladesh MFS fraud detection.

Features built (grouped by category):
  AMOUNT FEATURES:
    - amount_bdt               : raw transaction amount
    - amount_log               : log1p transform (normalises heavy right skew)
    - amount_zscore            : z-score within transaction type
    - amount_near_threshold    : 1 if 20000 <= amount < 25000 (structuring signal)
    - fee_ratio                : fee_bdt / amount_bdt

  VELOCITY FEATURES (customer-level rolling, no leakage from future):
    - cust_txn_count_24h       : # transactions by this customer in last 24h
    - cust_amount_sum_24h      : total amount sent in last 24h
    - cust_txn_count_7d        : # transactions in last 7 days
    - mins_since_last_txn      : minutes since customer's previous transaction

  TIME FEATURES:
    - hour                     : hour of day (0-23)
    - day_of_week              : 0=Monday, 6=Sunday
    - is_weekend               : 1 if Friday/Saturday (BD weekend)
    - is_peak_hour             : 1 if 9-13 or 17-20
    - is_midnight              : 1 if hour in 0-4 (fraud spike window)

  GEOGRAPHY FEATURES:
    - is_cross_district        : sender_district != receiver_district
    - is_away_from_home        : customer home district != sender_district

  ACCOUNT FEATURES:
    - account_age_days         : customer account age
    - is_new_account_30d       : 1 if account < 30 days old
    - is_new_account_90d       : 1 if account < 90 days old
    - kyc_tier_encoded         : ordinal encoding (tier1=1, tier2=2, tier3=3)

  CHANNEL / TYPE FEATURES:
    - channel_encoded          : app=0, ussd=1, agent=2
    - txn_type_encoded         : ordinal by fraud risk (cash_out highest)

  AGENT FEATURES:
    - has_agent                : 1 if agent involved

TARGET:
    - is_fraud (boolean -> int)

SPLIT STRATEGY:
    - Time-based: first 80% of dates = TRAIN, last 20% of dates = TEST
    - NO random split to prevent temporal leakage
    - Train/test boundary date logged

Usage:
    python -m src.ml.features
    from src.ml.features import build_features
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.db.connection import get_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ml.features")

FEATURE_COLS = [
    # Amount
    "amount_bdt", "amount_log", "amount_zscore", "amount_near_threshold", "fee_ratio",
    # Velocity
    "cust_txn_count_24h", "cust_amount_sum_24h", "cust_txn_count_7d", "mins_since_last_txn",
    # Time
    "hour", "day_of_week", "is_weekend", "is_peak_hour", "is_midnight",
    # Geography
    "is_cross_district", "is_away_from_home",
    # Account
    "account_age_days", "is_new_account_30d", "is_new_account_90d", "kyc_tier_encoded",
    # Channel / Type
    "channel_encoded", "txn_type_encoded",
    # Agent
    "has_agent",
]

TARGET_COL = "is_fraud"


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------

def _encode_kyc(tier: str) -> int:
    return {"tier1": 1, "tier2": 2, "tier3": 3}.get(str(tier), 1)

def _encode_channel(ch: str) -> int:
    return {"app": 0, "ussd": 1, "agent": 2}.get(str(ch), 0)

def _encode_txn_type(t: str) -> int:
    # Ordered by empirical fraud risk (cash_out highest)
    order = {"add_money": 0, "send_money": 1, "payment": 2, "cash_in": 3, "cash_out": 4}
    return order.get(str(t), 0)


# -------------------------------------------------------------------------
# Main feature builder
# -------------------------------------------------------------------------

def build_features(engine=None) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series, str]:
    """
    Loads data, engineers all features, performs time-based split.

    Returns:
        X_train, y_train, X_test, y_test, split_date (str)
    """
    if engine is None:
        engine = get_engine()

    logger.info("Loading data from PostgreSQL via vw_transaction_detail...")
    df = pd.read_sql("SELECT * FROM vw_transaction_detail", engine)
    logger.info(f"Loaded {len(df):,} rows, {df.shape[1]} columns")

    # ---- Parse timestamps ------------------------------------------------
    df["txn_timestamp"] = pd.to_datetime(df["txn_timestamp"])
    df = df.sort_values("txn_timestamp").reset_index(drop=True)

    # ---- Amount features -------------------------------------------------
    df["amount_log"] = np.log1p(df["amount_bdt"])

    # z-score per txn type (prevents type-confounded scores)
    df["amount_zscore"] = df.groupby("txn_type")["amount_bdt"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )
    df["amount_near_threshold"] = ((df["amount_bdt"] >= 20000) & (df["amount_bdt"] < 25000)).astype(int)
    df["fee_ratio"] = (df["fee_bdt"] / (df["amount_bdt"] + 1e-9)).clip(0, 1)

    # ---- Velocity features (NO FUTURE LEAKAGE — sort-based rolling) ------
    logger.info("Computing velocity features (sort-order safe rolling)...")
    df = df.sort_values(["customer_code", "txn_timestamp"]).reset_index(drop=True)

    # Time since last transaction (in minutes)
    df["prev_txn_time"] = df.groupby("customer_code")["txn_timestamp"].shift(1)
    df["mins_since_last_txn"] = (
        (df["txn_timestamp"] - df["prev_txn_time"]).dt.total_seconds() / 60
    ).clip(0, 10080).fillna(9999)   # 9999 = first transaction ever (no prior)

    # 24h and 7d rolling counts — use expanding on sorted data (approximation)
    # Real-world: use a proper event-time window; here we use cumcount within day
    df["txn_date"] = df["txn_timestamp"].dt.date

    # Count customer transactions on the same day (proxy for 24h velocity)
    daily_counts = (
        df.groupby(["customer_code", "txn_date"])
        .cumcount()          # index within the group (0-based, so +1 for count including current)
        + 1
    )
    df["cust_txn_count_24h"] = daily_counts

    # Sum of amounts per customer per day (cumulative up to current txn)
    df["cust_amount_sum_24h"] = df.groupby(["customer_code", "txn_date"])["amount_bdt"].cumsum()

    # 7-day count: rank within customer (total txns up to this one, proxy)
    df["cust_txn_count_7d"] = df.groupby("customer_code").cumcount() + 1

    # ---- Time features ---------------------------------------------------
    df["is_midnight"] = df["hour"].apply(lambda h: 1 if h <= 4 else 0)
    # is_weekend and is_peak_hour already exist in view

    # ---- Geography features ----------------------------------------------
    df["is_cross_district"] = df["is_cross_district"].astype(int)
    df["is_away_from_home"] = (
        df["customer_district"] != df["sender_district"]
    ).astype(int)

    # ---- Account features ------------------------------------------------
    df["is_new_account_30d"] = (df["account_age_days"] < 30).astype(int)
    df["is_new_account_90d"] = (df["account_age_days"] < 90).astype(int)
    df["kyc_tier_encoded"]   = df["kyc_tier"].apply(_encode_kyc)

    # ---- Channel / Type features -----------------------------------------
    df["channel_encoded"]  = df["channel"].apply(_encode_channel)
    df["txn_type_encoded"] = df["txn_type"].apply(_encode_txn_type)

    # ---- Agent feature ---------------------------------------------------
    df["has_agent"] = (df["agent_code"] != "N/A").astype(int)

    # ---- Target ----------------------------------------------------------
    df["is_fraud_int"] = df["is_fraud"].astype(int)

    # ---- Time-based train/test split ------------------------------------
    logger.info("Performing time-based train/test split (80/20 by date)...")
    unique_dates = sorted(df["txn_timestamp"].dt.date.unique())
    cutoff_idx   = int(len(unique_dates) * 0.80)
    split_date   = str(unique_dates[cutoff_idx])

    train_mask = df["txn_timestamp"].dt.date < unique_dates[cutoff_idx]
    test_mask  = df["txn_timestamp"].dt.date >= unique_dates[cutoff_idx]

    train_df = df[train_mask]
    test_df  = df[test_mask]

    X_train = train_df[FEATURE_COLS].fillna(0)
    y_train = train_df["is_fraud_int"]
    X_test  = test_df[FEATURE_COLS].fillna(0)
    y_test  = test_df["is_fraud_int"]

    # ---- Verify no temporal leakage --------------------------------------
    assert train_df["txn_timestamp"].max() <= test_df["txn_timestamp"].min(), \
        "LEAKAGE: train set contains timestamps after test set start!"

    logger.info(f"Split date (cutoff): {split_date}")
    logger.info(f"Train: {len(X_train):,} rows | fraud={y_train.sum():,} ({100*y_train.mean():.2f}%)")
    logger.info(f"Test:  {len(X_test):,} rows  | fraud={y_test.sum():,} ({100*y_test.mean():.2f}%)")
    logger.info(f"Features: {FEATURE_COLS}")
    logger.info(f"X_train shape: {X_train.shape} | X_test shape: {X_test.shape}")

    return X_train, y_train, X_test, y_test, split_date


if __name__ == "__main__":
    X_train, y_train, X_test, y_test, split_date = build_features()
    print(f"\n{'='*55}")
    print(f"{'FEATURE ENGINEERING SUMMARY':^55}")
    print(f"{'='*55}")
    print(f"  Split date (cutoff):  {split_date}")
    print(f"  Train set:            {X_train.shape[0]:,} rows x {X_train.shape[1]} features")
    print(f"  Test set:             {X_test.shape[0]:,} rows x {X_test.shape[1]} features")
    print(f"  Fraud rate (train):   {100*y_train.mean():.2f}%")
    print(f"  Fraud rate (test):    {100*y_test.mean():.2f}%")
    print(f"  Features: {list(X_train.columns)}")
    print(f"{'='*55}\n")
