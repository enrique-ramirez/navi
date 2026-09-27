"""`applied.jsonl`: a line holding a tag value with a line separator in it still reads back as one line.

`append_log` writes a line with `ensure_ascii=False`, so a tag value goes
into the file as the characters it holds. A lyrics or comment value can
hold U+2028 LINE SEPARATOR, U+2029 PARAGRAPH SEPARATOR or U+0085 NEXT LINE,
and `str.splitlines()` breaks a line at every one of them as well as at
`\\n`. A log split that way cuts the line in the middle of a JSON string,
and every later read of the job fails: on the box, the second
`musiclib batch apply` stopped with `JSONDecodeError: Unterminated string`,
and rollback reads the log the same way.

`json.dumps` already escapes `\\x0b`, `\\x0c` and `\\x1c` to `\\x1e`, since it
escapes every control character below U+0020, so those four pass today.
They are here because `splitlines()` breaks at them too, and a writer that
stopped escaping them would bring the same failure back.

The end-to-end cases build the job the way `tests.test_batch_apply` does,
with its `Library` and `tests.test_batch_identify`'s fake MusicBrainz.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from musiclib import files, tagwrite
from musiclib.batch import job as job_module
from musiclib.batch.job import Job
from tests import builders
from tests.test_batch_apply import new_library

#: Every character `str.splitlines()` treats as a line break that `\n`
#: splitting does not. `\r` is left out: `json.dumps` escapes it, and a
#: reader that splits on `\n` alone would leave a raw one on the line.
SEPARATORS = {
    "U+2028 LINE SEPARATOR": "\u2028",
    "U+2029 PARAGRAPH SEPARATOR": "\u2029",
    "U+0085 NEXT LINE": "\x85",
    "U+001C FILE SEPARATOR": "\x1c",
    "U+001D GROUP SEPARATOR": "\x1d",
    "U+001E RECORD SEPARATOR": "\x1e",
    "U+000B LINE TABULATION": "\x0b",
    "U+000C FORM FEED": "\x0c",
}

ALBUM = "L/Lyric Band/Record [rip]"

#: A lyrics value as a ripper leaves one. Lyrics are kept as written, so this
#: value survives the plan unchanged and lands in the record's prior tags.
LYRICS = "first verse\u2028second verse"


def entry(source: str, lyrics: str) -> dict:
    """An `applied` line in the shape apply writes, with `lyrics` as a track's prior value."""
    return {"source": source, "destination": source.replace(" [rip]", ""), "outcome": "applied",
            "error": None,
            "record": {"tags": {f"{source}/01 one.flac": {"lyrics": [lyrics], "title": ["one"]}},
                       "moves": [], "created": [], "deleted": []}}


def log_lines(job_dir: Path) -> list[dict]:
    """`applied.jsonl` split on `\\n` alone, the way the writer ends each line.

    `tests.test_batch_apply.Library.log` splits with `splitlines()`, which
    breaks on the very characters these cases put in the log.
    """
    text = (job_dir / "applied.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line]


def tracks(root: Path) -> dict[str, dict[str, list[str]]]:
    """Every flac under `root` by its relative path, with its tags less any picture."""
    found = {}
    for path in sorted(root.rglob("*.flac")):
        track = files.read(path)
        found[path.relative_to(root).as_posix()] = {
            key: values for key, values in track.tags.items()
            if not tagwrite.is_picture_key(track.family, key)}
    return found


class ReadingBack(unittest.TestCase):
    def test_every_entry_appended_is_read_back_unchanged_and_in_order_whatever_separator_its_values_hold(self):
        for name, char in SEPARATORS.items():
            with self.subTest(separator=name):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                job = Job(Path(tmp.name))
                # Out of path order, so a reader that sorted would be caught,
                # and plain lines either side of the odd one, so a reader
                # that dropped or merged a line would be too. The separator
                # sits at the start, in the middle and at the end of a value.
                written = [entry("Z/Zeta/Last [rip]", "plain"),
                           entry("M/Mid/Middle [rip]", f"{char}one{char}two{char}"),
                           entry("A/Alpha/First [rip]", "plain")]
                for line in written:
                    job_module.append_log(job, line)

                self.assertEqual(job_module.read_log(job), written)


class ApplyingTwice(unittest.TestCase):
    """One flac album whose tracks carry lyrics with U+2028 in them, applied once."""

    def setUp(self):
        lib = self.lib = new_library(self)
        base = lib.add(ALBUM, 1)
        for path in sorted(base.glob("*.flac")):
            builders.write_tags(path, {"LYRICS": [LYRICS]})
        self.before = tracks(lib.root)
        lib.identify()
        if lib.states() != {ALBUM: "auto"}:
            raise AssertionError(f"the fixture did not plan as these cases assume: {lib.states()}")

        code, _out, err = lib.apply()
        first = log_lines(lib.job)
        if code != 0 or [line["outcome"] for line in first] != ["applied"]:
            raise AssertionError(f"the first apply did not write the album: {code}, {err}, {first}")
        # With no separator in the record these cases pass without testing a thing.
        if LYRICS not in json.dumps(first, ensure_ascii=False):
            raise AssertionError("the applied record does not hold the lyrics with their U+2028")
        self.applied = builders.tree(lib.root)

    def test_a_second_apply_on_the_same_job_skips_the_applied_album_and_writes_nothing(self):
        code, out, err = self.lib.apply()

        self.assertEqual(code, 0, out + err)
        self.assertEqual([line["outcome"] for line in log_lines(self.lib.job)], ["applied"])
        self.assertEqual(builders.tree(self.lib.root), self.applied)

    def test_rollback_puts_the_album_back_with_its_lyrics_as_they_were(self):
        from musiclib.batch.rollback import run

        lib = self.lib
        out, err = io.StringIO(), io.StringIO()
        # Exit 1 is expected either way: rollback lists the cover apply wrote
        # and the pictures it embedded. The tracks are what it owes back.
        code = run(Job(lib.job), extras_root=lib.extras, live_root=lib.root,
                   systemctl=str(lib.systemctl(running=False)), out=out, err=err)

        self.assertEqual(tracks(lib.root), self.before, f"exit {code}: {out.getvalue()}{err.getvalue()}")


if __name__ == "__main__":
    unittest.main()
