-- ============================================================================
-- Migration: 001_create_schema.sql
-- Project: Bangladesh MFS Fraud Detection & Monitoring Dashboard
-- Description: Star Schema DDL for MFS transactions and dimensional tables
-- ============================================================================

-- Drop tables if they already exist (in reverse FK dependency order)
DROP TABLE IF EXISTS fact_transactions CASCADE;
DROP TABLE IF EXISTS dim_customer CASCADE;
DROP TABLE IF EXISTS dim_agent CASCADE;
DROP TABLE IF EXISTS dim_time CASCADE;
DROP TABLE IF EXISTS dim_transaction_type CASCADE;

-- ----------------------------------------------------------------------------
-- 1. Dimension: Transaction Type
-- ----------------------------------------------------------------------------
CREATE TABLE dim_transaction_type (
    txn_type_id       INT PRIMARY KEY,
    type_name         VARCHAR(30) UNIQUE NOT NULL,
    max_limit_bdt     NUMERIC(10,2),
    daily_limit_bdt   NUMERIC(12,2),
    requires_agent    BOOLEAN NOT NULL DEFAULT FALSE,
    description       TEXT
);

-- ----------------------------------------------------------------------------
-- 2. Dimension: Customer
-- ----------------------------------------------------------------------------
CREATE TABLE dim_customer (
    customer_id       INT PRIMARY KEY,
    customer_code     VARCHAR(15) UNIQUE NOT NULL,
    name              VARCHAR(100) NOT NULL,
    phone             VARCHAR(20) NOT NULL,
    district          VARCHAR(50) NOT NULL,
    division          VARCHAR(30) NOT NULL,
    account_age_days  INT NOT NULL,
    kyc_tier          VARCHAR(10) NOT NULL,
    linked_nid_hash   BIGINT NOT NULL,
    registered_at     TIMESTAMP NOT NULL
);

-- ----------------------------------------------------------------------------
-- 3. Dimension: Agent
-- ----------------------------------------------------------------------------
CREATE TABLE dim_agent (
    agent_id          INT PRIMARY KEY,
    agent_code        VARCHAR(15) UNIQUE NOT NULL,
    district          VARCHAR(50) NOT NULL,
    division          VARCHAR(30) NOT NULL,
    agent_type        VARCHAR(20) NOT NULL,
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    commission_rate   DOUBLE PRECISION NOT NULL,
    registered_at     TIMESTAMP NOT NULL
);

-- ----------------------------------------------------------------------------
-- 4. Dimension: Time (Calendar & Temporal Features)
-- ----------------------------------------------------------------------------
CREATE TABLE dim_time (
    time_id           BIGINT PRIMARY KEY,
    ts                TIMESTAMP NOT NULL,
    hour              INT NOT NULL,
    day_of_week       INT NOT NULL,
    day_name          VARCHAR(15) NOT NULL,
    week_of_year      INT NOT NULL,
    month             INT NOT NULL,
    month_name        VARCHAR(15) NOT NULL,
    quarter           INT NOT NULL,
    year              INT NOT NULL,
    is_weekend        BOOLEAN NOT NULL,
    is_peak_hour      BOOLEAN NOT NULL,
    is_month_end      BOOLEAN NOT NULL
);

-- ----------------------------------------------------------------------------
-- 5. Fact: Transactions
-- ----------------------------------------------------------------------------
CREATE TABLE fact_transactions (
    transaction_id      BIGINT PRIMARY KEY,
    txn_ref             VARCHAR(30) UNIQUE NOT NULL,
    customer_id         INT NOT NULL REFERENCES dim_customer(customer_id),
    agent_id            INT REFERENCES dim_agent(agent_id),
    time_id             BIGINT NOT NULL REFERENCES dim_time(time_id),
    txn_type_id         INT NOT NULL REFERENCES dim_transaction_type(txn_type_id),
    amount_bdt          NUMERIC(12,2) NOT NULL,
    fee_bdt             NUMERIC(8,2) NOT NULL DEFAULT 0.00,
    channel             VARCHAR(20) NOT NULL,
    status              VARCHAR(20) NOT NULL,
    sender_district     VARCHAR(50) NOT NULL,
    receiver_district   VARCHAR(50) NOT NULL,
    location_lat        DOUBLE PRECISION,
    location_lon        DOUBLE PRECISION,
    device_fingerprint  BIGINT,
    is_fraud            BOOLEAN NOT NULL DEFAULT FALSE,
    fraud_pattern       VARCHAR(50),
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ----------------------------------------------------------------------------
-- Performance Indexes
-- ----------------------------------------------------------------------------
CREATE INDEX idx_fact_txns_customer ON fact_transactions(customer_id);
CREATE INDEX idx_fact_txns_agent ON fact_transactions(agent_id);
CREATE INDEX idx_fact_txns_time ON fact_transactions(time_id);
CREATE INDEX idx_fact_txns_type ON fact_transactions(txn_type_id);
CREATE INDEX idx_fact_txns_is_fraud ON fact_transactions(is_fraud);
CREATE INDEX idx_fact_txns_fraud_pattern ON fact_transactions(fraud_pattern);
CREATE INDEX idx_fact_txns_sender_dist ON fact_transactions(sender_district);
CREATE INDEX idx_fact_txns_receiver_dist ON fact_transactions(receiver_district);
CREATE INDEX idx_fact_txns_created_at ON fact_transactions(created_at);
CREATE INDEX idx_dim_customer_district ON dim_customer(district);
CREATE INDEX idx_dim_agent_district ON dim_agent(district);
CREATE INDEX idx_dim_time_ts ON dim_time(ts);
