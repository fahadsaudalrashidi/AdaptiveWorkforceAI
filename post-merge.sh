#!/usr/bin/env bash
# Reconcile dependencies and rebuild after isolated task changes are merged.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

# Hooks do not inherit the editor's pip destination. Install into the existing
# project-local package prefix, never Nix's immutable system Python.
python_site=".pythonlibs/lib/python$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages"
export PYTHONPATH="$PWD/$python_site${PYTHONPATH:+:$PYTHONPATH}"
python -m pip install --disable-pip-version-check --no-input \
  --prefix "$PWD/.pythonlibs" \
  -r backend/requirements-replit.txt
npm --prefix executive-ui ci --no-audit --no-fund
npm --prefix executive-ui run build

# Replit reconciles/restarts workflows after this script succeeds.
# Do not start servers, reset databases, or provision accounts here.
