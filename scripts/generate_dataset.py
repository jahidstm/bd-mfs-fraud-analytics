"""
scripts/generate_dataset.py
-----------------------------
Full dataset generation pipeline for Bangladesh MFS Fraud Detection project.

Steps:
  1. Load config from .env
  2. Generate 50K+ legitimate transactions (TransactionGenerator)
  3. Inject 5 fraud patterns (FraudInjector)
  4. Save all CSVs to data/raw/
  5. Print summary statistics

Run:
    python scripts/generate_dataset.py
    python scripts/generate_dataset.py --transactions 100000 --seed 123
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on the path when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

import os
import pandas as pd

from src.data_gen.generator import GeneratorConfig, TransactionGenerator
from src.data_gen.fraud_injector import FraudInjector

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("generate_dataset")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate synthetic Bangladesh MFS fraud dataset."
    )
    parser.add_argument(
        "--transactions",
        type=int,
        default=int(os.getenv("NUM_TRANSACTIONS", "55000")),
        help="Number of legitimate transactions to generate (default: 55000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("DATA_SEED", "42")),
        help="Random seed (default: 42)",
    )
    parser.add_argument(
        "--fraud-rate",
        type=float,
        default=float(os.getenv("FRAUD_RATE", "0.026")),
        help="Target fraud rate 0.0-1.0 (default: 0.026)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw"),
        help="Output directory for CSV files (default: data/raw)",
    )
    parser.add_argument(
        "--customers",
        type=int,
        default=5000,
        help="Number of unique customers (default: 5000)",
    )
    parser.add_argument(
        "--agents",
        type=int,
        default=500,
        help="Number of unique agents (default: 500)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _print_summary(fact: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> None:
    """Print a formatted summary of the generated dataset."""
    sep = "=" * 60
    print(f"\n{sep}")
    print("  DATASET GENERATION SUMMARY")
    print(sep)

    total = len(fact)
    fraud_total = fact["is_fraud"].sum()
    fraud_pct = fraud_total / total * 100

    print(f"\n{'Total transactions':<30} {total:>10,}")
    print(f"{'Legitimate':<30} {total - fraud_total:>10,}")
    print(f"{'Fraud (all patterns)':<30} {fraud_total:>10,}  ({fraud_pct:.2f}%)")

    print("\n--- Fraud by pattern ---")
    pattern_counts = (
        fact[fact["is_fraud"]]
        .groupby("fraud_pattern")
        .size()
        .sort_values(ascending=False)
    )
    for pattern, count in pattern_counts.items():
        pct = count / total * 100
        print(f"  {pattern:<25} {count:>6,}  ({pct:.2f}%)")

    print("\n--- Transaction types ---")
    type_map = {1: "send_money", 2: "cash_in", 3: "cash_out", 4: "payment", 5: "add_money"}
    type_counts = fact["txn_type_id"].value_counts().sort_index()
    for tid, count in type_counts.items():
        print(f"  {type_map.get(tid, str(tid)):<20} {count:>8,}")

    print("\n--- Channels ---")
    for ch, count in fact["channel"].value_counts().items():
        print(f"  {ch:<20} {count:>8,}")

    print("\n--- Amount stats (BDT) ---")
    legit = fact[~fact["is_fraud"]]["amount_bdt"]
    frau = fact[fact["is_fraud"]]["amount_bdt"]
    print(f"  {'Legitimate':<20}  min={legit.min():>10,.0f}  max={legit.max():>10,.0f}  mean={legit.mean():>10,.0f}")
    print(f"  {'Fraud':<20}  min={frau.min():>10,.0f}  max={frau.max():>10,.0f}  mean={frau.mean():>10,.0f}")

    print("\n--- Dimension tables ---")
    for name, df in dims.items():
        print(f"  {name:<30} {len(df):>8,} rows  {df.shape[1]} cols")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    t0 = time.time()

    logger.info("=== Bangladesh MFS Fraud Dataset Generation ===")
    logger.info(
        "Config: transactions=%d seed=%d fraud_rate=%.3f customers=%d agents=%d",
        args.transactions, args.seed, args.fraud_rate, args.customers, args.agents,
    )

    # --- Step 1: Generate legitimate transactions ---
    config = GeneratorConfig(
        seed=args.seed,
        num_transactions=args.transactions,
        num_customers=args.customers,
        num_agents=args.agents,
        output_dir=args.output_dir,
    )
    generator = TransactionGenerator(config)
    datasets = generator.generate()

    fact_legit = datasets["fact_transactions"]
    dim_customer = datasets["dim_customer"]
    dim_agent = datasets["dim_agent"]
    dim_time_legit = datasets["dim_time"]
    dim_txn_type = datasets["dim_transaction_type"]

    # --- Step 2: Inject fraud patterns ---
    injector = FraudInjector(seed=args.seed, fraud_rate=args.fraud_rate)
    fact_full = injector.inject(fact_legit, dim_customer, dim_agent)

    # --- Step 3: Rebuild DIM_TIME to cover fraud timestamps ---
    import importlib
    from src.data_gen.generator import TransactionGenerator as TG
    # Re-derive dim_time from full fact timestamps
    from datetime import datetime
    all_ts = pd.to_datetime(fact_full["time_id"].astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    all_ts_list = [t for t in all_ts if pd.notna(t)]
    dim_time_full = generator.generate_dim_time(
        [datetime(t.year, t.month, t.day, t.hour, t.minute) for t in all_ts_list]
    )

    # --- Step 4: Save all CSVs ---
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    save_map = {
        "fact_transactions": fact_full,
        "dim_customer":      dim_customer,
        "dim_agent":         dim_agent,
        "dim_time":          dim_time_full,
        "dim_transaction_type": dim_txn_type,
    }

    for name, df in save_map.items():
        path = output_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        logger.info("Saved %-30s -> %s  (%d rows)", name, path, len(df))

    # --- Step 5: Print summary ---
    dims_for_summary = {k: v for k, v in save_map.items() if k != "fact_transactions"}
    _print_summary(fact_full, dims_for_summary)

    elapsed = time.time() - t0
    logger.info("=== Done in %.1f seconds ===", elapsed)


if __name__ == "__main__":
    main()
