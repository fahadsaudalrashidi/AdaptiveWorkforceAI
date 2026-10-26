---
name: Imported dependency recovery
description: Compatible dependency recovery and the installer's local Python namespace inference trap.
---

When recovering dependencies omitted from this import's frontend manifest, use
the original lockfile's compatible version ranges as provenance before trying
the latest major release.

**Why:** The imported manifest and lockfile described different dependency sets.
The original lockfile retained chart and animation dependencies that the manifest
omitted. Installing the newest chart major broke existing component types, while
the original compatible range built successfully without component rewrites.

**How to apply:** If another missing package surfaces during import recovery,
inspect its original lockfile entry before selecting a version. Treat a major
upgrade as separate work, not a prerequisite for running the existing app.

## Local Python namespace inference

Review requirement changes after using the package installer. It may infer the
repository's `backend` Python namespace as an unrelated PyPI package and append
`backend` to the root requirements. Do not keep that inferred dependency.

**Why:** The installer's import discovery does not reliably distinguish this
project's own Python package from a third-party distribution.

**How to apply:** Remove a newly inferred `backend` dependency from the manifest
after installation; declare the intended third-party packages in the active
dependency file. Do not resolve the issue by depending on the unrelated package.

## Native dependency scope for publishing

Keep the publishing dependency scope limited to the active web application.
Do not add large native compiler/toolchain dependencies merely to recover a
retired or optional Python feature when supported binary wheels suffice.

**Why:** Publishing can fail after successful application compilation while
uploading an uncached Nix layer. Unused native build tools expand that layer;
changing JavaScript warning thresholds cannot repair a layer-upload failure.
The observed failure did not include a definitive underlying upload error.

**How to apply:** Check actual active dependency requirements before adding
system packages, retain required OCR/font runtimes, and rerun parsing/OCR checks
after changing native dependencies. Diagnose compilation and layer-upload
failures separately; never clear shared Nix storage or user databases as a fix.

## Release dependencies must survive editor-cache exclusions

Treat editor-installed Python packages and shipped release dependencies as
separate environments. Install the complete release dependency set even when
the editor reports it already installed, and verify imports with site-packages
disabled before considering a build ready.

**Why:** pip can report every requirement satisfied from an editor dependency
tree excluded by publishing. Compilation then succeeds but the published
process cannot import its server. A local startup using the editor tree does
not test the shipped dependency set.

**How to apply:** Keep the generated release prefix outside publish exclusions,
use `--ignore-installed` when populating it, and set the runtime import path
explicitly. Keep pip's build-tool import environment until installation ends;
pip itself may be provided by editor tooling. Verify the release in isolation.
