#!/usr/bin/env bash
# Runs once on the primary's first boot (via /docker-entrypoint-initdb.d).
# Creates a replication role and allows the replica to stream from us.
# NOTE: `trust` auth here is for LOCAL DEVELOPMENT ONLY.
set -euo pipefail

cat >> "${PGDATA}/pg_hba.conf" <<'EOF'
host replication replicator all trust
EOF

psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" <<-'SQL'
  CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator';
  SELECT pg_reload_conf();
SQL
