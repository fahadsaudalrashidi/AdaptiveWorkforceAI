"""
FastAPI Backend — Adaptive Workforce Intelligence Enterprise Platform API

Real endpoints:
  GET  /api/v1/status              — Health check
  *    /api/v1/auth/*              — Authentication (backend/api/auth_routes.py)
  *    /api/local/*                — Every real analysis/calculator module
                                      (backend/api/local_analysis_routes.py)

Phase 39: the entire "V1" pipeline this docstring previously listed here
(POST /api/v1/upload, POST /api/v1/analyse, GET /api/v1/session/{sid},
POST /api/v1/export/{sid}/csv, and the theory-construct/ML-prediction chain
that fed them — TheoryAwareColumnMapper, compute_constructs, FeatureFactory,
ModelInputContract, TemporalValidationGuard, MLRouter, risk_intelligence,
plus the co-located, equally-unreachable biosignal branch) was removed.
Confirmed dead-from-the-frontend all session: executive-ui never calls any
/api/v1/upload, /api/v1/analyse, /api/v1/session, or /api/v1/export route —
only /api/local/*. See PHASE_39_PREDICTION_REMOVAL_AND_ENTERPRISE_REBRAND_REPORT.md.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

# ── FastAPI guard ────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

# ── add project root to sys.path ─────────────────────────────────────────────
# --- add project root to sys.path ---
_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config.settings import API_HOST, API_PORT, API_PREFIX, PLATFORM_NAME, PLATFORM_VERSION
from backend.api.auth_routes import router as auth_router
from backend.core.local_auth import get_auth_manager
from backend.api.local_analysis_routes import create_local_analysis_router
from backend.api.data_hub_routes import create_data_hub_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# APP CREATION (guarded)
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> Any:
    if not _HAS_FASTAPI:
        raise ImportError("FastAPI is not installed. Run: pip install fastapi uvicorn")

    app = FastAPI(
        title     = PLATFORM_NAME,
        version   = PLATFORM_VERSION,
        docs_url  = f"{API_PREFIX}/docs",
        openapi_url = f"{API_PREFIX}/openapi.json",
    )
    # CORS: restrict to localhost by default for on-prem deployments.
    # Set AWI_CORS_ORIGINS env var (comma-separated) to override.
    import os as _os
    _cors_env = _os.environ.get("AWI_CORS_ORIGINS", "")
    _cors_origins = (
        [o.strip() for o in _cors_env.split(",") if o.strip()]
        if _cors_env
        else ["http://localhost:3000", "http://localhost:8501", "http://127.0.0.1:3000", "http://127.0.0.1:8501"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins  = _cors_origins,
        allow_methods  = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers  = ["Authorization", "Content-Type", "Accept"],
        expose_headers = ["X-HR-Letters-Summary"],
        allow_credentials = True,
    )

    # ── AUTH ROUTES (Phase 30.1) ──────────────────────────────────────────────
    app.include_router(auth_router)

    # ── LOCAL ANALYSIS (authenticated, single organisation) ─────────────────
    app.include_router(create_local_analysis_router())
    app.include_router(create_data_hub_router())

    # ── FIRST-BOOT: create admin only from the Replit Secrets value ────────────
    _bootstrap_password = _os.environ.get("AWI_ADMIN_BOOTSTRAP_PASSWORD", "")
    if _bootstrap_password:
        get_auth_manager().bootstrap_admin(initial_password=_bootstrap_password)

    # Owner-only startup configuration, never an anonymous recovery endpoint.
    # The password is read by the app from Secrets and is never logged.
    _additional_username = _os.environ.get("THRIVE_NEW_ADMIN_USERNAME", "").strip()
    if _additional_username:
        _additional_password = _os.environ.get("THRIVE_NEW_ADMIN_PASSWORD", "")
        if not _additional_password:
            raise RuntimeError("THRIVE_NEW_ADMIN_PASSWORD is required to provision the configured administrator.")
        get_auth_manager().provision_additional_admin(_additional_username, _additional_password)

    # ── HEALTH CHECK ─────────────────────────────────────────────────────────
    @app.get(f"{API_PREFIX}/status")
    def status():
        return {
            "status":   "operational",
            "platform": PLATFORM_NAME,
            "version":  PLATFORM_VERSION,
        }

    return app


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not _HAS_FASTAPI:
        print("FastAPI not installed. Run: pip install fastapi uvicorn python-multipart")
    else:
        app = create_app()
        uvicorn.run(app, host=API_HOST, port=API_PORT, reload=False)
