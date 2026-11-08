#!/bin/sh
# Starts the ApproveAccept MCP server for .mcp.json.
# With AA_AGENT_ENV_FILE set, it reads a prepared sandbox run (connect/prepare_fresh_run.py).
# Without it, it connects to the local demo (./journey.sh --no-paypal) on http://127.0.0.1:8780
# and uses APPROVEACCEPT_AGENT_TOKEN from your environment, if you set one.
set -eu
if [ -n "${AA_AGENT_ENV_FILE:-}" ]; then
  case "$AA_AGENT_ENV_FILE" in
    /*) ;;
    *) echo "AA_AGENT_ENV_FILE must be an absolute path" >&2; exit 1 ;;
  esac
  . "$AA_AGENT_ENV_FILE"
else
  AA_URL="${AA_URL:-http://127.0.0.1:8780}"
  export AA_URL
  if [ -z "${APPROVEACCEPT_AGENT_TOKEN:-}" ]; then
    echo "ApproveAccept: no agent key yet. Start ./journey.sh --no-paypal, add an agent on the Agents tab of /inbox, then set APPROVEACCEPT_AGENT_TOKEN to its key." >&2
  fi
fi
unset APPROVEACCEPT_OWNER_TOKEN
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 -B "$repo_dir/mcp_server.py"
