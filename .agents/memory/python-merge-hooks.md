---
name: Python in merge hooks
description: Environment difference between editor shell installs and automated merge hooks.
---

Python dependency installation in automated merge hooks must explicitly use a
workspace-local prefix and make its site-packages available to Python.

**Why:** The editor's shell could install project dependencies normally, but the
automated hook did not inherit that pip destination and tried to modify the
immutable Nix Python installation, failing with PEP 668.

**How to apply:** Preserve the explicit project-local destination when modifying
setup hooks. Do not bypass the externally-managed protection or introduce a
virtual environment to work around it.
