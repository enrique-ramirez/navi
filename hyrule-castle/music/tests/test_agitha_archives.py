"""Archives dropped on agitha, opened on the box.

A zip made on Windows carries its names as cp850 bytes with no UTF-8 flag,
and one made by a Mac carries UTF-8 bytes with no flag and a `__MACOSX/`
folder of resource forks. Python's `zipfile` reads every flagless name as
cp437, which gets `está` right and `CANCIÓN` wrong (`CANCIαN`), and a
flagless UTF-8 `está` comes out as `estÃ¡`.

An archive that would write outside its folder, plant a symlink, or cannot
be read in full is refused whole: the folder it was going into is left
empty and the archive stays where it was.

Every archive is built here. A RAR cannot be made on this Mac, so the 7z
cases stand in for RAR, which is checked by hand on the box.

`agitha.archives` is imported inside each case, so every case reports on
its own.
"""

from __future__ import annotations

import importlib
import os
import random
import shutil
import stat
import struct
import subprocess
import tempfile
import unicodedata
import unittest
import zipfile
from pathlib import Path

BSDTAR = shutil.which("bsdtar")
needs_bsdtar = unittest.skipUnless(BSDTAR, "bsdtar is not installed")

#: A name with an accented letter.
HIMNO = "03 - Himno (para los que están jodidos).mp3"
#: A name cp437 and cp850 read differently: cp850's 0xE0 is `Ó`, cp437's is `α`.
CANCION = "04 - CANCIÓN DE CUNA.mp3"

ZIP_UTF8_FLAG = 0x800
ZIP_ENCRYPTED_FLAG = 0x1


def noise(seed: int, size: int = 4096) -> bytes:
    """Bytes that do not compress, the same on every run."""
    return random.Random(seed).randbytes(size)


def archives():
    return importlib.import_module("agitha.archives")


def nfc(name: str) -> str:
    # The Mac's bsdtar writes decomposed names; a reader sees the same name either way.
    return unicodedata.normalize("NFC", name)


def tree(root: Path) -> dict[str, str]:
    """Every path under `root`, relative, with its kind, symlinks not followed."""
    found: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            mode = path.lstat().st_mode
            kind = "link" if stat.S_ISLNK(mode) else "dir" if stat.S_ISDIR(mode) else "file"
            found[nfc(path.relative_to(root).as_posix())] = kind
    return found


def files(root: Path) -> dict[str, bytes]:
    """Every regular file under `root`, relative, with its bytes."""
    return {nfc(p.relative_to(root).as_posix()): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def write_zip(path: Path, entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for info, data in entries:
            zf.writestr(info, data)
    return path


def patch_flags(path: Path, entry: str, set_bits: int = 0, clear_bits: int = 0) -> None:
    """Set and clear general-purpose flag bits on one entry, in its local and central headers."""
    with zipfile.ZipFile(path) as zf:
        info = zf.getinfo(entry)
        start_dir = zf.start_dir
        count = len(zf.infolist())
    data = bytearray(path.read_bytes())

    def patch(offset: int) -> None:
        flags = struct.unpack_from("<H", data, offset)[0]
        struct.pack_into("<H", data, offset, (flags | set_bits) & ~clear_bits)

    assert data[info.header_offset:info.header_offset + 4] == b"PK\x03\x04"
    patch(info.header_offset + 6)
    at = start_dir
    for _ in range(count):
        assert data[at:at + 4] == b"PK\x01\x02"
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, at + 28)
        if struct.unpack_from("<I", data, at + 42)[0] == info.header_offset:
            patch(at + 8)
        at += 46 + name_len + extra_len + comment_len
    path.write_bytes(bytes(data))


def zip_with_raw_names(path: Path, entries: list[tuple[bytes, bytes]]) -> Path:
    """A zip whose names are exactly the given bytes, with the UTF-8 flag clear on every entry.

    `zipfile` sets the flag on any non-ASCII name it writes, so each entry is
    written under an ASCII placeholder of the same length and the bytes are
    swapped in afterwards, in the local and the central header.
    """
    placeholders = []
    for i, (raw, _data) in enumerate(entries):
        placeholder = f"~{i}~".ljust(len(raw), "#").encode("ascii")
        assert len(placeholder) == len(raw)
        placeholders.append(placeholder)
    write_zip(path, [(p.decode("ascii"), data) for p, (_raw, data) in zip(placeholders, entries)])
    data = path.read_bytes()
    for placeholder, (raw, _data) in zip(placeholders, entries):
        assert data.count(placeholder) == 2, placeholder
        data = data.replace(placeholder, raw)
    path.write_bytes(data)
    with zipfile.ZipFile(path) as zf:
        assert all(not info.flag_bits & ZIP_UTF8_FLAG for info in zf.infolist())
    return path


def bsdtar_create(out: Path, cwd: Path, members: list[str], *flags: str) -> Path:
    subprocess.run([BSDTAR, "-cf", str(out), "--format", "7zip", *flags, *members],
                   cwd=cwd, check=True, capture_output=True)
    return out


class _Archives(unittest.TestCase):
    """`self.tmp` holds `archives/`, where each archive is made, and `drop/into/`, where it goes."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        (self.tmp / "archives").mkdir()
        self.into = self.tmp / "drop" / "into"
        self.into.mkdir(parents=True)

    def archive(self, name: str) -> Path:
        return self.tmp / "archives" / name

    def build_dir(self, name: str) -> Path:
        """A scratch folder for bsdtar's sources, removed before the archive is opened."""
        path = self.tmp / "build" / name
        path.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def extracted(self, archive: Path) -> dict[str, bytes]:
        archives().extract(archive, self.into)
        return files(self.into)

    def assert_refused(self, archive: Path, entry: str | None = None) -> None:
        """Refused whole: `into` is left empty, nothing lands anywhere else, the archive stays."""
        shutil.rmtree(self.tmp / "build", ignore_errors=True)
        before = tree(self.tmp)
        module = archives()
        with self.assertRaises(module.ArchiveRefused) as caught:
            module.extract(archive, self.into)
        refused = caught.exception
        self.assertIsInstance(refused.reason, str)
        self.assertTrue(refused.reason.strip(), "the refusal gives no reason")
        self.assertIn(refused.reason, str(refused))
        if entry is not None:
            self.assertEqual(nfc(refused.entry or ""), entry)
            self.assertIn(refused.entry, str(refused))
        after = tree(self.tmp)
        left = {p: k for p, k in after.items() if p.startswith("drop/into/")}
        self.assertEqual(left, {}, "a refused archive left files in the folder it was going into")
        # `into` itself may go or stay; everything else under tmp must be exactly as it was.
        before.pop("drop/into", None)
        after.pop("drop/into", None)
        self.assertEqual(after, before, "a refused archive changed something outside `into`")
        self.assertTrue(archive.is_file(), "a refused archive was deleted")


class ZipNames(_Archives):
    """The UTF-8 flag, then valid UTF-8, then cp850."""

    def test_a_flagged_utf8_name_is_read_as_utf8(self) -> None:
        archive = write_zip(self.archive("flagged.zip"), [(f"Blockbuster/{HIMNO}", b"himno")])
        with zipfile.ZipFile(archive) as zf:
            self.assertTrue(zf.getinfo(f"Blockbuster/{HIMNO}").flag_bits & ZIP_UTF8_FLAG)

        self.assertEqual(self.extracted(archive), {f"Blockbuster/{HIMNO}": b"himno"})

    def test_a_flagless_name_that_is_valid_utf8_is_read_as_utf8(self) -> None:
        # What a Mac writes. Read as cp437 or cp850 it comes out `estÃ¡n`.
        archive = zip_with_raw_names(self.archive("mac.zip"), [
            (f"Blockbuster/{HIMNO}".encode("utf-8"), b"himno"),
            (f"Blockbuster/{CANCION}".encode("utf-8"), b"cancion"),
        ])

        self.assertEqual(self.extracted(archive), {
            f"Blockbuster/{HIMNO}": b"himno",
            f"Blockbuster/{CANCION}": b"cancion",
        })

    def test_a_flagless_name_that_is_not_utf8_is_read_as_cp850(self) -> None:
        # What Windows writes. `est\xa0n` is the Latin-1 reading of the first;
        # `CANCIαN` is the cp437 reading of the second, which is what `zipfile` gives.
        archive = zip_with_raw_names(self.archive("La La Love You - Blockbuster.zip"), [
            (f"Blockbuster/{HIMNO}".encode("cp850"), b"himno"),
            (f"Blockbuster/{CANCION}".encode("cp850"), b"cancion"),
        ])

        names = self.extracted(archive)

        self.assertEqual(names, {
            f"Blockbuster/{HIMNO}": b"himno",
            f"Blockbuster/{CANCION}": b"cancion",
        })
        self.assertFalse(any("\xa0" in name or "α" in name for name in names))

    def test_macosx_entries_are_not_extracted_and_the_rest_is(self) -> None:
        archive = write_zip(self.archive("from a mac.zip"), [
            ("x.mp3", b"audio"),
            ("__MACOSX/._x.mp3", b"resource fork"),
            ("__MACOSX/Album/._01.mp3", b"resource fork"),
        ])

        self.assertEqual(self.extracted(archive), {"x.mp3": b"audio"})
        self.assertEqual(tree(self.into), {"x.mp3": "file"})


class GoodExtraction(_Archives):
    """The archive's files arrive whole and the archive is deleted."""

    def test_a_zip_extracts_its_tree_and_is_deleted(self) -> None:
        archive = write_zip(self.archive("album.zip"), [
            ("Album/CD1/01 - Uno.mp3", b"uno"),
            ("Album/CD2/01 - Dos.mp3", b"dos"),
            ("Album/cover.jpg", b"jpeg"),
        ])

        self.assertEqual(self.extracted(archive), {
            "Album/CD1/01 - Uno.mp3": b"uno",
            "Album/CD2/01 - Dos.mp3": b"dos",
            "Album/cover.jpg": b"jpeg",
        })
        self.assertFalse(archive.exists(), "the zip is still there after a good extraction")

    @needs_bsdtar
    def test_a_7z_extracts_its_files_and_folder_through_bsdtar_and_is_deleted(self) -> None:
        src = self.build_dir("good")
        (src / "Álbum").mkdir()
        (src / "Álbum" / "01 - Canción.mp3").write_bytes(b"cancion")
        (src / "Álbum" / "cover.jpg").write_bytes(b"jpeg")
        archive = bsdtar_create(self.archive("album.7z"), src, ["Álbum"])
        shutil.rmtree(src)

        self.assertEqual(self.extracted(archive), {
            "Álbum/01 - Canción.mp3": b"cancion",
            "Álbum/cover.jpg": b"jpeg",
        })
        self.assertFalse(archive.exists(), "the 7z is still there after a good extraction")


class NestedArchive(_Archives):
    """An archive inside an archive is a file of the album, never opened."""

    def test_a_zip_inside_a_zip_is_left_as_a_file(self) -> None:
        inner = write_zip(self.archive("inner.zip"), [("hidden.mp3", b"hidden")]).read_bytes()
        self.archive("inner.zip").unlink()
        archive = write_zip(self.archive("outer.zip"), [
            ("Album/01 - Uno.mp3", b"uno"),
            ("Album/inner.zip", inner),
        ])

        self.assertEqual(self.extracted(archive), {
            "Album/01 - Uno.mp3": b"uno",
            "Album/inner.zip": inner,
        })

    @needs_bsdtar
    def test_a_zip_inside_a_7z_is_left_as_a_file(self) -> None:
        inner = write_zip(self.archive("inner.zip"), [("hidden.mp3", b"hidden")]).read_bytes()
        self.archive("inner.zip").unlink()
        src = self.build_dir("nested")
        (src / "Album").mkdir()
        (src / "Album" / "01 - Uno.mp3").write_bytes(b"uno")
        (src / "Album" / "inner.zip").write_bytes(inner)
        archive = bsdtar_create(self.archive("outer.7z"), src, ["Album"])
        shutil.rmtree(src)

        self.assertEqual(self.extracted(archive), {
            "Album/01 - Uno.mp3": b"uno",
            "Album/inner.zip": inner,
        })


class ZipRefusals(_Archives):
    """Refused zips. Each holds a good entry first, so a partial extraction shows."""

    def test_a_zip_with_an_absolute_entry_is_refused_whole(self) -> None:
        # `zipfile.extract` quietly strips the leading `/` and writes the file.
        escaped = f"{self.tmp}/escaped.mp3"
        archive = write_zip(self.archive("absolute.zip"), [
            ("01 - Uno.mp3", b"uno"),
            (zipfile.ZipInfo(escaped), b"escaped"),
        ])

        self.assert_refused(archive, escaped)

    def test_a_zip_with_a_dotdot_entry_is_refused_whole(self) -> None:
        # From `drop/into/`, this lands at `tmp/escaped.mp3`. `zipfile.extract` drops the `..` instead.
        archive = write_zip(self.archive("dotdot.zip"), [
            ("01 - Uno.mp3", b"uno"),
            ("Album/../../../escaped.mp3", b"escaped"),
        ])

        self.assert_refused(archive, "Album/../../../escaped.mp3")

    def test_a_zip_holding_a_symlink_is_refused_whole(self) -> None:
        # `zipfile` would write the link as a small file holding its target.
        link = zipfile.ZipInfo("cover.jpg")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive = write_zip(self.archive("symlink.zip"), [
            ("01 - Uno.mp3", b"uno"),
            (link, b"/etc/passwd"),
        ])

        self.assert_refused(archive, "cover.jpg")

    def test_a_password_protected_zip_is_refused_whole(self) -> None:
        archive = write_zip(self.archive("password.zip"), [
            ("01 - Uno.mp3", b"uno"),
            ("02 - Secret.mp3", noise(3, 64)),
        ])
        patch_flags(archive, "02 - Secret.mp3", set_bits=ZIP_ENCRYPTED_FLAG)

        self.assert_refused(archive, "02 - Secret.mp3")

    def test_a_zip_whose_entry_fails_its_checksum_is_refused_whole(self) -> None:
        # `zipfile` finds a bad CRC only at the end of the entry, after it has written the first.
        archive = write_zip(self.archive("crc.zip"), [
            ("01 - Uno.mp3", b"uno" * 100),
            ("02 - Dos.mp3", b"dos" * 100),
        ])
        with zipfile.ZipFile(archive) as zf:
            info = zf.getinfo("02 - Dos.mp3")
        data = bytearray(archive.read_bytes())
        name_len, extra_len = struct.unpack_from("<HH", data, info.header_offset + 26)
        data[info.header_offset + 30 + name_len + extra_len + 10] ^= 0xFF
        archive.write_bytes(bytes(data))

        self.assert_refused(archive, "02 - Dos.mp3")

    def test_a_truncated_zip_is_refused(self) -> None:
        good = write_zip(self.archive("truncated.zip"), [
            ("01 - Uno.mp3", b"uno" * 100),
            ("02 - Dos.mp3", b"dos" * 100),
        ])
        good.write_bytes(good.read_bytes()[: good.stat().st_size // 2])

        self.assert_refused(good)

    def test_a_file_named_zip_that_is_not_one_is_refused(self) -> None:
        archive = self.archive("not really.zip")
        archive.write_bytes(b"this is not a zip file at all " * 20)

        self.assert_refused(archive)


@needs_bsdtar
class SevenZipRefusals(_Archives):
    """Refused 7z archives, which stands in for RAR: both go through bsdtar."""

    def test_a_7z_with_an_absolute_entry_is_refused_whole(self) -> None:
        # bsdtar strips the leading `/` and extracts it unless the listing is checked first.
        src = self.build_dir("absolute")
        (src / "01 - Uno.mp3").write_bytes(b"uno")
        escaped = self.tmp / "escaped.mp3"
        escaped.write_bytes(b"escaped")
        archive = bsdtar_create(self.archive("absolute.7z"), src, ["01 - Uno.mp3", str(escaped)], "-P")
        escaped.unlink()

        self.assert_refused(archive, str(escaped))

    def test_a_7z_with_a_dotdot_entry_is_refused_whole(self) -> None:
        src = self.build_dir("dotdot")
        (src / "Album").mkdir()
        (src / "Album" / "01 - Uno.mp3").write_bytes(b"uno")
        (src / "escaped.mp3").write_bytes(b"escaped")
        archive = bsdtar_create(self.archive("dotdot.7z"), src / "Album",
                                ["01 - Uno.mp3", "../escaped.mp3"], "-P")

        self.assert_refused(archive, "../escaped.mp3")

    def test_a_7z_holding_a_symlink_is_refused_whole(self) -> None:
        src = self.build_dir("symlink")
        (src / "01 - Uno.mp3").write_bytes(b"uno")
        (src / "cover.jpg").symlink_to("/etc/passwd")
        archive = bsdtar_create(self.archive("symlink.7z"), src, ["01 - Uno.mp3", "cover.jpg"])

        self.assert_refused(archive, "cover.jpg")

    def test_a_truncated_7z_is_refused(self) -> None:
        src = self.build_dir("truncated")
        (src / "01 - Uno.mp3").write_bytes(noise(1))
        (src / "02 - Dos.mp3").write_bytes(noise(2))
        archive = bsdtar_create(self.archive("truncated.7z"), src, ["01 - Uno.mp3", "02 - Dos.mp3"])
        archive.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])

        self.assert_refused(archive)

    def test_a_7z_whose_data_is_damaged_is_refused_whole(self) -> None:
        # The listing reads fine; bsdtar fails part-way through extracting, after writing a file.
        src = self.build_dir("damaged")
        (src / "01 - Uno.mp3").write_bytes(noise(1))
        (src / "02 - Dos.mp3").write_bytes(noise(2))
        archive = bsdtar_create(self.archive("damaged.7z"), src, ["01 - Uno.mp3", "02 - Dos.mp3"])
        data = bytearray(archive.read_bytes())
        data[32 + 6000] ^= 0xFF
        archive.write_bytes(bytes(data))

        self.assert_refused(archive)

    def test_a_file_named_7z_that_is_not_one_is_refused(self) -> None:
        archive = self.archive("not really.7z")
        archive.write_bytes(b"this is not a 7z file at all " * 20)

        self.assert_refused(archive)


if __name__ == "__main__":
    unittest.main()
