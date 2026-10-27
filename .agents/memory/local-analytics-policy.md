---
name: Local analytics policy
description: Why Chat and Business Analyst prioritize local parsing and deterministic calculations
---

AI Chat and AI Business Analyst must analyze supported uploaded files without
forcing a paid external API dependency. Prefer local Python parsing and
auditable, deterministic calculations. Any external AI processing must be an
explicit opt-in, including provider validation that can incur charges.

**Why:** The user requires accurate Excel, CSV, PDF and JSON analysis without a
paid external API, and explicitly requires existing formulas and deterministic
calculations to remain intact, with cohorts smaller than five suppressed.

**How to apply:** Expand supported questions with bounded, tested operations.
Preserve source attribution and explicit extraction/ambiguity warnings. Never
silently replace a requested measure, ignore a filter, or treat retrieved
document text as a computed metric. Optional language models may assist
phrasing, but are not prerequisites for local calculations. Treat new
seasonality or risk context as additive metadata; regression-test existing
counts, thresholds and severity before shipping. Preserve the `<5` cohort
suppression boundary in every new grouped result.
