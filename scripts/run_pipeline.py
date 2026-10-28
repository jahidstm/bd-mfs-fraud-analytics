"""
scripts/run_pipeline.py
-----------------------
Daily pipeline orchestrator for bd-mfs-fraud-analytics.

Runs the full pipeline end-to-end:
  Step 1  [GENERATE]  — Generate a daily batch of new synthetic transactions
  Step 2  [LOAD]      — ETL: load new batch into PostgreSQL (idempotent upsert)
  Step 3  [QUALITY]   — 14-check data quality audit; fails pipeline on critical error
  Step 4  [SCORE]     — Reload & retrain model if new data > threshold, else score only
  Step 5  [REPORT]    — Print summary stats to stdout / log file

Exit codes:
  0 = All steps SUCCESS
  1 = One or more steps FAILED (check logs for details)

Usage:
    python scripts/run_pipeline.py                    # full pipeline
    python scripts/run_pipeline.py --steps load score # run specific steps
    python scripts/run_pipeline.py --dry-run          # validate config only

Logging:
    Logs go to logs/pipeline_YYYY-MM-DD.log (appended)
    Also streamed to stdout for GitHub Actions / CI visibility
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

# ─── Logging Setup ────────────────────────────────────────────────────────────

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
log_file = LOG_DIR / f"pipeline_{date.today()}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ],
)
logger = logging.getLogger("pipeline")


# ─── Step Runner ──────────────────────────────────────────────────────────────

def run_step(name: str, description: str, fn, *args, **kwargs) -> bool:
    """Run a pipeline step, log duration, return True on success."""
    separator = "─" * 60
    logger.info(separator)
    logger.info(f"STEP [{name}]  {description}")
    logger.info(separator)
    start = time.perf_counter()
    try:
        fn(*args, **kwargs)
        elapsed = time.perf_counter() - start
        logger.info(f"[{name}] SUCCESS  ({elapsed:.2f}s)")
        return True
    except SystemExit as e:
        elapsed = time.perf_counter() - start
        if e.code == 0:
            logger.info(f"[{name}] SUCCESS  ({elapsed:.2f}s)")
            return True
        logger.error(f"[{name}] FAILED   ({elapsed:.2f}s) — exit code {e.code}")
        return False
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.error(f"[{name}] FAILED   ({elapsed:.2f}s) — {exc}", exc_info=True)
        return False


# ─── Pipeline Steps ───────────────────────────────────────────────────────────

def step_generate(rows: int = 500):
    """Generate a daily batch of synthetic transactions and write to data/raw/."""
    logger.info(f"Generating {rows} new synthetic transactions...")
    from src.data_gen.generator import GeneratorConfig, TransactionGenerator
    from src.data_gen.fraud_injector import FraudInjector

    config = GeneratorConfig(
        num_transactions=rows,
        seed=int(datetime.now().timestamp()) % 99999,
    )
    gen = TransactionGenerator(config)
    datasets = gen.generate()   # saves CSVs to data/raw/ automatically

    # inject fraud into fact_transactions
    fact_df       = datasets["fact_transactions"]
    dim_customer  = datasets["dim_customer"]
    dim_agent     = datasets["dim_agent"]

    injector = FraudInjector(fraud_rate=0.026, seed=42)
    fact_df  = injector.inject(fact_df, dim_customer, dim_agent)

    # overwrite fact CSV so loader picks it up
    out_path = Path("data/raw/fact_transactions.csv")
    fact_df.to_csv(out_path, index=False)

    fraud_count = int(fact_df["is_fraud"].sum())
    logger.info(f"Generated {len(fact_df):,} rows ({fraud_count} fraud) → {out_path}")


def step_load():
    """Load daily batch CSV into PostgreSQL."""
    logger.info("Running ETL loader (upsert-safe)...")
    from src.etl.loader import run_etl
    # run_etl() loads from data/raw/ by default (idempotent upsert)
    run_etl()


def step_quality():
    """Run data quality checks — exits with code 1 on critical failure."""
    logger.info("Running 14-check data quality audit...")
    from src.etl.quality import run_quality_checks
    run_quality_checks()


def step_score():
    """Score all transactions with Isolation Forest and write back to DB."""
    logger.info("Scoring transactions with Isolation Forest...")
    from pathlib import Path
    model_path = Path("models/isolation_forest.pkl")
    if not model_path.exists():
        logger.info("Model artifact not found. Training model first on current data...")
        from src.ml.model import train_model
        train_model()
    from src.ml.score_writer import write_scores
    write_scores()


def step_report():
    """Print pipeline summary stats from the database."""
    logger.info("Generating pipeline summary report...")
    from src.db.connection import get_conn

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                COUNT(*)                                           AS total_txns,
                SUM(is_fraud::int)                                 AS fraud_cases,
                ROUND(100.0 * SUM(is_fraud::int) / COUNT(*), 3)   AS fraud_rate_pct,
                ROUND(AVG(fraud_score)::numeric, 4)                AS avg_ml_score,
                SUM(CASE WHEN fraud_score >= 0.639 THEN 1 ELSE 0 END) AS ml_flagged,
                ROUND(MAX(amount_bdt)::numeric, 2)                 AS max_txn_bdt,
                COUNT(DISTINCT sender_district)                    AS active_districts
            FROM fact_transactions;
        """)
        row = cur.fetchone()
    conn.close()

    total, fraud, rate, avg_score, flagged, max_amt, districts = row
    logger.info("=" * 60)
    logger.info("  PIPELINE SUMMARY REPORT")
    logger.info("=" * 60)
    logger.info(f"  Total transactions  : {total:,}")
    logger.info(f"  Confirmed fraud     : {fraud:,} ({rate}%)")
    logger.info(f"  ML flagged (>=0.639): {flagged:,}")
    logger.info(f"  Avg ML score        : {avg_score}")
    logger.info(f"  Max transaction     : BDT {max_amt:,.2f}")
    logger.info(f"  Active districts    : {districts}")
    logger.info("=" * 60)


# ─── Main ─────────────────────────────────────────────────────────────────────

ALL_STEPS = ["generate", "load", "quality", "score", "report"]

STEP_MAP = {
    "generate": (step_generate, "Generate daily synthetic transaction batch"),
    "load":     (step_load,     "ETL: load batch CSV into PostgreSQL"),
    "quality":  (step_quality,  "Data quality audit (14 checks)"),
    "score":    (step_score,    "ML scoring + fraud_score writeback to DB"),
    "report":   (step_report,   "Pipeline summary stats report"),
}


def main():
    parser = argparse.ArgumentParser(
        description="bd-mfs-fraud-analytics daily pipeline orchestrator"
    )
    parser.add_argument(
        "--steps",
        nargs="+",
        choices=ALL_STEPS,
        default=ALL_STEPS,
        help="Which steps to run (default: all)",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=500,
        help="Number of rows to generate in the GENERATE step (default: 500)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and imports only — do not execute",
    )
    args = parser.parse_args()

    pipeline_start = time.perf_counter()
    logger.info("=" * 60)
    logger.info("  bd-mfs-fraud-analytics DAILY PIPELINE")
    logger.info(f"  Started : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Steps   : {', '.join(args.steps)}")
    logger.info(f"  Dry run : {args.dry_run}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY-RUN mode: validating imports only...")
        try:
            import src.db.connection       # noqa
            import src.data_gen.generator  # noqa
            import src.etl.loader          # noqa
            import src.etl.quality         # noqa
            import src.ml.score_writer     # noqa
            logger.info("DRY-RUN: All imports OK. Pipeline is ready.")
        except ImportError as e:
            logger.error(f"DRY-RUN: Import failed — {e}")
            sys.exit(1)
        sys.exit(0)

    results = {}
    for step_name in args.steps:
        fn, desc = STEP_MAP[step_name]
        kwargs = {"rows": args.rows} if step_name == "generate" else {}
        success = run_step(step_name.upper(), desc, fn, **kwargs)
        results[step_name] = success

        # Stop pipeline immediately if quality check fails (critical gate)
        if step_name == "quality" and not success:
            logger.error("Quality check FAILED — aborting pipeline (data integrity at risk).")
            break

    # ── Final Summary ──────────────────────────────────────────────────────
    elapsed_total = time.perf_counter() - pipeline_start
    passed = sum(results.values())
    failed = len(results) - passed

    logger.info("=" * 60)
    logger.info("  PIPELINE COMPLETE")
    logger.info(f"  Duration : {elapsed_total:.2f}s")
    logger.info(f"  Passed   : {passed}/{len(results)} steps")
    logger.info(f"  Failed   : {failed}/{len(results)} steps")
    for step, ok in results.items():
        status = "OK " if ok else "FAIL"
        logger.info(f"    [{status}] {step}")
    logger.info("=" * 60)
    logger.info(f"Log saved to: {log_file}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
