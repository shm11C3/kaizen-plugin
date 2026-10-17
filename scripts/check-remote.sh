#!/usr/bin/env bash
# Run an immutable Go test fixture in a temporary directory on the owned app host.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
[ "${KAIZEN_TEAM_MODE:-}" = 1 ] || die "check-remote requires the owned team target.py action"
export APP_HOST SSH_CONFIG LOCAL_SYNC_PATHS
exec python3 "$KAIZEN_PLUGIN_ROOT/scripts/check_remote_go.py" "$@"
