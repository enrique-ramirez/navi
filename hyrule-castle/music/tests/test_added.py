"""`ADDED`: the time an import brought the album in, written on every file it plans.

`musiclib batch identify --added YYYY-MM-DDTHH:MM` plans that value as each
file's `ADDED` (`TXXX:ADDED`, Vorbis `ADDED`, MP4
`----:com.apple.iTunes:ADDED`, ASF `ADDED`), replacing one the file has in
any case, and keeps it in the entry's `inputs` so apply rebuilds the same
plan. A job without the flag - a library job - plans no `ADDED` and leaves
one a file already has exactly as it is.

Jobs are built the real way, rips on disk and `batch identify` over the fake
MusicBrainz of `tests.test_batch_identify`; the per-format cases plan one
fixture file of each format against a release directly.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from musiclib import files, mapping
from musiclib.__main__ import main
from tests import builders
from tests.test_batch_apply import Library, new_library
from tests.test_batch_identify import Services, release

STAMP = "2026-09-30T11:02"
EARLIER = "2019-04-01T20:15"
KEY = "A/Alpha/First [rip]"
FOUND, _GROUP = release(1, "Alpha", "First", ["One", "Two"])

#: The one key each format carries `ADDED` under, as `files.read` reports it.
ADDED_KEYS = {"mp3": "TXXX:ADDED", "flac": "added", "ogg": "added", "m4a": "----:com.apple.iTunes:ADDED",
              "wma": "ADDED"}


def identify(lib: Library, added: str | None) -> None:
    from musiclib.batch.identify import run
    from musiclib.batch.job import Job

    code = run(lib.root, Job(lib.job), lib.memory, [], transport=Services(lib.catalogue), env={},
               which=lambda _name: None, out=io.StringIO(), err=io.StringIO(), added=added)
    assert code == 0, "identify failed"


def after_values(entry: dict, key: str) -> list:
    return [planned["after"].get(key) for planned in entry["files"]]


class PerFormat(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def plan(self, ext: str, added: str | None, tags: dict | None = None) -> dict:
        path = self.tmp / f"01.{ext}"
        shutil.copyfile(builders.FIXTURES / f"tone.{ext}", path)
        if tags:
            builders.write_tags(path, tags, v2_version=4)
        return mapping.plan_tags(files.read(path), FOUND, 1, 1, [], added=added).target

    def test_each_format_carries_added_under_its_own_key(self) -> None:
        for ext, key in ADDED_KEYS.items():
            with self.subTest(ext=ext):
                self.assertEqual(self.plan(ext, STAMP).get(key), [STAMP])

    def test_an_added_the_file_has_in_another_case_is_replaced_not_kept_beside_it(self) -> None:
        for ext, spelled in (("mp3", "TXXX:added"), ("m4a", "----:com.apple.iTunes:added"), ("wma", "Added")):
            with self.subTest(ext=ext):
                target = self.plan(ext, STAMP, {spelled: EARLIER})
                self.assertEqual({k: v for k, v in target.items() if k.casefold().endswith("added")},
                                 {ADDED_KEYS[ext]: [STAMP]})

    def test_without_a_stamp_an_added_the_file_has_is_kept_as_written(self) -> None:
        for ext, key in ADDED_KEYS.items():
            with self.subTest(ext=ext):
                spelled = "ADDED" if ext in ("flac", "ogg") else key
                self.assertEqual(self.plan(ext, None, {spelled: f" {EARLIER} "}).get(key), [f" {EARLIER} "])
                self.assertNotIn(key, self.plan(ext, None))


class Importing(unittest.TestCase):
    """An import planned with `--added`, then applied."""

    def setUp(self) -> None:
        self.lib = new_library(self)
        self.lib.add(KEY, 1)
        identify(self.lib, STAMP)
        self.entry = self.lib.entries()[KEY]

    def test_every_planned_file_carries_the_stamp_and_the_entry_keeps_it_for_apply(self) -> None:
        self.assertEqual(after_values(self.entry, "added"), [[STAMP], [STAMP]])
        self.assertEqual(self.entry["inputs"]["added"], STAMP)

    def test_apply_rebuilds_the_same_plan_and_writes_the_stamp(self) -> None:
        code, _out, err = self.lib.apply()
        self.assertEqual(code, 0, err)
        self.assertEqual([line["outcome"] for line in self.lib.log()], ["applied"])
        for planned in self.entry["files"]:
            self.assertEqual(files.read(self.lib.root / planned["destination"]).tags.get("added"), [STAMP])

    def test_the_stamp_must_be_a_minute_written_exactly(self) -> None:
        for value in ("2026-09-30 11:02", "2026-09-30T11:02:00", "2026-9-30T11:02", "2026-09-31T11:02"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main(["batch", "identify", str(self.lib.root), "--job", str(self.lib.job), "--added", value])
                self.assertEqual(raised.exception.code, 2)


class LibraryJob(unittest.TestCase):
    """A job without `--added` over files that already carry one."""

    def setUp(self) -> None:
        self.lib = new_library(self)
        folder = self.lib.add(KEY, 1)
        self.paths = sorted(folder.glob("*.flac"))
        for path in self.paths:
            builders.write_tags(path, {"ADDED": EARLIER})
        identify(self.lib, None)
        self.entry = self.lib.entries()[KEY]

    def test_the_plan_keeps_the_files_added_and_records_no_stamp(self) -> None:
        self.assertEqual(after_values(self.entry, "added"), [[EARLIER], [EARLIER]])
        self.assertNotIn("added", self.entry["inputs"])
        self.assertFalse([r for r in self.entry["residue"] if r["key"] == "added"])

    def test_apply_leaves_it_as_it_was(self) -> None:
        code, _out, err = self.lib.apply()
        self.assertEqual(code, 0, err)
        for planned in self.entry["files"]:
            self.assertEqual(files.read(self.lib.root / planned["destination"]).tags.get("added"), [EARLIER])


if __name__ == "__main__":
    unittest.main()
