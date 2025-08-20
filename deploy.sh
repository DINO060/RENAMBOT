#!/usr/bin/env bash
set -euo pipefail

# ===== Config =====
APP_DIR="/home/pdfbot/apps/renambot"
PY="${APP_DIR}/venv/bin/python"
PIP="${APP_DIR}/venv/bin/pip"
SERVICE="renambot"
BRANCH="main"   # change to your branch if needed
# ==================

log() { echo -e "\033[1;32m[deploy]\033[0m $*"; }
err() { echo -e "\033[1;31m[error]\033[0m $*" >&2; }

cd "$APP_DIR"

log "Fetching latest code..."
if git rev-parse --git-dir >/dev/null 2>&1; then
  git fetch origin
  git checkout "$BRANCH"
  git pull --rebase origin "$BRANCH"
else
  err "No git repo in $APP_DIR"
  exit 1
fi

log "Ensuring virtualenv..."
if [[ ! -x "$PY" ]]; then
  python3 -m venv venv
fi

log "Installing dependencies..."
"$PIP" install --upgrade pip
"$PIP" install -r requirements.txt

log "Restarting systemd service..."
sudo systemctl restart "$SERVICE"
sudo systemctl status "$SERVICE" --no-pager -n 20 || true

log "Done."
