#!/bin/sh
# Start the one-screen journey with the keys saved by step 0 (python3 connect/byok.py).
# Sandbox only. Keys stay in the env file; this script never prints them.
set -eu
AA_HOME="${APPROVEACCEPT_HOME:-$HOME/.config/approveaccept}"
ENV_FILE="$AA_HOME/sandbox.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "No keys yet. Run step 0 first: python3 connect/byok.py" >&2
  exit 1
fi
# shellcheck disable=SC1090
. "$ENV_FILE"
export APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET APPROVEACCEPT_PAYPAL_SANDBOX_MERCHANT_ID
export APPROVEACCEPT_OWNER_TOKEN APPROVEACCEPT_AGENT_TOKEN APPROVEACCEPT_AGENT_NAME
[ -n "${APPROVEACCEPT_ANTHROPIC_API_KEY:-}" ] && export APPROVEACCEPT_ANTHROPIC_API_KEY
unset LEASH_V2_SUBSTITUTE
: "${AA_PORT:=8780}"
export LEASH_V2_PORT="$AA_PORT"
export LEASH_V2_DATA="${AA_DATA_DIR:-$AA_HOME/data}"
mkdir -p "$LEASH_V2_DATA"
echo "ApproveAccept journey: http://127.0.0.1:$AA_PORT/journey  (PayPal Sandbox, your own keys)"
echo "Sign in with the owner key from step 0. Stop with Ctrl-C."
exec python3 -B app.py
