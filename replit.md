# Running AWI on Replit

The imported structure is retained: `executive-ui/` is the React/TypeScript
frontend, and `backend/` is the Python FastAPI application. Python 3.12 and
Node.js 20 are configured.

## Run

Use **Run** to start the configured frontend and backend workflows:

- **AWI frontend:** `cd executive-ui && npm run dev` (port 5000).
- **AWI backend:** `python -m uvicorn backend.api.main:create_app --factory --host 127.0.0.1 --port 8000`.

Open Preview at `/`. Vite allows Replit's proxy hosts and forwards `/api/*`
to the internal backend. Browser requests use relative paths.
The backend is not separately exposed; its docs are available through the
frontend at `/api/v1/docs` and its health check at `/api/v1/status`.

To reinstall dependencies:

```sh
python -m pip install -r backend/requirements-replit.txt
cd executive-ui && npm ci
```

`backend/requirements-replit.txt` covers the current web application, and the
root `requirements.txt` includes it. `requirements-legacy.txt` preserves
legacy ML and Streamlit packages not used
by the active API; that full install was blocked on a Pillow dependency by the
package firewall. Do not bypass the firewall.

## After task merges

`post-merge.sh` is configured as the automatic post-merge setup hook, with a
five-minute timeout. It installs the active backend requirements, installs the
frontend from its lockfile, and runs the TypeScript/production build. It is
non-interactive and safe to rerun; it does not reset databases, change secrets,
or provision accounts. Replit reconciles and restarts workflows afterward.

## Publishing THRIVE

- Publishing is configured for a **single Reserved VM**, not a static site or
  multiple Autoscale instances. The API retains one-use generated downloads in
  process memory. Those outputs are temporary and must be regenerated after a
  restart; uploaded source files are not retained.
- Build: `bash build-production.sh`. Run: `bash start-production.sh`.
  Builds clear only generated frontend output/caches and the generated Python
  release prefix, reinstall frontend dependencies from the lockfile, and install
  active Python requirements into `.production-python/` with `--ignore-installed`.
  Editor `.pythonlibs/` is excluded from publishing; pip must not consider its
  packages sufficient for the release. `.production-python/` is gitignored but
  must NOT be excluded by `.replitignore`. A build-time isolated import check
  verifies release dependencies without editor/system site-packages. Startup
  replaces the editor PYTHONPATH with this release prefix and the app root.
  Vite splits vendor bundles and loads the larger analyst/accounting screens
  on demand. Its build guard rejects any JavaScript chunk >= 500,000 bytes;
  do not raise the warning threshold to hide an oversized chunk.
  Uvicorn serves the built React UI and all APIs on `0.0.0.0`, port 5000
  (or the platform `PORT`), with one worker. No Vite dev server or second
  publicly exposed backend is used in production.
- The production startup script explicitly selects `AWI_AUTH_BACKEND=postgres`.
  Replit supplies `DATABASE_URL`; shared/production `SESSION_SECRET` must be at
  least 32 characters. Missing/unreachable PostgreSQL never falls back to SQLite.
- Schema source: `backend/db/auth_schema.sql`. Apply schema changes to the
  **development** database only. Replit Publish reviews/applies the development
  schema diff to production; neither the build nor app startup executes DDL.
  Do not select data overwrite when publishing. Development user data is not
  needed or automatically copied to production.
- Existing SQLite accounts remain unchanged for the two development workflows.
  The production account database starts fresh. The initial `admin` account
  uses `AWI_ADMIN_BOOTSTRAP_PASSWORD`, requires a password change at first login,
  and is not reset on restart/republish. Remove the bootstrap secret from the
  production environment after provisioning and keep `SESSION_SECRET` stable.
  To provision a separate administrator without resetting any account, the
  project owner can set `THRIVE_NEW_ADMIN_USERNAME` and provide
  `THRIVE_NEW_ADMIN_PASSWORD` through Secrets, then restart/republish. This is
  startup-only, create-only provisioning with a mandatory first-login password
  change. It never updates existing passwords, elevates existing non-admin
  users, or reactivates disabled users. Remove the provisioning configuration
  after confirming access; do not use this as an ongoing password-reset path.
  Do not copy local SQLite databases or signing keys into the published image;
  `data/` is explicitly excluded from publishing.
- Account provisioning and password recovery use the existing authenticated
  System Admin user-management screen. Keep a second trusted administrator
  before removing the bootstrap secret; there is no anonymous email recovery.
  Manage production database access and backups through Replit's Database tools.
  Managed production databases provide automatic backups and point-in-time
  recovery; verify the available retention window in Database settings before
  onboarding sensitive data. See https://docs.replit.com/features/data-and-storage/data-recovery.
- The public `/` readiness route returns the sign-in UI with HTTP 200; APIs
  retain their authentication and first-password-change checks. Unknown API
  paths remain JSON 404s, not frontend HTML. The app shell and API responses
  are not cached; fingerprinted JS/CSS assets may be cached.
- `/demo` is a public, read-only walkthrough using fixed synthetic local
  examples. It does not call analysis APIs, accept uploads, or save changes.
  Keep real organization data, uploads, and analysis behind the existing
  authentication and authorization checks.
- Sector benchmark contribution remains closed. Seeded sector examples are
  not observed results; see `docs/BENCHMARK_CONTRIBUTION_GOVERNANCE.md` for the
  consent, withdrawal, aggregation, privacy, retention, and audit gates that
  must be implemented before accepting real contributions.
- Regression checks:
  `AWI_TEST_POSTGRES=1 python -m unittest discover -s backend/tests`
  uses disposable schemas in the **development** PostgreSQL database.
  Run `python -m pytest tests/` for the pytest-based API regression suite and
  `node --test tests/analysis_transport.test.mjs` for the browser transport.
- Only the user can trigger Publish. The public production URL is available
  after publishing succeeds; a `.replit.dev` URL is not the production URL.

## Configuration and limitations

- The repository excluded `config/`. Only settings required by the active API
  were restored. Product name/version follow the repository's documented
  `/api/v1/status` response. Legacy ML configuration was not reconstructed.
- Existing development SQLite storage is preserved. Runtime authentication data and the
  fallback local signing key live in ignored `data/`; never commit them.
  Configure `SESSION_SECRET` in Replit Secrets so JWT signing remains stable
  across app restarts and environments. Published releases require PostgreSQL
  and the configured signing secret; they never use `data/` or a generated key.
- PyJWT replaces python-jose, whose latest release was blocked by the package
  firewall. HS256 signing, expiry verification, roles and password rules remain.
- First-boot admin creation requires a strong `AWI_ADMIN_BOOTSTRAP_PASSWORD`
  in Replit Secrets. The admin must change it at first sign-in. The app has a
  sign-in gate, and all `/api/local/*` routes require a valid user with analysis
  permission. HR letters and generated-file downloads are further restricted
  to CHRO, HR Manager, and System Admin users; generated downloads are tied to
  the user who requested them. Authentication cannot be disabled with an
  environment flag. Remove `AWI_ADMIN_BOOTSTRAP_PASSWORD` from Secrets after
  the initial account has been created; keep `SESSION_SECRET` configured.
- Cloud AI is optional and disabled without credentials. To enable it, connect
  a supported provider through the workspace integration flow, configure
  `ANTHROPIC_API_KEY` in Secrets and `ANTHROPIC_MODEL` as an environment setting.
  No local Ollama server is installed. Standard deterministic analytics work
  without a model.
- AI-generated file execution uses Windows Job Objects in the original code.
  It fails closed on Linux when that limiter is unavailable; do not remove the
  guard to make it run. Optional AI slide generation also needs python-pptx.
- Uploaded files are processed in request memory; generated analysis downloads
  are held in process memory and are single-use. Sandbox work files may use
  temporary local storage and are cleaned by the sandbox lifecycle. Verify
  runtime cleanup and storage permissions before public use. Do not commit
  customer uploads, `data/`, database snapshots, or generated reports.
- Do not publish this as a public service for sensitive employee/company data
  until the production secret values, durable storage/backup policy, HTTPS,
  allowed origins, user provisioning, and account recovery process are reviewed
   for the specific deployment.

## Checks

```sh
cd executive-ui && npm run build
```

This runs TypeScript checks and creates the frontend bundle. A large-bundle
warning is non-fatal.

### Local AI Chat / Business Analyst

The chat defaults to local deterministic analytics, without requiring Ollama
or any external API key. Cloud AI is an explicit per-request opt-in; status
polling does not call a paid provider. Ollama remains optional for phrasing
existing registered metric answers, never for calculating arbitrary formulas.

Uploads use the secure ingestion pipeline after local parsing:
- Excel: every non-empty worksheet, with a 50-sheet safety limit.
- CSV and Parquet: tabular ingestion.
- JSON: nested record objects flattened; independent record collections remain
  separate, named sources.
- PDF: ruled/borderless native tables plus page-cited text and offline OCR
  for Arabic/English scans, including image-bearing searchable pages.
  Replit's Nix `tesseract` package supplies both `ara` and `eng` language data;
  PDFium rasterizes locally at 200 DPI. No OCR network call, model, paid API,
  or runtime language download is used. Missing language data fails explicitly.
  Scanned passages remain quotations, not inferred tables. Before calculating
  financial figures, provide verified CSV/Excel or a verified searchable PDF.
  All scanned sources require numeric review (even high token confidence does
  not prove column alignment), preventing partial totals from native tables
  in mixed documents. Page confidence and counts of uncertain numeric tokens
  are shown without returning raw token metadata. Numbers below 85% token
  confidence, or pages below 70% mean confidence, produce explicit warnings.
  Every native table and text source is governance-scanned; a rejected source
  rejects its sibling PDF sources. Embedded identifier patterns in PDF text
  are blocked, not exposed as quotations.
  Local PDF limits: 25 MB, 20 pages, 12 megapixels per rendered page, two
  simultaneous workers, 15 seconds per OCR page and 45 seconds per document.
  Workers have 1.5 GiB address-space, CPU, file-size and descriptor limits;
  process groups are terminated and temporary files removed on completion or
  failure. OCR progress records contain only stage/page metadata, are
  owner-restricted, bounded to 100 entries, and expire after ten minutes.
  The in-memory progress store assumes the existing single API process;
  do not add multiple server workers without a shared owner-aware store.

Direct column queries support totals, averages, counts, min/max, grouped
aggregations and monthly trends. Ambiguous sources/measures, personal-data
fields and unsupported filters must not silently produce a guessed result.

Explicit local filters use a restricted grammar, not generated code or SQL:
`total "Sales" where "Region" = "West" and "Date" >= "2025-01-01"`.
Use `average "Sales"` or `count records` for other aggregates. Compare two
cohorts with `compare total "Sales" where "Region" = "West" versus "Region" = "East"`.
With multiple files/sheets add `from "exact displayed source name"` before
`where`. Column names must match exactly (case-insensitive); category values
must match exactly including case. Operators are `= != > >= < <=`; only `and`
is supported within a cohort, with at most eight filters. Dates must be ISO
YYYY-MM-DD; mixed currencies, ambiguous `$`, locale-dependent numbers and
formulas require clarification, not inferred conversion. Missing filter
values never match (including `!=`); missing measure values do not count as
zero. Empty totals/averages have no value, while empty record counts are zero.
Numeric inputs, thresholds and results are bounded to magnitude `2^53 - 1`
to reject unsafe large-number calculations rather than silently overflow.
Responses preserve each cohort's source, filters, counts, and values; cohorts
may overlap and their counts must not be added.
Document excerpts are context evidence, not computed business metrics.

Run the active local-file/API tests without extra test dependencies:

```sh
python -m unittest discover -s backend/tests -p 'test_local_file_analytics.py' -v
python -m unittest discover -s backend/tests -p 'test_local_pdf_ocr.py' -v
```

`python -m pytest -q` includes both the active API and local-file suites.
With the frontend running, `python tests/pdf_ocr_frontend_regression.py`
checks actual page-progress rendering, confidence/warnings, and polling cleanup
in Chromium using browser-only mocked sessions and a response generated through
the real offline API. It does not create accounts or weaken application auth.

Setup verification also exercised real CSV uploads through the preview proxy
for finance, accounting, inventory, contract expiry and GOSI; the manual Zakat
calculator; and JWT access/refresh tokens, invalid-token rejection and bcrypt
password verification. The dashboard was visually checked in Preview.
