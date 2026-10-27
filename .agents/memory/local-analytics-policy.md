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

For conversational analysis, reuse only a previously successful local tabular
question while the exact same in-memory file objects remain selected. Keep this
context request-bound, and never send it in explicit cloud mode or persist it.
Split multi-intent requests only when every clause contains an independent
analytical intent; calculate clauses separately and return no partial results
if any clause is unclear. Fuzzy column matches may be suggested but must never
be selected automatically.

**Why:** Reusing context across changed files or externally processed requests
can answer against the wrong data or disclose extra user-entered context.
Automatic fuzzy mappings can silently change the requested measure, while
partial multi-intent answers can be mistaken for complete totals.

**How to apply:** Bind follow-up context to the current file selection and
local-only mode. Keep parsing bounded and auditable, require user confirmation
for suggested schema mappings, and test ambiguous clauses as fail-closed.
