---
name: Local extraction delivery
description: Why live extraction uses the active request rather than introducing a shared progress service
---

Keep ordinary local extraction request-bound unless resumable background jobs
are explicitly needed. Do not introduce a mandatory shared database, queue or
paid service solely to display live progress.

**Why:** The platform must remain usable locally without a paid provider.
Worker-local polling cannot reliably find another server's progress, while a
single authenticated stream stays with the worker doing the extraction.

**How to apply:** Treat a lost connection as an incomplete request and require
a retry, not a partial successful answer. Do not promise resumability or durable
progress history. If those become requirements, design a persistent,
owner-scoped job store rather than extending process-local dictionaries.

Retain the established JSON analysis API when adding a newer transport.

**Why:** The user encountered “Not Found” after the branded frontend started
using a newer streaming route. Frontend hot reload and backend worker updates
can occur independently, so client and server versions may temporarily differ.

**How to apply:** Negotiate transport capabilities and fall back only for a
missing/unsupported route. Authentication, validation, failed processing and
interrupted streams must remain explicit errors, not automatic upload retries.
