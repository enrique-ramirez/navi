"""The engine as git carries it, which is the engine the deploy installs.

`deploy.sh` installs the engine from the checkout on hyrule-castle, so a
file that `.gitignore` swallows never reaches the box. `genres.py` reads its
data file at import, and a missing one fails every command there while the
MacBook, which still has the file, runs clean.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

import musiclib

PACKAGE = Path(musiclib.__file__).resolve().parent


def package_files() -> list[Path]:
    # Bytecode is what Python leaves behind, not what the package holds.
    return sorted(
        p for p in PACKAGE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    )


@unittest.skipIf(shutil.which("git") is None, "git is not on PATH")
class TravelsWithGit(unittest.TestCase):
    def test_no_file_in_the_package_is_ignored_by_git(self) -> None:
        root = Path(subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=PACKAGE, capture_output=True, text=True, check=True,
        ).stdout.strip())
        found = package_files()
        # An empty listing would make the check below pass on nothing.
        self.assertIn(PACKAGE / "genres.py", found)
        held = [str(p.relative_to(root)) for p in found]

        # Exit 1 is "nothing ignored", 0 is "something ignored" and prints
        # it, anything else is git failing and proves nothing either way.
        result = subprocess.run(
            ["git", "check-ignore", "--verbose", "--stdin"],
            cwd=root, input="\n".join(held) + "\n", capture_output=True, text=True,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertEqual(result.stdout, "", "git ignores these, so the deploy never gets them")


if __name__ == "__main__":
    unittest.main()
