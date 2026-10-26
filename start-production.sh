#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
python_site=".production-python/lib/python$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages"
if [[ ! -d "$python_site/uvicorn" ]]; then
  echo "Production Python dependencies are missing. Run build-production.sh before publishing." >&2
  exit 1
fi
export PYTHONPATH="$PWD/$python_site:$PWD"
export PYTHONNOUSERSITE=1
export AWI_AUTH_BACKEND=postgres
# Exactly one worker: progress and one-use generated downloads are request-local
# or process-local. Accounts and session revocations are durable in PostgreSQL.
exec python -m uvicorn backend.api.production:create_app --factory \
  --host 0.0.0.0 --port "${PORT:-5000}" --workers 1 --no-server-header
