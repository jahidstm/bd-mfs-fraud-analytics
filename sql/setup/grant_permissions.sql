-- =============================================================
-- sql/setup/grant_permissions.sql
-- Run as postgres superuser connected to mfs_fraud:
--   psql -U postgres -d mfs_fraud -f sql/setup/grant_permissions.sql
-- =============================================================

GRANT ALL ON SCHEMA public TO mfs_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO mfs_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO mfs_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO mfs_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO mfs_user;

\echo '>>> Permissions on mfs_fraud schema public granted to mfs_user.'
