"""The server as the deploy installs it: the standard library, mutagen and musiclib.

The deploy puts agitha beside musiclib on hyrule-castle and installs mutagen
and nothing else for it, so an import of anything more fails there at start
while the MacBook, which has more installed, runs clean. And agitha never
stops, starts or restarts foobar2000, so no source file of
the server names `systemctl` at all.

`agitha/ui/` is the page, built by pnpm, and holds no server code.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "agitha"

#: What `agitha` may import from outside the standard library.
ALLOWED = {"mutagen", "musiclib", "agitha", "__future__"}


def server_files() -> list[Path]:
    """Every `.py` of the server, skipping the page and its `node_modules`."""
    found = []
    for folder, subfolders, names in os.walk(PACKAGE):
        here = Path(folder)
        if here == PACKAGE:
            subfolders[:] = [s for s in subfolders if s != "ui"]
        subfolders[:] = [s for s in subfolders if s != "__pycache__"]
        found.extend(here / name for name in names if name.endswith(".py"))
    return sorted(found)


def outside_imports(source: str, relpath: str) -> list[str]:
    """Every import in one file of a top-level module that is not the standard library's or allowed."""
    allowed = set(sys.stdlib_module_names) | ALLOWED
    found = []
    for node in ast.walk(ast.parse(source, relpath)):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            modules = [node.module or ""]
        else:
            continue
        found.extend(f"{relpath}: {module}" for module in modules if module.split(".")[0] not in allowed)
    return found


class ImportsOnlyWhatTheDeployInstalls(unittest.TestCase):
    def test_the_scanner_flags_a_module_outside_the_standard_library_mutagen_and_musiclib(self) -> None:
        # Without this, a scanner that matched nothing would leave the
        # package check below green on every tree. Pillow is allowed for
        # musiclib and not for agitha, and the other three are what a web
        # server is usually built on.
        source = (
            "import os.path, json, http.server as hs\n"
            "from mutagen.flac import FLAC\n"
            "from musiclib.batch.job import Job\n"
            "from agitha import archives\n"
            "from . import queue\n"
            "from .state import read\n"
            "import flask\n"
            "def late():\n"
            "    from PIL import Image\n"
            "    import werkzeug.serving\n"
            "class Handler:\n"
            "    def do_GET(self):\n"
            "        import requests\n"
        )
        self.assertEqual(sorted(outside_imports(source, "server.py")), [
            "server.py: PIL",
            "server.py: flask",
            "server.py: requests",
            "server.py: werkzeug.serving",
        ])

    def test_the_file_walk_skips_the_page_and_finds_the_server(self) -> None:
        files = server_files()
        # An empty listing would make the checks below pass on nothing.
        self.assertIn(PACKAGE / "__init__.py", files)
        self.assertIn(PACKAGE / "__main__.py", files)
        self.assertIn(PACKAGE / "server.py", files)
        self.assertEqual([p for p in files if "ui" in p.relative_to(PACKAGE).parts], [])

    def test_no_module_imports_anything_but_the_standard_library_mutagen_and_musiclib(self) -> None:
        files = server_files()
        self.assertIn(PACKAGE / "server.py", files)
        offenders = sorted(
            line
            for path in files
            for line in outside_imports(path.read_text(encoding="utf-8"), path.relative_to(PACKAGE).as_posix())
        )
        self.assertEqual(offenders, [], "the deploy does not install these:\n" + "\n".join(offenders))


class NeverTouchesFoobar(unittest.TestCase):
    def test_no_server_file_mentions_systemctl(self) -> None:
        # A plain text search, comments and strings included:
        # the server has no business naming the tool that stops a unit.
        files = server_files()
        self.assertIn(PACKAGE / "server.py", files)
        offenders = sorted(
            path.relative_to(PACKAGE).as_posix()
            for path in files
            if "systemctl" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(offenders, [], "these mention systemctl:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
