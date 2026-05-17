#!/usr/bin/env bash
# setup-venv.sh — create $RETRO_DAILY_DATA/.venv and install Python deps.
# Idempotent: if the venv already has all requirements, it does nothing.
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_paths.sh"

VENV="$RETRO_DAILY_DATA/.venv"
REQS="$RETRO_DAILY_HOME/requirements.txt"

if [[ ! -f "$REQS" ]]; then
  echo "setup-venv: requirements.txt not found at $REQS" >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python3" ]]; then
  echo "setup-venv: creating venv at $VENV"
  python3 -m venv "$VENV"
fi

# Skip pip install if the import set already resolves — keeps re-runs fast.
if "$VENV/bin/python3" -c "import numpy, sentence_transformers" 2>/dev/null; then
  echo "setup-venv: deps already installed, nothing to do"
  exit 0
fi

echo "setup-venv: installing Python deps (this is slow the first time — ~500MB of model deps)"
"$VENV/bin/python3" -m pip install --upgrade pip --quiet
"$VENV/bin/python3" -m pip install -r "$REQS" --quiet
echo "setup-venv: done"
