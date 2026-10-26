---
name: Local analytics policy
description: Why Chat and Business Analyst prioritize local parsing and deterministic calculations
---

AI Chat and AI Business Analyst must analyze supported uploaded files without
forcing a paid external API dependency. Prefer local Python parsing and
auditable, deterministic calculations. Any external AI processing must be an
explicit opt-in, including provider validation that can incur charges.

**Why:** The user requested high accuracy across Excel, CSV, PDF and JSON
without requiring a paid external API. A model-generated number is not evidence
that a calculation is correct.

**How to apply:** Expand supported questions with bounded, tested operations.
Preserve source attribution and explicit extraction/ambiguity warnings. Never
silently replace a requested measure, ignore a filter, or treat retrieved
document text as a computed metric. Optional language models may assist
phrasing, but are not prerequisites for local calculations.
