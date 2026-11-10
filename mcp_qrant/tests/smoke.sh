#!/usr/bin/env bash
set -euo pipefail

QDIR="$(mktemp -d)"
trap 'kill $SRV 2>/dev/null; rm -rf "$QDIR"' EXIT

echo "--- starting server (port 8008, local Qdrant at $QDIR) ---"
MCPQ_PORT=8008 ../.venv/bin/python ../server.py &
SRV=$!
sleep 3

BASE_URL="http://127.0.0.1:8008/mcp"

echo "--- list_providers (expect 10 entries) ---"
curl -s "$BASE_URL" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_providers","arguments":{}}}'
echo

echo "--- store 2 chunks into smoke_col ---"
curl -s "$BASE_URL" \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"store\",\"arguments\":{\"provider\":\"qdrant\",\"connection\":{\"mode\":\"local\",\"path\":\"$QDIR\"},\"collection\":\"smoke_col\",\"items\":[{\"text\":\"the cat sat on the mat\",\"metadata\":{\"src\":\"smoke\"}},{\"text\":\"solar panels convert sunlight into electricity\",\"metadata\":{\"src\":\"smoke\"}}]}}}"
echo

echo "--- find: query 'renewable energy' (expect solar hit) ---"
curl -s "$BASE_URL" \
  -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"find\",\"arguments\":{\"provider\":\"qdrant\",\"connection\":{\"mode\":\"local\",\"path\":\"$QDIR\"},\"collection\":\"smoke_col\",\"query\":\"renewable energy\",\"limit\":1}}}"
echo

echo "--- done ---"
