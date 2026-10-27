---
name: Public demo safety
description: Keep the public THRIVE demo isolated to fixed synthetic data while real workspace APIs remain authenticated.
---

**Rule:** The public demo is a separate synthetic-data preview. It must not accept real uploads, query company datasets, or call authenticated analysis APIs. Keep the sign-in gate and backend authorization in place for the real workspace.

**Why:** The user chose a public synthetic-data demo instead of disabling authentication, to let visitors evaluate the experience without exposing HR or finance data.

**How to apply:** Add demo features only if they stay client-side and clearly label illustrative figures and simulated checks. Keep a clear sign-in path for the private workspace; do not share its authenticated pages or API calls with the public route.
