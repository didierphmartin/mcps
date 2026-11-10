#!/usr/bin/env bash
# smoke_cloud.sh — guarded live S3 smoke test for langfs
# Skips cleanly (exit 0) unless the three required env vars are set.
# Usage:
#   LANGFS_SMOKE_S3_BUCKET=my-bucket \
#   AWS_ACCESS_KEY_ID=... \
#   AWS_SECRET_ACCESS_KEY=... \
#   ./tests/smoke_cloud.sh

set -euo pipefail

# ── guard ──────────────────────────────────────────────────────────────────────
if [[ -z "${LANGFS_SMOKE_S3_BUCKET:-}" || \
      -z "${AWS_ACCESS_KEY_ID:-}"       || \
      -z "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  echo "SKIP — set LANGFS_SMOKE_S3_BUCKET + AWS creds to run"
  exit 0
fi

BUCKET="$LANGFS_SMOKE_S3_BUCKET"
REGION="${AWS_DEFAULT_REGION:-us-east-1}"
CLIENT_ID="u:smoke-s3"

# ── start server ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/server.py" &
SRV=$!
trap 'kill $SRV 2>/dev/null; wait $SRV 2>/dev/null || true' EXIT

echo "Started server (pid $SRV), waiting for it to be ready..."
sleep 2

BASE_URL="http://127.0.0.1:8077"

# ── helper ────────────────────────────────────────────────────────────────────
call() {
  curl -sf "$BASE_URL/" \
    -H 'content-type: application/json' \
    -d "$1"
}

# ── test_connection ────────────────────────────────────────────────────────────
echo
echo "--- test_connection ---"
TC_PAYLOAD=$(cat <<EOF
{
  "jsonrpc":"2.0","id":1,"method":"tools/call",
  "params":{
    "name":"test_connection",
    "arguments":{
      "provider":"s3",
      "scope":{"bucket":"$BUCKET"},
      "credentials":{
        "access_key":"$AWS_ACCESS_KEY_ID",
        "secret_key":"$AWS_SECRET_ACCESS_KEY",
        "region":"$REGION"
      }
    }
  }
}
EOF
)
TC_RESP=$(call "$TC_PAYLOAD")
echo "$TC_RESP"

# assert ok:true inside the tool result text
if ! echo "$TC_RESP" | grep -q '"ok":true'; then
  echo "FAIL: test_connection did not return ok:true"
  exit 1
fi
echo "  ✓ test_connection ok"

# ── read_next #1 ───────────────────────────────────────────────────────────────
echo
echo "--- read_next #1 ---"
RN1_PAYLOAD=$(cat <<EOF
{
  "jsonrpc":"2.0","id":2,"method":"tools/call",
  "params":{
    "name":"read_next",
    "arguments":{
      "provider":"s3",
      "scope":{"bucket":"$BUCKET"},
      "credentials":{
        "access_key":"$AWS_ACCESS_KEY_ID",
        "secret_key":"$AWS_SECRET_ACCESS_KEY",
        "region":"$REGION"
      },
      "client_id":"$CLIENT_ID"
    }
  }
}
EOF
)
RN1_RESP=$(call "$RN1_PAYLOAD")
echo "$RN1_RESP"

# ── read_next #2 ───────────────────────────────────────────────────────────────
echo
echo "--- read_next #2 ---"
RN2_PAYLOAD=$(cat <<EOF
{
  "jsonrpc":"2.0","id":3,"method":"tools/call",
  "params":{
    "name":"read_next",
    "arguments":{
      "provider":"s3",
      "scope":{"bucket":"$BUCKET"},
      "credentials":{
        "access_key":"$AWS_ACCESS_KEY_ID",
        "secret_key":"$AWS_SECRET_ACCESS_KEY",
        "region":"$REGION"
      },
      "client_id":"$CLIENT_ID"
    }
  }
}
EOF
)
RN2_RESP=$(call "$RN2_PAYLOAD")
echo "$RN2_RESP"
echo
echo "S3 smoke complete."
