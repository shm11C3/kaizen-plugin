#!/usr/bin/env bash
# Advisory history analysis; no target changes or approval gates.
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config
[ "$#" -gt 0 ] || set -- status
exec python3 "$KAIZEN_PLUGIN_ROOT/scripts/strategy.py" --project "$KAIZEN_PROJECT" "$@"
