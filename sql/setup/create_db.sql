-- =============================================================
-- sql/setup/create_db.sql
-- Run as PostgreSQL superuser (e.g., postgres):
--   psql -U postgres -f sql/setup/create_db.sql
-- =============================================================

-- Create database
CREATE DATABASE mfs_fraud
    WITH
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    TEMPLATE = template0;

-- Create dedicated user (replace 'your_strong_password_here' with a real password)
CREATE USER mfs_user WITH
    PASSWORD 'mfs_pass_2026'
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE;

-- Grant privileges
GRANT CONNECT ON DATABASE mfs_fraud TO mfs_user;
GRANT USAGE ON SCHEMA public TO mfs_user;
GRANT CREATE ON SCHEMA public TO mfs_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mfs_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mfs_user;

-- Verify
\echo '>>> Database mfs_fraud and user mfs_user created successfully.'
\echo '>>> Update DB_PASSWORD in your .env file to match the password set above.'
