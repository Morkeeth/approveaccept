#!/bin/sh
set -eu

: "${LEASH_V2_PORT:=8879}"
: "${LEASH_V2_DATA:=$(pwd)/data-guided-demo}"

export LEASH_V2_PORT LEASH_V2_DATA
export LEASH_V2_SUBSTITUTE=1
export APPROVEACCEPT_GUIDED_DEMO=1
export APPROVEACCEPT_PUBLIC_BASE_URL="http://127.0.0.1:$LEASH_V2_PORT"

echo "ApproveAccept guided demo: http://127.0.0.1:$LEASH_V2_PORT"
echo "Local substitute only. No PayPal call and no Face ID proof."
exec python3 -B app.py
