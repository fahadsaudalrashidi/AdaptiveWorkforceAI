"""Catch editor-only dependency reuse before a published release crash-loops."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReleaseScriptTests(unittest.TestCase):
    def test_build_installs_every_dependency_even_when_editor_has_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy(ROOT / "build-production.sh", root)
            # Mock only the tool entrypoint: never install packages in this test.
            python = root / "python"
            python.write_text(
                '#!/bin/bash\n'
                'if [[ "$1" == "-c" ]]; then echo 3.12; exit 0; fi\n'
                'printf "%s\\n" "$@" > "$CAPTURE_ARGS"\n'
                'exit 37\n'
            )
            python.chmod(0o755)
            capture = root / "args"
            result = subprocess.run(
                ["bash", str(root / "build-production.sh")],
                env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                     "CAPTURE_ARGS": str(capture)},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 37)  # fail early on install errors
            args = capture.read_text().splitlines()
            self.assertIn("--ignore-installed", args)
            self.assertEqual(args[args.index("--prefix") + 1], str(root / ".production-python"))
            self.assertNotIn(str(root / ".pythonlibs"), args)

    def test_startup_rejects_missing_release_even_if_editor_dependencies_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy(ROOT / "start-production.sh", root)
            result = subprocess.run(
                ["bash", str(root / "start-production.sh")],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("Production Python dependencies are missing", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_release_is_not_excluded_from_publishing(self):
        excludes = (ROOT / ".replitignore").read_text().splitlines()
        patterns = [line.strip() for line in excludes if line and not line.startswith("#")]
        self.assertIn("/.pythonlibs/", patterns)
        self.assertNotIn("/.production-python/", patterns)
        self.assertIn("/.production-python/", (ROOT / ".gitignore").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
