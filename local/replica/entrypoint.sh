#!/usr/bin/env bash
# Custom entrypoint for the standby: on first boot, clone the primary with
# pg_basebackup (which writes standby.signal + primary_conninfo via -R), then
# start Postgres as a streaming hot standby.
set -euo pipefail

DATA="/var/lib/postgresql/data"

if [ ! -s "${DATA}/PG_VERSION" ]; then
  echo "[replica] cloning primary ${PRIMARY_HOST} via pg_basebackup..."
  mkdir -p "${DATA}"
  chown -R postgres:postgres "${DATA}"
  until gosu postgres pg_basebackup \
      -h "${PRIMARY_HOST}" -p 5432 -U "${REPL_USER}" \
      -D "${DATA}" -Fp -Xs -P -R -w; do
    echo "[replica] primary not ready yet, retrying in 2s..."
    sleep 2
  done
  chmod 0700 "${DATA}"
  echo "[replica] base backup complete; starting standby."
fi

# Hand off to the stock entrypoint, which detects existing data and just starts.
exec docker-entrypoint.sh postgres
