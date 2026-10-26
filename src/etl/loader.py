import io
import logging
import os
import sys
import time
from pathlib import Path
import pandas as pd
import psycopg2
from src.db.connection import get_conn

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('etl.loader')

RAW_DIR = Path('data/raw')

# Columns that may be nullable integers (Pandas reads as float when NaN present)
NULLABLE_INT_COLS = {'agent_id', 'device_fingerprint', 'linked_nid_hash'}

TABLE_CONFIGS = [
    {
        'table_name': 'dim_transaction_type',
        'csv_file': 'dim_transaction_type.csv',
        'pk_col': 'txn_type_id',
        'cols': ['txn_type_id', 'type_name', 'max_limit_bdt', 'daily_limit_bdt', 'requires_agent', 'description'],
    },
    {
        'table_name': 'dim_customer',
        'csv_file': 'dim_customer.csv',
        'pk_col': 'customer_id',
        'cols': ['customer_id', 'customer_code', 'name', 'phone', 'district', 'division', 'account_age_days', 'kyc_tier', 'linked_nid_hash', 'registered_at'],
    },
    {
        'table_name': 'dim_agent',
        'csv_file': 'dim_agent.csv',
        'pk_col': 'agent_id',
        'cols': ['agent_id', 'agent_code', 'district', 'division', 'agent_type', 'is_active', 'commission_rate', 'registered_at'],
    },
    {
        'table_name': 'dim_time',
        'csv_file': 'dim_time.csv',
        'pk_col': 'time_id',
        'cols': ['time_id', 'ts', 'hour', 'day_of_week', 'day_name', 'week_of_year', 'month', 'month_name', 'quarter', 'year', 'is_weekend', 'is_peak_hour', 'is_month_end'],
    },
    {
        'table_name': 'fact_transactions',
        'csv_file': 'fact_transactions.csv',
        'pk_col': 'transaction_id',
        'cols': [
            'transaction_id', 'txn_ref', 'customer_id', 'agent_id', 'time_id',
            'txn_type_id', 'amount_bdt', 'fee_bdt', 'channel', 'status',
            'sender_district', 'receiver_district', 'location_lat', 'location_lon',
            'device_fingerprint', 'is_fraud', 'fraud_pattern', 'created_at'
        ],
    },
]

def load_table(conn, config: dict):
    table = config['table_name']
    csv_path = RAW_DIR / config['csv_file']
    pk_col = config['pk_col']
    cols = config['cols']
    cols_str = ', '.join(cols)

    if not csv_path.exists():
        logger.error(f'File not found: {csv_path}')
        raise FileNotFoundError(f'{csv_path} not found')

    df = pd.read_csv(csv_path)
    csv_count = len(df)
    logger.info(f'Loading {table} from {csv_path.name} ({csv_count:,} rows in CSV)...')

    # Coerce float-nullable-int cols to proper pandas Int64 so COPY gets "448" not "448.0"
    for col in cols:
        if col in df.columns and col in NULLABLE_INT_COLS:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

    sio = io.StringIO()
    df[cols].to_csv(sio, index=False, header=False, na_rep='\\N')
    sio.seek(0)

    stage_table = f'stage_{table}'
    start_time = time.time()

    with conn.cursor() as cur:
        cur.execute(f'CREATE TEMP TABLE {stage_table} (LIKE {table} INCLUDING DEFAULTS) ON COMMIT DROP;')
        copy_sql = f"COPY {stage_table} ({cols_str}) FROM STDIN WITH (FORMAT CSV, NULL '\\N');"
        cur.copy_expert(copy_sql, sio)

        upsert_sql = f"""
            INSERT INTO {table} ({cols_str})
            SELECT {cols_str} FROM {stage_table}
            ON CONFLICT ({pk_col}) DO NOTHING;
        """
        cur.execute(upsert_sql)
        inserted_count = cur.rowcount

        cur.execute(f'SELECT COUNT(*) FROM {table};')
        db_count = cur.fetchone()[0]

    conn.commit()
    elapsed = time.time() - start_time
    logger.info(
        f'Loaded {table}: {inserted_count:,} new rows inserted ({elapsed:.2f}s). Total DB count: {db_count:,}'
    )
    return csv_count, db_count

def run_etl():
    logger.info('Starting MFS Fraud Analytics ETL Pipeline...')
    conn = get_conn()
    overall_start = time.time()
    summary = []

    try:
        for config in TABLE_CONFIGS:
            csv_count, db_count = load_table(conn, config)
            summary.append({
                'Table': config['table_name'],
                'CSV Rows': csv_count,
                'DB Rows': db_count,
                'Match': csv_count == db_count
            })
    except Exception as e:
        conn.rollback()
        logger.exception(f'ETL failed: {e}')
        raise
    finally:
        conn.close()

    total_time = time.time() - overall_start
    logger.info(f'ETL Completed in {total_time:.2f} seconds.')
    print('\n' + '='*60)
    print(f'{"ETL VALIDATION SUMMARY":^60}')
    print('='*60)
    print(f'{"Table Name":<25} | {"CSV Rows":<10} | {"DB Rows":<10} | Status')
    print('-'*60)
    for s in summary:
        status = 'MATCH [OK]' if s['Match'] else 'MISMATCH'
        print(f"{s['Table']:<25} | {s['CSV Rows']:<10} | {s['DB Rows']:<10} | {status}")
    print('='*60 + '\n')

if __name__ == '__main__':
    run_etl()
