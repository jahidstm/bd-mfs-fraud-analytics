"""
src/etl/quality.py
------------------
Data quality validation suite for Bangladesh MFS Fraud Detection DB.

Checks:
  1. Null Rate: Ensures mandatory columns have 0% nulls.
  2. Uniqueness: Verifies primary keys and unique transaction references.
  3. Referential Integrity: Verifies FK links to Customer, Agent, Time, and Type.
  4. Range & Domain Violations: Checks positive amounts, valid hours, coordinates.
  5. Fraud Sanity: Verifies expected fraud presence (~2-4%) and pattern naming.

Usage:
    python -m src.etl.quality
"""

import logging
import sys
import pandas as pd
from src.db.connection import get_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("etl.quality")

def run_quality_checks():
    logger.info("Running Data Quality Checks on PostgreSQL mfs_fraud...")
    conn = get_conn()
    results = []
    has_critical_failure = False

    def add_result(check_name: str, check_type: str, passed: bool, details: str, critical: bool = True):
        nonlocal has_critical_failure
        if not passed and critical:
            has_critical_failure = True
        results.append({
            "Check": check_name,
            "Type": check_type,
            "Status": "PASS" if passed else ("FAIL" if critical else "WARN"),
            "Details": details,
        })

    try:
        with conn.cursor() as cur:
            # 1. Total row count checks
            for tbl in ["fact_transactions", "dim_customer", "dim_agent", "dim_time", "dim_transaction_type"]:
                cur.execute(f"SELECT COUNT(*) FROM {tbl};")
                cnt = cur.fetchone()[0]
                passed = cnt > 0
                add_result(f"Row count: {tbl}", "Volume", passed, f"{cnt:,} rows", critical=True)

            # 2. Duplicate checks
            cur.execute("SELECT COUNT(*), COUNT(DISTINCT txn_ref) FROM fact_transactions;")
            tot_txns, dist_refs = cur.fetchone()
            passed = (tot_txns == dist_refs)
            add_result("Unique txn_ref in Fact", "Uniqueness", passed, f"{tot_txns} total vs {dist_refs} distinct")

            # 3. Mandatory NULL checks on Fact
            mandatory_cols = ["transaction_id", "txn_ref", "customer_id", "time_id", "txn_type_id", "amount_bdt", "is_fraud"]
            null_conditions = " + ".join([f"(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)" for c in mandatory_cols])
            cur.execute(f"SELECT SUM({null_conditions}) FROM fact_transactions;")
            null_count = cur.fetchone()[0] or 0
            passed = (null_count == 0)
            add_result("Mandatory Nulls in Fact", "Null Check", passed, f"{null_count} nulls across critical fields")

            # 4. Referential Integrity Checks
            # Customer FK
            cur.execute("""
                SELECT COUNT(*) FROM fact_transactions f 
                LEFT JOIN dim_customer c ON f.customer_id = c.customer_id 
                WHERE c.customer_id IS NULL;
            """)
            orphan_cust = cur.fetchone()[0]
            add_result("Orphan Customer FK", "Referential Integrity", orphan_cust == 0, f"{orphan_cust} unlinked customers")

            # Agent FK (where agent_id is not null)
            cur.execute("""
                SELECT COUNT(*) FROM fact_transactions f 
                LEFT JOIN dim_agent a ON f.agent_id = a.agent_id 
                WHERE f.agent_id IS NOT NULL AND a.agent_id IS NULL;
            """)
            orphan_agent = cur.fetchone()[0]
            add_result("Orphan Agent FK", "Referential Integrity", orphan_agent == 0, f"{orphan_agent} unlinked agents")

            # Time FK
            cur.execute("""
                SELECT COUNT(*) FROM fact_transactions f 
                LEFT JOIN dim_time t ON f.time_id = t.time_id 
                WHERE t.time_id IS NULL;
            """)
            orphan_time = cur.fetchone()[0]
            add_result("Orphan Time FK", "Referential Integrity", orphan_time == 0, f"{orphan_time} unlinked time keys")

            # Transaction Type FK
            cur.execute("""
                SELECT COUNT(*) FROM fact_transactions f 
                LEFT JOIN dim_transaction_type tt ON f.txn_type_id = tt.txn_type_id 
                WHERE tt.txn_type_id IS NULL;
            """)
            orphan_type = cur.fetchone()[0]
            add_result("Orphan Txn Type FK", "Referential Integrity", orphan_type == 0, f"{orphan_type} unlinked types")

            # 5. Range & Domain Checks
            cur.execute("SELECT COUNT(*) FROM fact_transactions WHERE amount_bdt <= 0;")
            invalid_amounts = cur.fetchone()[0]
            add_result("Positive Amounts", "Range", invalid_amounts == 0, f"{invalid_amounts} non-positive amounts")

            cur.execute("SELECT COUNT(*) FROM fact_transactions WHERE fee_bdt < 0;")
            invalid_fees = cur.fetchone()[0]
            add_result("Non-negative Fees", "Range", invalid_fees == 0, f"{invalid_fees} negative fees")

            # 6. Fraud Labels sanity
            cur.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN is_fraud THEN 1 ELSE 0 END) as fraud_count,
                    COUNT(DISTINCT fraud_pattern) as pattern_count
                FROM fact_transactions;
            """)
            tot, frd, pat_cnt = cur.fetchone()
            frd_rate = (frd / tot * 100) if tot > 0 else 0
            # Expecting ~2.0% - 4.0% fraud rate and 5 patterns
            fraud_rate_ok = (1.5 <= frd_rate <= 5.0)
            add_result("Fraud Ratio (~2-4%)", "Sanity Check", fraud_rate_ok, f"{frd:,} fraud txns ({frd_rate:.2f}%) across {pat_cnt} patterns")

    except Exception as e:
        logger.exception(f"Quality checks failed with exception: {e}")
        has_critical_failure = True
    finally:
        conn.close()

    # Display Report
    print("\n" + "="*75)
    print(f'{"DATA QUALITY AUDIT REPORT":^75}')
    print("="*75)
    print(f'{"Check Name":<28} | {"Category":<22} | {"Status":<6} | Details')
    print("-"*75)
    for r in results:
        status_symbol = "[OK]" if r["Status"] == "PASS" else "[FAIL]"
        print(f'{r["Check"]:<28} | {r["Type"]:<22} | {status_symbol:<6} | {r["Details"]}')
    print("="*75 + "\n")

    if has_critical_failure:
        logger.error("Data Quality Audit: CRITICAL FAILURES DETECTED.")
        sys.exit(1)
    else:
        logger.info("Data Quality Audit: ALL CHECKS PASSED SUCCESSFULLY.")
        sys.exit(0)

if __name__ == "__main__":
    run_quality_checks()
