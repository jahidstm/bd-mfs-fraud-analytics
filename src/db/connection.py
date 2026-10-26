"""
src/db/connection.py
--------------------
PostgreSQL connection factory using psycopg2 + python-dotenv.
Reads credentials from .env file (never hardcoded).

Usage:
    python -m src.db.connection          # test connection
    from src.db.connection import get_conn, get_engine
"""

import logging
import os
import sys

import psycopg2
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (read from environment — never hardcode credentials)
# ---------------------------------------------------------------------------

DB_HOST: str = os.environ.get("DB_HOST", "localhost")
DB_PORT: str = os.environ.get("DB_PORT", "5432")
DB_NAME: str = os.environ.get("DB_NAME", "mfs_fraud")
DB_USER: str = os.environ.get("DB_USER", "mfs_user")
DB_PASSWORD: str = os.environ.get("DB_PASSWORD", "")

DATABASE_URL: str = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)


# ---------------------------------------------------------------------------
# psycopg2 raw connection (for bulk copy / low-level ops)
# ---------------------------------------------------------------------------

def get_conn() -> psycopg2.extensions.connection:
    """Return a raw psycopg2 connection. Caller is responsible for closing."""
    return psycopg2.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


# ---------------------------------------------------------------------------
# SQLAlchemy engine (for pandas / ORM usage)
# ---------------------------------------------------------------------------

def get_engine() -> Engine:
    """Return a SQLAlchemy engine (connection-pooled)."""
    return create_engine(DATABASE_URL, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Entrypoint — connection test
# ---------------------------------------------------------------------------

def _test_connection() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    try:
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.scalar()
        logger.info("Connection OK")
        logger.info("PostgreSQL version: %s", version)
        print("\nConnection OK")
        print(f"PostgreSQL: {version}")
    except Exception as exc:
        logger.error("Connection FAILED: %s", exc)
        print(f"\nConnection FAILED: {exc}")
        print("\nCheck that:")
        print("  1. PostgreSQL is running (pg_ctl status / Services)")
        print("  2. .env file exists with correct DB_* values")
        print("  3. mfs_fraud database and mfs_user exist")
        sys.exit(1)


if __name__ == "__main__":
    _test_connection()
