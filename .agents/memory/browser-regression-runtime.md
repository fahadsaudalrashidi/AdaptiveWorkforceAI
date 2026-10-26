---
name: Local browser regression runtime
description: The available browser automation options in this imported workspace.
---

For local browser regression checks, use the system Chromium executable with Python's
`websockets` package to speak the Chrome DevTools Protocol when a browser package is
not already available inside `executive-ui`.

**Why:** The imported workspace has Chromium but Node 20 does not expose a global
WebSocket here, and the frontend's nested npm package does not include Playwright.
The package installer also operates from the workspace root, not the nested frontend.

**How to apply:** Check the actual `executive-ui` dependencies before adding a browser
automation package. If they remain unavailable, keep browser checks in Python and
mock API calls through CDP rather than creating a second root npm project.
