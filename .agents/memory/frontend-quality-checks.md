---
name: Frontend quality checks
description: Keep React hook linting active and fix hook-order or dependency findings instead of suppressing them.
---

Keep the frontend lint configuration present and enforce both React hook ordering and effect dependency rules. When hooks are reported after an early return, move them above the return or split the conditional rendering into a child component rather than disabling the rule.

**Why:** Enabling the previously missing lint configuration surfaced real conditional hook calls and stale effect dependencies that TypeScript compilation did not catch.

**How to apply:** Run the frontend lint command after UI changes. Keep `react-hooks/rules-of-hooks` and `react-hooks/exhaustive-deps` enforced, and treat parser/compiler compatibility warnings as a separate toolchain issue rather than hiding them.
