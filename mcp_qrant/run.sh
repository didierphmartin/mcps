#!/usr/bin/env bash
# Start mcp_qrant with its OWN Qdrant (the server owns the DB, like the old
# qdrant double; the gpt node's Connection box is then optional for local Qdrant).
# Override the location with MCPQ_QDRANT_PATH / _MODE / _URL / _API_KEY.
set -u
cd "$(dirname "$0")"

# Load local config/secrets if present (gitignored) — DSN, OpenAI key, paths —
# so they survive restarts without being retyped. Edit .env to change them.
if [ -f .env ]; then
    set -a; . ./.env; set +a
fi

export MCPQ_QDRANT_MODE="${MCPQ_QDRANT_MODE:-local}"
export MCPQ_QDRANT_PATH="${MCPQ_QDRANT_PATH:-$HOME/mcp_qrant_storage}"

# Free :8008 if a previous instance is still bound (env-less or stale).
lsof -ti tcp:8008 2>/dev/null | xargs kill 2>/dev/null || true
sleep 2

nohup .venv/bin/python server.py > /tmp/mcp_qrant.log 2>&1 &
sleep 4
echo "mcp_qrant up on http://127.0.0.1:8008/mcp"
echo "  Qdrant:   mode=$MCPQ_QDRANT_MODE path=$MCPQ_QDRANT_PATH"
echo "  pgvector: dsn=${MCPQ_PGVECTOR_DSN:+set} openai_key=${MCPQ_OPENAI_API_KEY:+set} embedding=${MCPQ_EMBEDDING:-openai:text-embedding-3-small}"
