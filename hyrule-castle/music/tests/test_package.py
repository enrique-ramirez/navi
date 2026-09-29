"""The engine as git carries it, which is the engine the deploy installs.

`deploy.sh` installs the engine from the checkout on hyrule-castle, so a
file that `.gitignore` swallows never reaches the box. `genres.py` reads its
data file at import, and a missing one fails every command there while the
MacBook, which still has the file, runs clean.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
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


def private_imports(source: str, relpath: str) -> list[str]:
    """Every `from <musiclib module> import _name` in one file, as `relpath: from module import name`.

    Relative imports are resolved against the file's own package, so
    `from ..write import _x` in `batch/apply.py` reads as `musiclib.write`.
    Dunder names such as `__version__` are public by convention and pass.
    """
    parts = relpath[:-len(".py")].split("/")
    package = ["musiclib", *parts[:-1]]
    found = []
    for node in ast.walk(ast.parse(source, relpath)):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            base = package[:len(package) - (node.level - 1)]
            module = ".".join(base + ([node.module] if node.module else []))
        else:
            module = node.module or ""
        if module != "musiclib" and not module.startswith("musiclib."):
            continue
        for alias in node.names:
            name = alias.name
            if name.startswith("_") and not (name.startswith("__") and name.endswith("__")):
                found.append(f"{relpath}: from {module} import {name}")
    return found


class KeepsPrivateNamesPrivate(unittest.TestCase):
    def test_the_scanner_flags_a_private_name_taken_from_a_musiclib_module(self) -> None:
        # Without this, a scanner that matched nothing would leave the
        # package check below green on every tree.
        source = (
            "from musiclib.x import public, _y\n"
            "from ..write import _guard\n"
            "from musiclib import __version__\n"
            "from os import _exit\n"
            "def late():\n"
            "    from musiclib.plan import _sort\n"
        )
        self.assertEqual(sorted(private_imports(source, "batch/z.py")), [
            "batch/z.py: from musiclib.plan import _sort",
            "batch/z.py: from musiclib.write import _guard",
            "batch/z.py: from musiclib.x import _y",
        ])

    def test_no_module_imports_an_underscore_name_from_another(self) -> None:
        # A leading underscore says the name may change without notice. A
        # second module that imports it turns every such change into a break
        # somewhere the author of the first module was not looking.
        files = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
        # An empty listing would make the check below pass on nothing.
        self.assertIn(PACKAGE / "batch" / "apply.py", files)
        offenders = sorted(
            line
            for path in files
            for line in private_imports(path.read_text(encoding="utf-8"), path.relative_to(PACKAGE).as_posix())
        )
        self.assertEqual(offenders, [], "these import a private name from another module:\n" + "\n".join(offenders))


def is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def is_package_module(module: str) -> bool:
    """Whether a dotted `musiclib...` name is a module of the package, not a function or class in one."""
    parts = module.split(".")[1:]
    where = PACKAGE.joinpath(*parts)
    return (where / "__init__.py").is_file() or where.with_suffix(".py").is_file()


def private_attributes(source: str, relpath: str) -> list[str]:
    """Every `alias._name` in one file where `alias` is a musiclib module it imported, as `relpath: alias._name (module)`.

    `from musiclib import x` binds a module only when `musiclib/x.py` is
    one; a class or function imported that way is not a module, and its
    underscore attributes (`Plan._replace` on a namedtuple) are not what
    this looks for. `import musiclib.write` binds `musiclib`, so
    `musiclib.write._x` is read through the dotted chain.
    """
    parts = relpath[:-len(".py")].split("/")
    package = ["musiclib", *parts[:-1]]
    tree = ast.parse(source, relpath)
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name != "musiclib" and not alias.name.startswith("musiclib."):
                    continue
                if alias.asname:
                    bound[alias.asname] = alias.name
                else:
                    bound[alias.name.split(".")[0]] = alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[:len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            if module != "musiclib" and not module.startswith("musiclib."):
                continue
            for alias in node.names:
                target = f"{module}.{alias.name}"
                if is_package_module(target):
                    bound[alias.asname or alias.name] = target
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not is_private(node.attr):
            continue
        chain = []
        value = node.value
        while isinstance(value, ast.Attribute):
            chain.append(value.attr)
            value = value.value
        if not isinstance(value, ast.Name) or value.id not in bound:
            continue
        written = ".".join([value.id, *reversed(chain)])
        module = ".".join([bound[value.id], *reversed(chain)])
        found.append(f"{relpath}: {written}.{node.attr} ({module})")
    return found


class KeepsPrivateAttributesPrivate(unittest.TestCase):
    # The import check above sees `from x import _y` and misses the same
    # reach written as `import x` then `x._y`.

    def test_the_scanner_flags_a_private_attribute_through_every_import_form(self) -> None:
        # Without this, a scanner that matched nothing would leave the
        # package check below green on every tree. The module names are
        # real ones, because a `from` import counts only if it names a
        # module the package holds.
        source = (
            "import musiclib.write as w\n"
            "import musiclib.plan\n"
            "from musiclib import mapping\n"
            "from musiclib.batch import decisions as decisions_module\n"
            "from . import job\n"
            "from .. import names as names_module\n"
            "w._guard\n"
            "musiclib.plan._sort()\n"
            "mapping._kept_or_mb(1)\n"
            "decisions_module._follow(key, m)\n"
            "job._x = 1\n"
            "def late():\n"
            "    from musiclib import files\n"
            "    return names_module._clean(files._family(p))\n"
        )
        self.assertEqual(sorted(private_attributes(source, "batch/z.py")), [
            "batch/z.py: decisions_module._follow (musiclib.batch.decisions)",
            "batch/z.py: files._family (musiclib.files)",
            "batch/z.py: job._x (musiclib.batch.job)",
            "batch/z.py: mapping._kept_or_mb (musiclib.mapping)",
            "batch/z.py: musiclib.plan._sort (musiclib.plan)",
            "batch/z.py: names_module._clean (musiclib.names)",
            "batch/z.py: w._guard (musiclib.write)",
        ])

    def test_the_scanner_leaves_alone_what_is_not_a_musiclib_module(self) -> None:
        # Each of these is an underscore after a dot that is fine: a module
        # outside the package, the object's own attribute, a local that
        # happens to share no import, a class imported from a musiclib
        # module, and a dunder, which is public by convention.
        source = (
            "import os\n"
            "import os.path as osp\n"
            "from musiclib.plan import Plan\n"
            "from musiclib import write\n"
            "os._exit(1)\n"
            "osp._joinrealpath\n"
            "self._x\n"
            "job = load()\n"
            "job._cache\n"
            "Plan._replace(p)\n"
            "write.__name__\n"
            "write.guard_foobar\n"
        )
        self.assertEqual(private_attributes(source, "batch/z.py"), [])

    def test_no_module_reaches_into_another_modules_underscore_names(self) -> None:
        # The same promise as the import check: a leading underscore says the
        # name may change without notice, and `x._y` breaks as surely as
        # `from x import _y` when it does.
        files = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
        # An empty listing would make the check below pass on nothing.
        self.assertIn(PACKAGE / "batch" / "identify.py", files)
        offenders = sorted(
            line
            for path in files
            for line in private_attributes(path.read_text(encoding="utf-8"), path.relative_to(PACKAGE).as_posix())
        )
        self.assertEqual(offenders, [], "these reach a private name of another module:\n" + "\n".join(offenders))


#: What `musiclib` may import from outside itself : the deploy
#: installs mutagen and Pillow beside it and nothing else.
ALLOWED_DISTRIBUTIONS = {"mutagen", "PIL"}


def outside_imports(source: str, relpath: str) -> list[str]:
    """Every import in one file of a top-level module that is not the standard library's, musiclib's or allowed."""
    allowed = set(sys.stdlib_module_names) | ALLOWED_DISTRIBUTIONS | {"musiclib", "__future__"}
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
    def test_the_scanner_flags_a_module_outside_the_standard_library_mutagen_and_pillow(self) -> None:
        # Without this, a scanner that matched nothing would leave the
        # package check below green on every tree. `imagehash` and `numpy`
        # are what an average hash is usually built on.
        source = (
            "import os.path, numpy as np\n"
            "from PIL import Image\n"
            "from mutagen.flac import FLAC\n"
            "from . import files\n"
            "from ..write import write_album\n"
            "from musiclib import images\n"
            "def late():\n"
            "    from imagehash import average_hash\n"
            "    import requests.adapters\n"
        )
        self.assertEqual(sorted(outside_imports(source, "batch/z.py")), [
            "batch/z.py: imagehash",
            "batch/z.py: numpy",
            "batch/z.py: requests.adapters",
        ])

    def test_no_module_imports_anything_but_the_standard_library_mutagen_and_pillow(self) -> None:
        files = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
        # An empty listing would make the check below pass on nothing.
        self.assertIn(PACKAGE / "images.py", files)
        offenders = sorted(
            line
            for path in files
            for line in outside_imports(path.read_text(encoding="utf-8"), path.relative_to(PACKAGE).as_posix())
        )
        self.assertEqual(offenders, [], "the deploy does not install these:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
