#!/usr/bin/env bash
set -euo pipefail
ROOT="$(mktemp -d)"
printf 'hello alpha' > "$ROOT/a.txt"
mkdir -p "$ROOT/sub"
printf 'deep charlie' > "$ROOT/sub/c.txt"

LANGFS_ROOTS="$ROOT" ../.venv/bin/python ../server.py &
SRV=$!
sleep 2
trap 'kill $SRV' EXIT

echo "--- list_providers ---"
curl -s localhost:8077/ -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_providers","arguments":{}}}'
echo; echo "--- read_next #1 ---"
curl -s localhost:8077/ -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"read_next\",\"arguments\":{\"provider\":\"local\",\"path\":\"$ROOT\",\"client_id\":\"u:smoke\"}}}"
echo; echo "--- read_next #2 ---"
curl -s localhost:8077/ -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"read_next\",\"arguments\":{\"provider\":\"local\",\"path\":\"$ROOT\",\"client_id\":\"u:smoke\"}}}"
echo; echo "--- read_next #3 (expect done) ---"
curl -s localhost:8077/ -H 'content-type: application/json' \
  -d "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"read_next\",\"arguments\":{\"provider\":\"local\",\"path\":\"$ROOT\",\"client_id\":\"u:smoke\"}}}"
echo
