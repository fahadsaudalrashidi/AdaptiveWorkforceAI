"""Same-origin production hosting for the compiled THRIVE UI and FastAPI API."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_DIST = Path(__file__).resolve().parents[2] / "executive-ui" / "dist"


def create_app():
    # Check before importing auth: no ephemeral signing key or SQLite fallback
    # is permitted in a published release.
    if len(os.environ.get("SESSION_SECRET", "")) < 32:
        raise RuntimeError("Production requires SESSION_SECRET with at least 32 characters.")
    from backend.core.auth_database import auth_backend, verify_postgres_schema
    if auth_backend() != "postgres":
        raise RuntimeError("Production requires AWI_AUTH_BACKEND=postgres.")
    if not (_DIST / "index.html").is_file():
        raise RuntimeError("The production frontend is missing. Run build-production.sh.")
    verify_postgres_schema()

    from backend.api.main import create_app as create_api_app
    from backend.core.local_auth import get_auth_manager
    app = create_api_app()
    # An empty database without a bootstrap secret would serve a sign-in screen
    # that nobody can access. Do not silently publish that state.
    manager = get_auth_manager()
    if not manager.list_users():
        raise RuntimeError("Production needs an active account. Configure AWI_ADMIN_BOOTSTRAP_PASSWORD for first boot.")

    @app.middleware("http")
    async def release_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Hashed bundles may be cached; API responses and the app shell may not.
        response.headers["Cache-Control"] = (
            "public, max-age=31536000, immutable"
            if request.url.path.startswith("/assets/") and response.status_code == 200
            else "no-store"
        )
        return response

    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="release-assets")
    app.mount("/brand", StaticFiles(directory=_DIST / "brand"), name="release-brand")

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontend(path: str):
        # Never turn an absent API endpoint or missing asset into an HTML 200.
        if path == "api" or path.startswith("api/") or (path != "index.html" and "." in path):
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(_DIST / "index.html", media_type="text/html")

    return app
