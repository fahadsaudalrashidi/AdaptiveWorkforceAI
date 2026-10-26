---
name: Vite cache after production builds
description: Prevent a stale optimized-dependency cache from leaving the dev preview blank after production dependency installation.
---

After running the production build script, restart the AWI frontend before relying on the preview. The script installs frontend packages, and the running Vite process can otherwise return `504 (Outdated Optimize Dep)` for the client entry and render a blank page.

**Why:** A successful production compile does not guarantee the already-running dev server's dependency optimizer still matches the refreshed `node_modules`.

**How to apply:** If a preview goes blank after the production build script, restart the frontend workflow once and verify the browser console and login page before concluding the app is broken.
