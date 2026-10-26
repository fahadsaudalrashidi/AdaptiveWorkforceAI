---
name: OCR numeric trust
description: Why OCR output is evidence rather than a verified financial table
---

Keep scanned passages usable as page-cited evidence, but require a verified
tabular source before financial calculations, including mixed searchable/scanned
PDFs. Do not treat a high OCR confidence score as proof of numeric correctness.

**Why:** Real Arabic scan testing recognized labels while changing Arabic-Indic
digits. English ambiguous letter/digit shapes were also recognized as plausible
numbers. Confidence alone cannot prove table alignment or that native tables
include the scanned portions of a report.

**How to apply:** Preserve this conservative trust boundary across local queries,
registered domain analyzers, optional cloud tools and exports. Any future
editable OCR/table verification feature must explicitly establish which values
and columns were verified rather than clearing a flag for an entire document.
