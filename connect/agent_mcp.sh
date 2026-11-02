#!/bin/sh
set -eu
: "${AA_AGENT_ENV_FILE:?Set AA_AGENT_ENV_FILE to the fresh run agent-env.sh}"
case "$AA_AGENT_ENV_FILE" in
  /*) ;;
  *) echo "AA_AGENT_ENV_FILE must be an absolute path" >&2; exit 1 ;;
esac
. "$AA_AGENT_ENV_FILE"
unset APPROVEACCEPT_OWNER_TOKEN
repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec python3 -B "$repo_dir/mcp_server.py"
