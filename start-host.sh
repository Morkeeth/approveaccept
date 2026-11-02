#!/bin/sh
set -eu

: "${PORT:=8080}"
: "${AA_BACKEND_PORT:=8752}"
: "${AA_DATA_DIR:=/tmp/approveaccept-data}"
: "${APPROVEACCEPT_PUBLIC_BASE_URL:=}"

mkdir -p "$AA_DATA_DIR"
export LEASH_V2_PORT="$AA_BACKEND_PORT"
export LEASH_V2_DATA="$AA_DATA_DIR"
export AA_UPSTREAM="http://127.0.0.1:$AA_BACKEND_PORT"
export AA_DESIGN_PORT="$PORT"
export AA_DESIGN_HOST="${AA_DESIGN_HOST:-0.0.0.0}"
if [ -z "${APPROVEACCEPT_PUBLIC_BASE_URL:-}" ] && [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
  export APPROVEACCEPT_PUBLIC_BASE_URL="$RENDER_EXTERNAL_URL"
fi
if [ -z "${APPROVEACCEPT_PASSKEY_ORIGIN:-}" ] && [ "${APPROVEACCEPT_PUBLIC_BASE_URL#https://}" != "${APPROVEACCEPT_PUBLIC_BASE_URL:-}" ]; then
  export APPROVEACCEPT_PASSKEY_ORIGIN="$APPROVEACCEPT_PUBLIC_BASE_URL"
fi

python3 -B app.py &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM

i=0
until python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$AA_BACKEND_PORT/health', timeout=1)" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "ApproveAccept backend did not become healthy" >&2
    exit 1
  fi
  sleep 1
done

exec python3 -B design/server.py
