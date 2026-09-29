"""`musiclib batch apply --job DIR`: what a job writes, and what it leaves alone.

Criteria 10 to 14 in spec 002. Apply writes the auto albums and every album
accepted in `decisions.json`, one at a time through 001's `write_album`, in
path order, and nothing else. It writes nothing while foobar2000 is running.
A failed album is reported and the rest still go. `--limit N` is the first N.
Every record the write returns lands in `applied.jsonl` as it comes back.

Every job here is built the real way: rips on disk, `batch identify` over
them with `tests.test_batch_identify`'s fake MusicBrainz, then
`decisions.json` by hand where a case needs one, and identify once more to
fold it in, the way `plan.md` runs a round. Apply then gets a transport that
refuses every request, because identify left the cache warm and apply must
not need the network.

foobar2000 is a stub `systemctl` in the temp folder, and the temp library is
passed as the live root, so the guard runs just as it does on the box. The
stub notes every call. It also copies `applied.jsonl` each time it is asked,
which is how a case sees the log part-way through a run: `write_album` asks
it once per album, before touching anything.

`memory.json` belongs to `tests.test_memory`. Here only its `reopened` list
is read, which apply alone takes albums off.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mutagen.flac import FLAC

from musiclib import files, mb, tagwrite
from musiclib.__main__ import main
from tests import builders
from tests.test_batch_identify import Services, album, no_throttle, release, run_identify

JOB_ID = "j1"
STOP_FOOBAR = "sudo systemctl stop foobar2000"

# Path order is the order below. The letters are picked so that an apply that
# ran the auto albums first and the accepted ones after would get a different
# order from one that went by path: FIRST, ACCEPTED, LAST against FIRST, LAST,
# ACCEPTED.
FIRST = "A/Alpha/First [rip]"
SKIPPED = "B/Beta/Second [rip]"
HELD = "H/Held/Third [rip]"
ACCEPTED = "K/Kept/Fourth [rip]"
UNIDENTIFIED = "U/Unknown/Fifth [rip]"
LAST = "Z/Zeta/Last [rip]"


class Library:
    """A library at `<base>/library` and a job at `<base>/.musiclib/jobs/j1`, as on the box."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.root = base / "library"
        self.root.mkdir()
        self.job = base / ".musiclib" / "jobs" / JOB_ID
        self.job.mkdir(parents=True)
        self.memory = base / ".musiclib" / "memory.json"
        self.extras = base / "extras"
        self.bin = base / "bin"
        self.bin.mkdir()
        self.calls = self.bin / "calls"
        self.snapshots = self.bin / "snapshots"
        self.catalogue: list[tuple[dict, dict]] = []
        self.asked: list[str] = []

    def add(self, key: str, number: int, *, exact: bool = True, tagged: bool = True) -> Path:
        """An album at `key`, tagged with release `number` unless `tagged` is false.

        `exact=False` is a release four minutes off the files, which
        identify can only call `review`, so the album is held. An untagged
        album is searched for, finds nothing and is held `unidentified`.
        """
        titles = ["One", "Two"]
        if not tagged:
            return album(self.root, key, titles)
        artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
        found, group = release(number, artist, title, titles, exact=exact)
        self.catalogue.append((found, group))
        return album(self.root, key, titles, release_id=found["id"])

    def identify(self) -> None:
        run_identify(self.root, self.job, self.memory, Services(self.catalogue))

    def decide(self, albums: dict[str, dict]) -> None:
        """`decisions.json` as the page exports it, then identify again to fold it in."""
        (self.job / "decisions.json").write_text(
            json.dumps({"job": JOB_ID, "albums": albums}), encoding="utf-8")
        self.identify()

    def accept(self, key: str) -> dict:
        """The page's `accept` of `key` as planned: its own release, no edits, no game choice."""
        return {"action": "accept", "release_id": self.entries()[key]["release_id"],
                "edits": {}, "game": None}

    def entries(self) -> dict[str, dict]:
        doc = json.loads((self.job / "plan.json").read_text(encoding="utf-8"))
        return {entry["source"]: entry for entry in doc["albums"]}

    def states(self) -> dict[str, str]:
        return {key: entry["state"] for key, entry in self.entries().items()}

    def systemctl(self, running: bool) -> Path:
        """A stub `systemctl`: notes its arguments, copies `applied.jsonl`, and answers."""
        script = self.bin / "systemctl"
        # `systemctl is-active` exits 3 for a unit that is not running.
        script.write_text(
            "#!/bin/sh\n"
            f'echo "$@" >> "{self.calls}"\n'
            f'{{ echo "---"; cat "{self.job / "applied.jsonl"}" 2>/dev/null; }} >> "{self.snapshots}"\n'
            f"echo {'active' if running else 'inactive'}\n"
            f"exit {0 if running else 3}\n")
        script.chmod(0o755)
        return script

    def refuse(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """The transport apply gets. Identify left the cache warm, so nothing should reach it."""
        self.asked.append(url)
        raise AssertionError(f"apply went to the network for {url}")

    def apply(self, *, running: bool = False, **kwargs) -> tuple[int, str, str]:
        """`batch.apply.run` on this job: its exit code, stdout and stderr.

        Imported here rather than at the top, so this file loads while the
        module does not exist yet and each case fails on its own.
        """
        from musiclib.batch.apply import run
        from musiclib.batch.job import Job

        out, err = io.StringIO(), io.StringIO()
        code = run(Job(self.job), self.memory, extras_root=self.extras, live_root=self.root,
                   systemctl=str(self.systemctl(running)), transport=self.refuse,
                   out=out, err=err, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def log(self) -> list[dict]:
        """`applied.jsonl`, one dict per line. No file is no lines."""
        path = self.job / "applied.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def calls_made(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def log_as_seen_by_systemctl(self) -> list[list[str]]:
        """The album keys in `applied.jsonl` at each call to the stub, in call order."""
        if not self.snapshots.exists():
            return []
        chunks = self.snapshots.read_text(encoding="utf-8").split("---\n")[1:]
        return [[json.loads(line)["source"] for line in chunk.splitlines()] for chunk in chunks]


def files_outside(snapshot: dict[str, bytes | None], folders: list[str]) -> dict[str, bytes]:
    """Every file in a `builders.tree` snapshot that is not under one of `folders`."""
    return {path: data for path, data in snapshot.items()
            if data is not None and not any(path == f or path.startswith(f + "/") for f in folders)}


def new_library(case) -> Library:
    tmp = tempfile.TemporaryDirectory()
    cleanup = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    cleanup(tmp.cleanup)
    no_throttle(case)
    return Library(Path(tmp.name))


class _Case(unittest.TestCase):
    def assertWrittenAsPlanned(self, lib: Library, entry: dict) -> None:
        """Every track of `entry` at its planned destination, carrying its planned tags."""
        moved = [f for f in entry["files"] if f["source"] != f["destination"]]
        # A plan that moves nothing would pass this with the album never touched.
        self.assertTrue(moved, f"{entry['source']}: the fixture plans no move")
        for planned in entry["files"]:
            destination = lib.root / planned["destination"]
            self.assertTrue(destination.is_file(), f"{planned['destination']} was not written")
            if planned in moved:
                self.assertFalse((lib.root / planned["source"]).exists(),
                                 f"{planned['source']} is still there")
            track = files.read(destination)
            # The embedded cover is written after the tags, so a picture key's
            # planned value is the old picture's digest. Every other key is
            # exactly the plan.
            for key, values in planned["after"].items():
                if not tagwrite.is_picture_key(track.family, key):
                    self.assertEqual(track.tags.get(key), values, f"{planned['destination']}: {key}")

    def assertApplied(self, lib: Library, keys: list[str]) -> None:
        self.assertEqual([line["source"] for line in lib.log() if line["outcome"] == "applied"], keys)


class Applying(_Case):
    """One library with an album in every position apply has to tell apart, applied once.

    FIRST and LAST are auto. SKIPPED is auto, and the owner skipped it.
    HELD is `review` with no decision. ACCEPTED is `review`, and the owner
    accepted it. UNIDENTIFIED has no plan at all. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        # Made out of path order, so an apply that went by the order the
        # folders happen to come off the disk shows.
        lib.add(LAST, 6)
        lib.add(ACCEPTED, 4, exact=False)
        lib.add(FIRST, 1)
        lib.add(UNIDENTIFIED, 5, tagged=False)
        lib.add(HELD, 3, exact=False)
        lib.add(SKIPPED, 2)
        lib.identify()
        lib.decide({SKIPPED: {"action": "skip"}, ACCEPTED: lib.accept(ACCEPTED),
                    UNIDENTIFIED: {"action": "skip"}})
        cls.entries = lib.entries()
        states = {key: entry["state"] for key, entry in cls.entries.items()}
        expected = {FIRST: "auto", SKIPPED: "auto", HELD: "held", ACCEPTED: "held",
                    UNIDENTIFIED: "held", LAST: "auto"}
        if states != expected:
            raise AssertionError(f"the fixture did not plan as these cases assume: {states}")
        cls.before = builders.tree(lib.root)
        cls.code, cls.out, cls.err = lib.apply()
        cls.after = builders.tree(lib.root)

    def test_every_auto_album_is_written_with_the_tags_and_paths_it_was_planned_with(self):
        for key in (FIRST, LAST):
            with self.subTest(album=key):
                self.assertWrittenAsPlanned(self.lib, self.entries[key])

    def test_a_held_album_the_owner_accepted_is_written_as_planned(self):
        self.assertWrittenAsPlanned(self.lib, self.entries[ACCEPTED])

    def test_an_auto_album_the_owner_skipped_is_byte_identical_afterwards(self):
        # Auto, so it would have been written but for the skip.
        inside = {p: b for p, b in self.before.items() if p.startswith(SKIPPED + "/")}
        self.assertTrue(inside, f"{SKIPPED}: the fixture has no files")
        self.assertEqual({p: b for p, b in self.after.items() if p.startswith(SKIPPED + "/")}, inside)

    def test_a_held_album_with_no_decision_and_one_with_no_plan_are_byte_identical_afterwards(self):
        for key in (HELD, UNIDENTIFIED):
            with self.subTest(album=key):
                inside = {p: b for p, b in self.before.items() if p.startswith(key + "/")}
                self.assertTrue(inside, f"{key}: the fixture has no files")
                self.assertEqual({p: b for p, b in self.after.items() if p.startswith(key + "/")}, inside)

    def test_every_file_outside_the_applied_albums_is_byte_identical_at_the_same_path(self):
        # Checked over the whole library rather than album by album, so a
        # file apply wrote, moved or removed anywhere else shows up too.
        applied = [self.entries[key][end] for key in (FIRST, ACCEPTED, LAST)
                   for end in ("source", "destination")]
        self.assertEqual(files_outside(self.after, applied), files_outside(self.before, applied))

    def test_the_run_exits_0_without_asking_the_network_or_stopping_foobar(self):
        self.assertEqual(self.code, 0, self.err)
        self.assertEqual(self.lib.asked, [])
        calls = self.lib.calls_made()
        # The stub must have been asked, or the "never stops it" half is
        # true of a run that never looked.
        self.assertTrue(calls, "systemctl was never asked whether foobar2000 is running")
        for call in calls:
            self.assertTrue(call.startswith("is-active"), f"systemctl was run with: {call}")

    def test_applied_jsonl_has_one_line_per_written_album_in_path_order_with_its_write_record(self):
        log = self.lib.log()
        self.assertEqual([line["source"] for line in log], [FIRST, ACCEPTED, LAST])
        for line in log:
            entry = self.entries[line["source"]]
            with self.subTest(album=line["source"]):
                self.assertEqual((line["outcome"], line["error"], line["destination"]),
                                 ("applied", None, entry["destination"]))
                record = line["record"]
                self.assertEqual(set(record), {"tags", "moves", "created", "deleted"})
                # The record is what rollback reads, so it has to be the
                # write's own: every track's move, and its tags from before.
                for planned in entry["files"]:
                    self.assertIn([planned["source"], planned["destination"], "library"], record["moves"])
                    self.assertEqual(record["tags"].get(planned["destination"]), planned["before"])

    def test_each_album_is_in_applied_jsonl_before_the_next_album_is_written(self):
        # A log written once at the end is empty after a crash on album 900,
        # and rollback then has nothing to undo the first 899 with. The stub
        # copies the log each time a write asks it about foobar2000, which
        # happens before that write touches anything.
        seen = self.lib.log_as_seen_by_systemctl()
        self.assertIn([FIRST], seen, f"the log as each write began: {seen}")
        self.assertIn([FIRST, ACCEPTED], seen, f"the log as each write began: {seen}")
        self.assertLess(seen.index([FIRST]), seen.index([FIRST, ACCEPTED]))


class WhileFoobarRuns(_Case):
    def test_nothing_is_written_and_the_command_that_stops_foobar_is_named(self):
        lib = new_library(self)
        lib.add(FIRST, 1)
        lib.add(LAST, 2)
        lib.identify()
        self.assertEqual(lib.states(), {FIRST: "auto", LAST: "auto"})
        before = builders.tree(lib.root)

        code, out, err = lib.apply(running=True)

        self.assertEqual(code, 1)
        self.assertIn(STOP_FOOBAR, out + err)
        self.assertEqual(builders.tree(lib.root), before)
        self.assertEqual(builders.tree(lib.extras), {})
        # Each album's own write would refuse as well, and log a failure per
        # album. Apply has to find out once, first, and log nothing.
        self.assertEqual(lib.log(), [])
        calls = lib.calls_made()
        self.assertTrue(calls, "systemctl was never asked whether foobar2000 is running")
        for call in calls:
            self.assertTrue(call.startswith("is-active"), f"systemctl was run with: {call}")


class WhenAnAlbumFails(_Case):
    def setUp(self):
        self.lib = new_library(self)
        self.lib.add(FIRST, 1)
        self.lib.add(LAST, 2)
        self.lib.identify()
        self.assertEqual(self.lib.states(), {FIRST: "auto", LAST: "auto"})
        self.entries = self.lib.entries()

    def test_an_album_whose_write_fails_is_reported_and_the_next_album_is_still_written(self):
        # A folder nothing can be renamed in: the write reads everything,
        # then fails on its first move, and 001 puts the album back.
        folder = self.lib.root / FIRST
        folder.chmod(0o555)
        self.addCleanup(folder.chmod, 0o755)
        before = builders.tree(folder)

        code, _out, err = self.lib.apply()

        self.assertEqual(code, 1)
        self.assertIn(FIRST, err)
        self.assertEqual(builders.tree(folder), before)
        self.assertWrittenAsPlanned(self.lib, self.entries[LAST])
        log = self.lib.log()
        self.assertEqual([(line["source"], line["outcome"]) for line in log],
                         [(FIRST, "failed"), (LAST, "applied")])
        self.assertTrue(log[0]["error"], "the failed line gives no error")
        self.assertEqual(set(log[0]["record"]), {"tags", "moves", "created", "deleted"})

    def test_an_album_changed_on_disk_since_identify_is_refused_and_the_next_album_is_still_written(self):
        # The plan the owner saw is not the plan the album would get now.
        # Writing the new one would apply something nobody looked at.
        (self.lib.root / FIRST / "notes.txt").write_text("added after identify\n")
        before = builders.tree(self.lib.root / FIRST)

        code, _out, err = self.lib.apply()

        self.assertEqual(code, 1)
        self.assertIn(FIRST, err)
        self.assertEqual(builders.tree(self.lib.root / FIRST), before)
        self.assertWrittenAsPlanned(self.lib, self.entries[LAST])
        self.assertApplied(self.lib, [LAST])


class Limit(_Case):
    def test_limit_2_writes_the_first_two_applicable_albums_by_path_and_a_later_run_writes_only_the_rest(self):
        lib = new_library(self)
        lib.add(LAST, 3)
        lib.add(ACCEPTED, 2, exact=False)
        lib.add(FIRST, 1)
        lib.identify()
        lib.decide({ACCEPTED: lib.accept(ACCEPTED)})
        entries = lib.entries()
        self.assertEqual(lib.states(), {FIRST: "auto", ACCEPTED: "held", LAST: "auto"})
        before = builders.tree(lib.root / LAST)

        # 2, not 1: the first album is FIRST whether apply goes by path or
        # runs the auto albums before the accepted ones. The second tells
        # them apart.
        code, _out, err = lib.apply(limit=2)

        self.assertEqual(code, 0, err)
        self.assertWrittenAsPlanned(lib, entries[FIRST])
        self.assertWrittenAsPlanned(lib, entries[ACCEPTED])
        self.assertEqual(builders.tree(lib.root / LAST), before)
        self.assertApplied(lib, [FIRST, ACCEPTED])

        # The canary, then the rest (`plan.md`). The first two are already
        # at their destinations, so an apply that tried them again would
        # find their sources gone and fail them.
        done = {key: builders.tree(lib.root / entries[key]["destination"]) for key in (FIRST, ACCEPTED)}
        code, _out, err = lib.apply()

        self.assertEqual(code, 0, err)
        self.assertWrittenAsPlanned(lib, entries[LAST])
        self.assertEqual([line["source"] for line in lib.log()], [FIRST, ACCEPTED, LAST])
        for key, tree in done.items():
            self.assertEqual(builders.tree(lib.root / entries[key]["destination"]), tree, key)


class AnAlbumWrittenInPlace(_Case):
    """A job that tagged an album where it lay can still write it again.

    The album's folder is already the name its plan gives it, so its
    `applied` line has the same `source` as the re-planned entry. A line in
    `applied.jsonl` stands for the plan it wrote, not for the album forever:
    the same plan is never written twice, and a new one is.

    Each case runs once on the line as this apply writes it and once on the
    line as job `t1` wrote it before this change, which is what the box has:
    682 of `t1`'s 875 lines are in place.
    """

    IN_PLACE = "A/Alpha/(2010) First"
    LINE_AS_T1_WROTE_IT = ("destination", "error", "outcome", "record", "source")

    def written_in_place(self, as_t1_wrote_it: bool) -> Library:
        lib = new_library(self)
        found, group = release(1, "Alpha", "First", ["One", "Two"])
        lib.catalogue.append((found, group))
        album(lib.root, self.IN_PLACE, ["One", "Two"], release_id=found["id"])
        lib.identify()
        entry = lib.entries()[self.IN_PLACE]
        if (entry["state"], entry["destination"]) != ("auto", self.IN_PLACE):
            raise AssertionError(f"the fixture is not an auto album planned in place: {entry['state']}, "
                                 f"{entry['destination']}")
        code, _out, err = lib.apply()
        if code != 0 or [line["outcome"] for line in lib.log()] != ["applied"]:
            raise AssertionError(f"the first apply did not write the album: {code} {err}")
        if as_t1_wrote_it:
            lines = [{key: line[key] for key in self.LINE_AS_T1_WROTE_IT} for line in lib.log()]
            (lib.job / "applied.jsonl").write_text(
                "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines), encoding="utf-8")
        return lib

    def test_a_second_apply_with_no_new_identify_writes_nothing_and_exits_0(self):
        # The resume rule: an apply that stopped trusting an in-place line
        # rebuilds the plan over tags it already wrote, finds it changed, and
        # refuses the album with exit 1.
        for as_t1_wrote_it in (False, True):
            with self.subTest(as_t1_wrote_it=as_t1_wrote_it):
                lib = self.written_in_place(as_t1_wrote_it)
                before, lines = builders.tree(lib.root), lib.log()

                code, _out, err = lib.apply()

                self.assertEqual((code, err), (0, ""))
                self.assertEqual(lib.log(), lines)
                self.assertEqual(builders.tree(lib.root), before)

    def test_a_new_identify_that_plans_it_auto_to_another_release_is_written(self):
        # The release id is changed on disk to stand in for a re-judge: apply
        # sees the same thing either way, an auto entry for another release
        # under a key the log already has. Today it is skipped with exit 0.
        for as_t1_wrote_it in (False, True):
            with self.subTest(as_t1_wrote_it=as_t1_wrote_it):
                lib = self.written_in_place(as_t1_wrote_it)
                other, group = release(2, "Alpha", "Second", ["One", "Two"])
                lib.catalogue.append((other, group))
                for path in (lib.root / self.IN_PLACE).glob("*.flac"):
                    track = FLAC(path)
                    track["musicbrainz_albumid"] = [other["id"]]
                    track.save()
                lib.identify()
                entry = lib.entries()[self.IN_PLACE]
                self.assertEqual((entry["state"], entry["release_id"]), ("auto", other["id"]))

                code, _out, err = lib.apply()

                self.assertEqual((code, err), (0, ""))
                self.assertWrittenAsPlanned(lib, entry)
                self.assertApplied(lib, [self.IN_PLACE, self.IN_PLACE])


class Cli(_Case):
    def test_batch_apply_on_the_command_line_takes_the_job_limit_extras_live_root_and_systemctl(self):
        lib = new_library(self)
        lib.add(FIRST, 1)
        lib.add(LAST, 2)
        # A video goes to the extras folder, which is the only way to see
        # that `--extras` reached the write.
        (lib.root / FIRST / "video.mkv").write_bytes(b"not really a video")
        lib.identify()
        entries = lib.entries()
        self.assertEqual(lib.states(), {FIRST: "auto", LAST: "auto"})
        self.assertEqual([Path(rel).name for rel in entries[FIRST]["extras"]], ["video.mkv"])
        before = builders.tree(lib.root / LAST)
        systemctl = lib.systemctl(running=False)

        # The CLI builds the real transport. Identify left the cache warm, so
        # nothing may reach it.
        with mock.patch.object(mb, "default_transport", lib.refuse), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                code = main(["batch", "apply", "--job", str(lib.job), "--limit", "1",
                             "--memory", str(lib.memory), "--extras", str(lib.extras),
                             "--live-root", str(lib.root), "--systemctl", str(systemctl)])
            except SystemExit as exc:
                # argparse refusing the subcommand; its message is in `err`.
                code = exc.code

        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(lib.asked, [])
        self.assertWrittenAsPlanned(lib, entries[FIRST])
        self.assertEqual(builders.tree(lib.root / LAST), before)
        self.assertEqual([p for p in builders.tree(lib.extras) if p.endswith("video.mkv")],
                         [f"{entries[FIRST]['destination']}/video.mkv"])
        # With the default live root, /srv/music/library, the temp library is
        # not live and the stub is never asked.
        self.assertTrue(lib.calls_made(), "the stub systemctl was never asked")


#: A release MusicBrainz does not have: the fake answers 404 for it.
UNKNOWN_RELEASE = "6f1a2b3c-0000-4000-8000-000199999999"


class AnAcceptNotWritten(_Case):
    def test_an_accepted_album_identify_could_not_plan_is_reported_by_apply_with_exit_1(self):
        # The owner accepted a release MusicBrainz answers 404 for, so identify
        # holds the album as an `error` with no plan. Apply cannot write it,
        # and the owner said yes to it, so saying nothing and exiting 0 reads
        # as done. It is the only album, so a run with nothing to write still
        # has to say so.
        lib = new_library(self)
        lib.add(ACCEPTED, 4, exact=False)
        lib.identify()
        lib.decide({ACCEPTED: {"action": "accept", "release_id": UNKNOWN_RELEASE,
                               "edits": {}, "game": None}})
        self.assertIn("error", {hold["kind"] for hold in lib.entries()[ACCEPTED]["holds"]},
                      "the fixture did not end as an error hold")
        before = builders.tree(lib.root)

        code, _out, err = lib.apply()

        self.assertEqual(code, 1, err)
        self.assertIn(ACCEPTED, err)
        self.assertEqual(builders.tree(lib.root), before)


SCORE = "S/Score/Sixth [rip]"


class AnAcceptWaitingOnItsSoundtrackChoice(_Case):
    def test_the_other_accepted_albums_are_written_and_the_one_with_no_game_is_reported_with_exit_1(self):
        # SCORE is a Soundtrack-type release, held for the
        # owner's soundtrack choice, and the owner accepted it with no
        # `game`. The rest of the file still goes. SCORE is reported, not
        # written: written, it would carry no choice at all.
        lib = new_library(self)
        lib.add(FIRST, 1)
        lib.add(ACCEPTED, 4, exact=False)
        lib.add(SCORE, 7)
        found, group = lib.catalogue[-1]
        group["secondary-types"] = found["release-group"]["secondary-types"] = ["Soundtrack"]
        lib.identify()
        if not lib.entries()[SCORE]["game_choice"]:
            raise AssertionError(f"the fixture is not held for a soundtrack choice: {lib.entries()[SCORE]}")
        lib.decide({ACCEPTED: lib.accept(ACCEPTED), SCORE: lib.accept(SCORE)})
        before = builders.tree(lib.root / SCORE)

        code, _out, err = lib.apply()

        self.assertEqual(code, 1, err)
        self.assertApplied(lib, [FIRST, ACCEPTED])
        self.assertIn(f"{SCORE}: accepted but its plan cannot be written; not applied", err)
        self.assertEqual(builders.tree(lib.root / SCORE), before)


class ReopenedInMemory(_Case):
    """`memory.json`'s `reopened` list, which apply alone takes albums off."""

    def test_only_an_applied_accept_takes_its_album_off_the_reopened_list(self):
        # ACCEPTED was reopened before this job's identify, so it is held and
        # the owner accepts it. FIRST was auto when this job was planned, and
        # another job's `--reopen` listed it afterwards: applying this job's
        # auto plan is not the correction the owner reopened it for.
        lib = new_library(self)
        lib.add(FIRST, 1)
        lib.add(ACCEPTED, 2)
        lib.memory.write_text(json.dumps({"edits": {}, "composers": {}, "reopened": [ACCEPTED]}))
        lib.identify()
        lib.decide({ACCEPTED: lib.accept(ACCEPTED)})
        self.assertEqual(lib.states(), {FIRST: "auto", ACCEPTED: "held"})
        memory = json.loads(lib.memory.read_text())
        memory["reopened"] = sorted(memory["reopened"] + [FIRST])
        lib.memory.write_text(json.dumps(memory))

        code, _out, err = lib.apply()

        self.assertEqual(code, 0, err)
        self.assertApplied(lib, [FIRST, ACCEPTED])
        self.assertEqual(json.loads(lib.memory.read_text())["reopened"], [FIRST])


class LimitArgument(_Case):
    def test_a_limit_of_0_or_below_is_a_bad_argument_and_nothing_is_written(self):
        # 0 would be a run that silently does nothing, and -1 would be
        # "all but the last" by the way a list slices.
        lib = new_library(self)
        lib.add(FIRST, 1)
        lib.add(LAST, 2)
        lib.identify()
        self.assertEqual(lib.states(), {FIRST: "auto", LAST: "auto"})
        systemctl = lib.systemctl(running=False)
        for limit in ("0", "-1"):
            with self.subTest(limit=limit):
                before = builders.tree(lib.base)
                with mock.patch.object(mb, "default_transport", lib.refuse), \
                        contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()) as err:
                    try:
                        code = main(["batch", "apply", "--job", str(lib.job), "--limit", limit,
                                     "--memory", str(lib.memory), "--extras", str(lib.extras),
                                     "--live-root", str(lib.root), "--systemctl", str(systemctl)])
                    except SystemExit as exc:
                        code = exc.code

                self.assertEqual(code, 2, err.getvalue())
                self.assertIn("--limit", err.getvalue())
                self.assertEqual(builders.tree(lib.base), before)


class NoPlan(_Case):
    def test_apply_on_a_job_identify_never_planned_exits_1_naming_batch_identify(self):
        lib = new_library(self)
        lib.add(FIRST, 1)
        before = builders.tree(lib.job)

        code, _out, err = lib.apply()

        self.assertEqual(code, 1, err)
        self.assertIn("musiclib batch identify", err)
        self.assertEqual(builders.tree(lib.job), before)


if __name__ == "__main__":
    unittest.main()
