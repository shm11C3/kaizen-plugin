#!/usr/bin/env bash
# Install the resident integrator on the control host (run as root through SSM Run Command).
# Idempotent: keeps an existing integrator.env / integrator.json, never restarts a running integrator.
#   PLUGIN_ROOT      plugin checkout on the host (default /srv/isucon/kaizen-plugin)
#   CLAUDE_VERSION   pin for the native installer (default: latest at install time; then DISABLE_UPDATES applies)
set -euo pipefail
PLUGIN=${PLUGIN_ROOT:-/srv/isucon/kaizen-plugin}
STATE=/srv/isucon/state
HERE="$PLUGIN/team/infra/integrator"
[ -f "$HERE/install.sh" ] || { echo "plugin not found at $PLUGIN" >&2; exit 2; }
id isucon >/dev/null 2>&1 || { echo "run team/infra/bootstrap.sh first" >&2; exit 2; }

install -d -o isucon -g isucon -m 0700 "$STATE" "$STATE/integrator" "$STATE/integrator/dashboard"
[ -f "$STATE/integrator.env" ] || install -o isucon -g isucon -m 0600 "$HERE/integrator.env.example" "$STATE/integrator.env"
[ -f "$STATE/integrator/integrator.json" ] || install -o isucon -g isucon -m 0600 "$PLUGIN/team/templates/integrator.example.json" "$STATE/integrator/integrator.json"

# Claude Code native binary for the isucon user; no Node needed. Pinned by DISABLE_UPDATES in integrator.env.
# runuser -l: a login shell, so HOME is /home/isucon (plain runuser keeps root's HOME and would install under /root).
if ! test -x /home/isucon/.local/bin/claude; then
  runuser -l isucon -c "curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_VERSION:-latest}"
fi
runuser -l isucon -c '~/.local/bin/claude --version'

install -m 0644 "$HERE/kaizen-integrator.service" /etc/systemd/system/kaizen-integrator.service
install -m 0644 "$HERE/kaizen-dashboard.service" /etc/systemd/system/kaizen-dashboard.service
systemctl daemon-reload
systemctl enable --now kaizen-dashboard.service
# The integrator itself is enabled by hand after the target is confirmed (README: 起動).
systemctl is-enabled kaizen-integrator.service >/dev/null 2>&1 || true
echo "installed. next: edit $STATE/integrator.env and $STATE/integrator/integrator.json, run the probe in README, then systemctl enable --now kaizen-integrator.service"
