"""Open a dropped archive into a folder, or refuse it whole.

Everything is written to a temporary sibling of the target and moved in
only after every entry has passed, so a refusal leaves the target as it was
and the archive where it was.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

from .paths import climbs

ZIP_UTF8_FLAG = 0x800
ZIP_ENCRYPTED_FLAG = 0x1
S_IFMT = 0o170000
S_IFLNK = 0o120000

BSDTAR_SUFFIXES = {".rar", ".7z"}


class ArchiveRefused(Exception):
    """The archive was not opened. `entry` is the member at fault, where there is one."""

    def __init__(self, reason: str, entry: str | None = None) -> None:
        super().__init__(reason, entry)
        self.reason = reason
        self.entry = entry

    def __str__(self) -> str:
        return f"{self.reason}: {self.entry}" if self.entry else self.reason


def extract(archive: Path, into: Path) -> None:
    """Extract `archive` under `into`, then delete it. Raises ArchiveRefused and leaves both untouched."""
    suffix = archive.suffix.lower()
    if suffix != ".zip" and suffix not in BSDTAR_SUFFIXES:
        raise ArchiveRefused("not an archive", archive.name)
    into.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=into.parent, prefix=into.name + ".extracting-"))
    try:
        if suffix == ".zip":
            _extract_zip(archive, work)
        else:
            _extract_bsdtar(archive, work)
        for item in sorted(work.iterdir()):
            shutil.move(str(item), into / item.name)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    archive.unlink()


def _unsafe(name: str) -> str | None:
    """Why a member name cannot be written under the target, or None."""
    if name.startswith(("/", "\\")):
        return "absolute path"
    if climbs(name):
        return "path goes above the folder"
    return None


def _zip_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & ZIP_UTF8_FLAG:
        return info.filename
    # `zipfile` decoded a flagless name as cp437; that is lossless, so the raw bytes come back.
    raw = info.filename.encode("cp437")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp850")


def _zip_problem(info: zipfile.ZipInfo, name: str) -> str | None:
    problem = _unsafe(name)
    if problem is None and (info.external_attr >> 16) & S_IFMT == S_IFLNK:
        return "symlink"
    if problem is None and info.flag_bits & ZIP_ENCRYPTED_FLAG:
        return "password-protected"
    return problem


def _zip_members(zf: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    """Every member worth writing, with its decoded name; raises on the first one that cannot be."""
    members = []
    for info in zf.infolist():
        name = _zip_name(info)
        if name.startswith("__MACOSX/"):
            continue
        problem = _zip_problem(info, name)
        if problem:
            raise ArchiveRefused(problem, name)
        members.append((info, name))
    return members


def _write_zip_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, name: str, work: Path) -> None:
    target = work / name
    try:
        if name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as err:
        raise ArchiveRefused(f"damaged or unsupported: {err}", name) from err
    except OSError as err:
        raise ArchiveRefused(f"cannot be read: {err}", name) from err


def _extract_zip(archive: Path, work: Path) -> None:
    try:
        with zipfile.ZipFile(archive) as zf:
            for info, name in _zip_members(zf):
                _write_zip_member(zf, info, name, work)
    except zipfile.BadZipFile as err:
        raise ArchiveRefused(f"not a readable zip: {err}") from err
    except OSError as err:
        raise ArchiveRefused(f"cannot be read: {err}") from err


def _bsdtar(*args: str) -> str:
    # Debian's bsdtar mangles non-ASCII names under the C locale.
    env = {**os.environ, "LC_ALL": "C.UTF-8"}
    try:
        done = subprocess.run(["bsdtar", *args], capture_output=True, env=env)
    except FileNotFoundError as err:
        raise ArchiveRefused("bsdtar is not installed") from err
    if done.returncode != 0:
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ArchiveRefused(lines[-1] if lines else f"bsdtar exited {done.returncode}")
    return done.stdout.decode("utf-8", "replace")


def _extract_bsdtar(archive: Path, work: Path) -> None:
    names = _bsdtar("-tf", str(archive)).splitlines()
    kinds = [line[:1] for line in _bsdtar("-tvf", str(archive)).splitlines()]
    for i, name in enumerate(names):
        problem = _unsafe(name)
        # Links are refused by type: a hard link can point outside the folder as well as a symlink can.
        if problem is None and i < len(kinds) and kinds[i] in ("l", "h"):
            problem = "symlink"
        if problem:
            raise ArchiveRefused(problem, name)
    _bsdtar("-xf", str(archive), "-C", str(work), "--no-same-owner")
