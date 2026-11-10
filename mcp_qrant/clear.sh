#!/usr/bin/env bash
# Wipe mcp_qrant's LOCAL Qdrant store (delete all collections/data), then
# restart the server clean. Only valid for local mode. Usage: bash clear.sh
set -u
cd "$(dirname "$0")"

P="${MCPQ_QDRANT_PATH:-$HOME/mcp_qrant_storage}"

echo "1/3  Stopping mcp_qrant (:8008)…"
lsof -ti tcp:8008 2>/dev/null | xargs kill 2>/dev/null || true
sleep 2

echo "2/3  Deleting the local Qdrant store at $P …"
rm -rf "$P"

echo "3/3  Restarting clean…"
exec ./run.sh
