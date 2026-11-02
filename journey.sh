#!/bin/sh
# Start ApproveAccept on http://127.0.0.1:8780.
#   ./journey.sh              PayPal Sandbox with the keys saved by step 0 (python3 connect/byok.py); keys are never printed.
#   ./journey.sh --no-paypal  no account needed: a labelled local stand-in for PayPal.
set -eu
AA_HOME="${APPROVEACCEPT_HOME:-$HOME/.config/approveaccept}"
: "${AA_PORT:=8780}"
if [ "${1:-}" = "--no-paypal" ]; then
  # Same app, same port and pages, with a labelled local stand-in for PayPal. No account, no keys, no network payment.
  umask 077
  mkdir -p "$AA_HOME"
  KEY_FILE="$AA_HOME/no-paypal.env"
  if [ ! -f "$KEY_FILE" ]; then
    printf "export APPROVEACCEPT_OWNER_TOKEN='%s'\n" "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" > "$KEY_FILE"
  fi
  # shellcheck disable=SC1090
  . "$KEY_FILE"
  export APPROVEACCEPT_OWNER_TOKEN LEASH_V2_SUBSTITUTE=1 LEASH_V2_PORT="$AA_PORT"
  export LEASH_V2_DATA="${AA_DATA_DIR:-$AA_HOME/data-no-paypal}"
  mkdir -p "$LEASH_V2_DATA"
  echo "ApproveAccept, no-PayPal mode (local stand-in, every ID starts with SUB): http://127.0.0.1:$AA_PORT/inbox"
  echo "Owner key for sign-in: $APPROVEACCEPT_OWNER_TOKEN"
  echo "(Local demo key, also saved in $KEY_FILE.) Stop with Ctrl-C."
  exec python3 -B app.py
fi
ENV_FILE="$AA_HOME/sandbox.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "No PayPal keys yet. Either run step 0 (python3 connect/byok.py), or try it without PayPal: ./journey.sh --no-paypal" >&2
  exit 1
fi
# shellcheck disable=SC1090
. "$ENV_FILE"
export APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET APPROVEACCEPT_PAYPAL_SANDBOX_MERCHANT_ID
export APPROVEACCEPT_OWNER_TOKEN APPROVEACCEPT_AGENT_TOKEN APPROVEACCEPT_AGENT_NAME
[ -n "${APPROVEACCEPT_ANTHROPIC_API_KEY:-}" ] && export APPROVEACCEPT_ANTHROPIC_API_KEY
unset LEASH_V2_SUBSTITUTE
export LEASH_V2_PORT="$AA_PORT"
export LEASH_V2_DATA="${AA_DATA_DIR:-$AA_HOME/data}"
mkdir -p "$LEASH_V2_DATA"
echo "ApproveAccept, PayPal Sandbox with your own keys: http://127.0.0.1:$AA_PORT/inbox"
echo "Sign in with the owner key from step 0. Stop with Ctrl-C."
exec python3 -B app.py
