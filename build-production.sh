#!/usr/bin/env bash
# Compile the release; never provision users or mutate a database in a build.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
release_prefix="$PWD/.production-python"
python_site="$release_prefix/lib/python$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/site-packages"
# Never let pip satisfy the release from editor packages excluded from the image.
# This generated prefix is gitignored, but deliberately NOT .replitignored.
rm -rf "$release_prefix"
# Only generated frontend output is removed; never delete data or credentials.
rm -rf executive-ui/dist executive-ui/node_modules/.vite
rm -f executive-ui/tsconfig.tsbuildinfo
python -m pip install --disable-pip-version-check --no-input --no-cache-dir \
  --ignore-installed --prefix "$release_prefix" -r backend/requirements-replit.txt
# The build's pip may itself live in the editor tooling. Isolate runtime
# imports only AFTER it has installed the complete release dependency set.
export PYTHONPATH="$python_site:$PWD"
export PYTHONNOUSERSITE=1
# -S disables editor/system site-packages: fail this build, not production
# startup, if any key runtime dependency is absent from the release prefix.
python -S - <<'PY'
import uvicorn, fastapi, psycopg, pandas, openpyxl, pdfplumber, pypdfium2, fpdf, uharfbuzz
from pathlib import Path
prefix = Path(".production-python").resolve()
for module in (uvicorn, fastapi, psycopg, pandas, openpyxl, pdfplumber, pypdfium2, fpdf, uharfbuzz):
    if not Path(module.__file__).resolve().is_relative_to(prefix):
        raise RuntimeError(f"Release dependency escaped production prefix: {module.__name__}")
print("Isolated production Python dependency check passed.")
PY
npm --prefix executive-ui ci --include=dev --no-audit --no-fund
npm --prefix executive-ui run build
