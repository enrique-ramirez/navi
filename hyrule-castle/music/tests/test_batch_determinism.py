"""The same job planned twice gives the same bytes, and a job over a library the batch wrote proposes nothing.

Determinism follows 001's `tests.test_determinism`: identify runs in child
processes with different `PYTHONHASHSEED`s, because a second run in the same
process shares the first one's seed, and a list built by walking a set comes
out in the same order both times. Both children read a warm cache through a
transport that notes every request, and neither may make one. The library
fills every map an entry has: two discs, residue, a file kept, one deleted and
one moved to the extras root, a held album with a candidate, a collision, an
unidentified album, a memory with an edit and a soundtrack choice, and a
`decisions.json` with an accept (with an edit and a `game`), a repoint and a
skip. The job is the same job at the same path both times. Copies at other
paths need not match, because `root` is in `plan.json`.

The second and third cases run the batch the way the owner does: identify,
decide, identify again to fold the decisions in, apply, and then a new job
over the library as apply left it, with the same `memory.json` and no
decisions. The fakes and the job layout are `tests.test_batch_identify`'s
and `tests.test_batch_apply`'s; the soundtrack releases are
`tests.test_soundtracks`'s.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

from tests import builders
from tests.test_batch_apply import Library, new_library
from tests.test_batch_identify import TONE_MS, Services, album, release, run_identify
from tests.test_memory import entries, key_of
from tests.test_soundtracks import SOUNDTRACK, VGM, soundtrack

HERE = Path(__file__).resolve().parents[1]

#: Two seeds known to walk small sets of strings in different orders.
SEEDS = ("1", "2")

TITLES = ["One", "Two"]

# The library. Path order differs from the order they are made in.
DISCS = "C/Cure/Disintegration [rip]"
EXTRAS = "E/Eel/Tide [rip]"
FILM = "F/Fennel/Harbour [rip]"
GAME = "S/Sakura/Overworld [rip]"
REVIEW = "R/Rook/Off [rip]"
REPOINTED = "P/Pike/Swap [rip]"
PAIR = ("D/Dace/Twice [flac]", "D/Dace/Twice [rip]")
UNIDENTIFIED = "U/Unknown/Nothing [rip]"

DISC_TITLES = (["Plainsong", "Pictures of You"], ["Prayers for Rain"])

#: The edit the memory holds before the first job, on disc 2 of DISCS.
REMEMBERED_TITLE = "Rain Again"
#: The edit the owner makes on GAME in `decisions.json`.
DECIDED_TITLE = "Second Wind"

#: What the batch applies in the first job: the auto albums and the accepted one.
APPLIED = (DISCS, EXTRAS, FILM, GAME)


def two_discs(number: int, key: str) -> tuple[dict, dict]:
    """A two-medium release for the rip at `key`, matching `two_disc_rip`'s files to the second."""
    artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
    found, group = release(number, artist, title, DISC_TITLES[0])
    second = builders.mb_medium(2, DISC_TITLES[1], credit=found["artist-credit"])
    for track in second["tracks"]:
        track["length"] = TONE_MS
        track["recording"]["length"] = TONE_MS
    found["media"].append(second)
    return found, group


def two_disc_rip(root: Path, key: str, release_id: str) -> Path:
    """`tests.test_batch_identify.album` over two discs, in CD1 and CD2, with ripper residue on every track.

    Three residue keys on each file, so a removal list built from a set has
    an order to lose.
    """
    base = root / key
    for disc, titles in enumerate(DISC_TITLES, start=1):
        folder = base / f"CD{disc}"
        folder.mkdir(parents=True)
        for number, title in enumerate(titles, start=1):
            path = folder / f"{number:02d} {title.lower()}.flac"
            shutil.copyfile(builders.FIXTURES / "tone.flac", path)
            fields = {"title": [title.lower()], "artist": [key.split("/")[1]],
                      "album": [key.split("/")[2]], "date": ["1989"], "release id": [release_id]}
            builders.write_tags(path, builders.picard_tags("flac", fields, track=(number, len(titles)),
                                                           disc=(disc, len(DISC_TITLES))), v2_version=4)
            builders.write_tags(path, {"encoder": "LAME 3.100", "ripping tool": "EAC",
                                       "url": "http://example.org/rip"})
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


class Catalogue:
    """Every release the library is tagged with, plus the one the owner pastes for REPOINTED."""

    discs = two_discs(1, DISCS)
    extras = release(2, "Eel", "Tide", TITLES)
    review = release(3, "Rook", "Off", TITLES, exact=False)
    repointed = release(4, "Pike", "Swap", TITLES, exact=False)
    #: Fits the files to the second, so only the repoint holds it.
    pasted = release(5, "Pike", "Swap (Remaster)", TITLES)
    pair = release(6, "Dace", "Twice", TITLES)
    game = soundtrack(7, GAME)
    film = soundtrack(8, FILM)


def release_id(pair: tuple[dict, dict]) -> str:
    return pair[0]["id"]


def build(lib: Library) -> None:
    """The library under `lib.root`, the memory before any job, and the catalogue the fake answers from."""
    c = Catalogue
    lib.catalogue.extend([c.discs, c.extras, c.review, c.repointed, c.pasted, c.pair, c.game, c.film])
    two_disc_rip(lib.root, DISCS, release_id(c.discs))
    # A file the write keeps, one it deletes and one it moves to the extras root.
    extras = album(lib.root, EXTRAS, TITLES, release_id=release_id(c.extras))
    (extras / "rip.log").write_text("Exact Audio Copy V1.6 extraction logfile\n")
    (extras / "notes.txt").write_text("Bought at Rough Trade.\n")
    (extras / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    (extras / "Making of.mkv").write_bytes(b"\x1aE\xdf\xa3 a video")
    album(lib.root, REVIEW, TITLES, release_id=release_id(c.review))
    album(lib.root, REPOINTED, TITLES, release_id=release_id(c.repointed))
    for key in PAIR:
        album(lib.root, key, TITLES, release_id=release_id(c.pair))
    album(lib.root, GAME, TITLES, release_id=release_id(c.game))
    album(lib.root, FILM, TITLES, release_id=release_id(c.film))
    album(lib.root, UNIDENTIFIED, TITLES)
    lib.memory.parent.mkdir(parents=True, exist_ok=True)
    lib.memory.write_text(json.dumps({
        "edits": {release_id(c.discs): {"2-1": {"title": [REMEMBERED_TITLE]}}},
        # Chosen in an earlier job, so FILM is settled and applied with no decision.
        "soundtracks": {release_id(c.film): SOUNDTRACK},
        "reopened": [],
    }), encoding="utf-8")


def decisions() -> dict:
    """`decisions.json`'s albums: an accept with an edit and a game choice, a repoint by URL, a skip of a held album.

    The skip is of a held album, never an auto one: a skip is not
    remembered, so a skipped auto album would be auto again in the next job,
    and the second job would then have something to propose.
    """
    return {
        GAME: {"action": "accept", "release_id": release_id(Catalogue.game),
               "edits": {"1-2": {"title": [DECIDED_TITLE]}}, "game": VGM},
        REPOINTED: {"action": "repoint",
                    "release": f"https://musicbrainz.org/release/{release_id(Catalogue.pasted)}"},
        REVIEW: {"action": "skip"},
    }


def apply_job(lib: Library, job: Path) -> tuple[int, str, str]:
    """`batch.apply.run` on `job` over `lib`'s library, foobar2000 stopped and the network refused."""
    from musiclib.batch.apply import run
    from musiclib.batch.job import Job

    out, err = io.StringIO(), io.StringIO()
    code = run(Job(job), lib.memory, extras_root=lib.extras, live_root=lib.root,
               systemctl=str(lib.systemctl(False)), transport=lib.refuse, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def log(job: Path) -> list[dict]:
    path = job / "applied.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def applied_sources(job: Path) -> list[str]:
    return [line["source"] for line in log(job) if line["outcome"] == "applied"]


def identify_second_job(lib: Library) -> tuple[Path, tuple[int, str, str], dict]:
    job = lib.base / ".musiclib" / "jobs" / "j2"
    said = run_identify(lib.root, job, lib.memory, Services(lib.catalogue))
    return job, said, entries(job) if (job / "plan.json").exists() else {}


def read_memory(lib: Library) -> dict:
    return json.loads(lib.memory.read_text(encoding="utf-8")) if lib.memory.exists() else {}


#: What a child process runs: `batch identify` on one job with a transport
#: that answers nothing, then the URLs it was asked for, written to a file.
#: A request the transport refuses surfaces in `plan.json` only as an `error`
#: hold, so the list is written out for the parent to check on its own.
_CHILD = r"""
import json, sys
from pathlib import Path

from musiclib import mb
from tests.test_batch_identify import run_identify

mb._MIN_INTERVAL = 0.0
args = json.loads(sys.argv[1])
asked = []

def offline(url, headers):
    asked.append(url)
    raise AssertionError(f"a request with a warm cache: {url}")

code, out, err = run_identify(Path(args["root"]), Path(args["job"]), Path(args["memory"]), offline)
Path(args["result"]).write_text(json.dumps({"code": code, "out": out, "err": err, "asked": asked}))
"""


class Determinism(unittest.TestCase):
    """One job, decided and folded in-process, then identified again by two children under two seeds."""

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        build(lib)
        # The first run is cold. The second folds the decisions in and fetches
        # the pasted release, so every later run has a warm cache.
        lib.identify()
        lib.decide(decisions())
        cls.runs = [cls.run_child(seed) for seed in SEEDS]

    @classmethod
    def run_child(cls, seed: str) -> dict:
        """`batch identify` on the job in a child hashing strings with `seed`: its result and the job's bytes."""
        result = cls.lib.base / f"child {seed}.json"
        args = {"root": str(cls.lib.root), "job": str(cls.lib.job), "memory": str(cls.lib.memory),
                "result": str(result)}
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1")
        done = subprocess.run([sys.executable, "-c", _CHILD, json.dumps(args)], cwd=HERE, env=env,
                              capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            raise AssertionError(f"the child process failed:\n{done.stderr[-3000:]}")
        run = json.loads(result.read_text())
        run["plan"] = (cls.lib.job / "plan.json").read_bytes()
        run["review"] = (cls.lib.job / "review.html").read_bytes()
        return run

    def test_identify_twice_on_one_job_gives_byte_identical_plan_json(self):
        first, second = self.runs
        # Equal bytes prove nothing about a map the fixture never filled, so
        # each is checked for content first.
        doc = json.loads(first["plan"])
        by_source = {entry["source"]: entry for entry in doc["albums"]}
        self.assertEqual(sorted(by_source), sorted([DISCS, EXTRAS, FILM, GAME, REVIEW, REPOINTED,
                                                    *PAIR, UNIDENTIFIED]))
        filled = {
            "two discs": any(f["position"] == "2-1" for f in by_source[DISCS]["files"]),
            "residue": by_source[DISCS]["residue"],
            "deletions": by_source[EXTRAS]["deletions"],
            "extras": by_source[EXTRAS]["extras"],
            "a held album's candidates": by_source[REVIEW]["candidates"],
            "a collision": all("collision" in {h["kind"] for h in by_source[key]["holds"]} for key in PAIR),
            "a repoint": by_source[REPOINTED]["decision"] == "repoint",
            "a skip": by_source[REVIEW]["decision"] == "skip",
            "an accept": by_source[GAME]["decision"] == "accept",
            "a remembered edit": (by_source[DISCS]["inputs"] or {}).get("edits"),
            "a decided edit": (by_source[GAME]["inputs"] or {}).get("edits"),
            "a remembered soundtrack choice": by_source[FILM]["state"] == "auto",
        }
        self.assertEqual([name for name, value in filled.items() if not value], [],
                         "the job does not exercise these; the byte comparison would prove nothing about them")
        self.assertEqual(first["plan"], second["plan"])

    def test_identify_twice_on_one_job_gives_byte_identical_review_html(self):
        first, second = self.runs
        self.assertGreater(len(first["review"]), 0, "review.html is empty")
        self.assertEqual(first["review"], second["review"])

    def test_identify_on_a_warm_job_makes_no_request(self):
        # A run that went to the network for something the first run never
        # stored could still give equal bytes here, and differ on the box.
        for seed, run in zip(SEEDS, self.runs):
            with self.subTest(seed=seed):
                self.assertEqual(run["code"], 0, run["err"])
                self.assertEqual(run["asked"], [])


class TheSecondTime(unittest.TestCase):
    """Job `j1` identified, decided, folded in and applied; then `j2` over the written library, no decisions.

    The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        build(lib)
        lib.identify()
        cls.first = lib.entries()
        lib.decide(decisions())
        cls.decided = lib.entries()
        cls.applied = lib.apply()

        cls.j2, cls.identified, cls.again = identify_second_job(lib)
        cls.before = builders.tree(lib.root), builders.tree(lib.extras)
        cls.second_apply = apply_job(lib, cls.j2)
        cls.after = builders.tree(lib.root), builders.tree(lib.extras)

    def assertFirstJobApplied(self) -> None:
        """The first job wrote exactly APPLIED, each of which it planned to change."""
        self.assertEqual(sorted(applied_sources(self.lib.job)), sorted(APPLIED),
                         f"the first job applied something else; apply said: {self.applied}")
        for key in APPLIED:
            # Otherwise "no change" in the second job is the first job never
            # having had anything to do.
            self.assertNotEqual(self.first[key]["changes"], [], key)

    def test_every_album_the_batch_applied_plans_no_change_in_a_new_job(self):
        self.assertFirstJobApplied()
        for key in APPLIED:
            destination = self.decided[key]["destination"]
            with self.subTest(album=key):
                self.assertIn(destination, self.again, f"not in the new job; identify said: {self.identified}")
                entry = self.again[destination]
                self.assertEqual((entry["changes"], entry["state"], entry["holds"]), ([], "unchanged", []))

    def test_an_edit_the_batch_applied_is_planned_again_and_is_already_on_disk(self):
        # The case above also passes for an engine that forgot the edits,
        # if the write forgot them too. Here the new job's plan carries each
        # edit, and still proposes nothing, so the files already have it.
        # DISCS's edit came from the memory, GAME's from a decision.
        self.assertFirstJobApplied()
        cases = [(DISCS, "2-1", "title", REMEMBERED_TITLE), (GAME, "1-2", "title", DECIDED_TITLE)]
        for key, position, field, value in cases:
            with self.subTest(album=key):
                entry = self.again.get(self.decided[key]["destination"])
                self.assertIsNotNone(entry, f"{key} is not in the new job")
                self.assertEqual(entry["fields"][position][field], [value])
                self.assertEqual(entry["changes"], [])
        game = self.again[self.decided[GAME]["destination"]]
        self.assertEqual([game["fields"][p]["genre"][0] for p in ("1-1", "1-2")], [VGM, VGM])

    def test_a_new_job_with_no_decisions_plans_no_album_auto_and_prints_no_auto_count(self):
        code, out, err = self.identified
        self.assertEqual(code, 0, err)
        self.assertTrue(self.again, f"the new job planned nothing: {err}")
        self.assertEqual({k: e["state"] for k, e in self.again.items() if e["state"] == "auto"}, {})
        self.assertNotIn("state auto:", out)
        # The printed counts are there at all, or the line above is vacuous.
        self.assertIn("state unchanged:", out)

    def test_applying_a_new_job_with_no_decisions_writes_nothing(self):
        code, _out, err = self.second_apply
        # Exit 0 is apply having run and chosen nothing. A refusal also
        # writes nothing, and would pass the rest of this case.
        self.assertEqual(code, 0, err)
        self.assertEqual(applied_sources(self.j2), [])
        root_before, extras_before = self.before
        root_after, extras_after = self.after
        self.assertEqual(root_after, root_before)
        self.assertEqual(extras_after, extras_before)


# The rips for AFixedNameTheSecondTime. Neither source folder starts with
# `.`, so the first job's walk finds them whatever it does with dot folders
# (criterion 26); only the name the engine gives them is under test.
DOTTED = "3/38 Special/Wild-Eyed Southern Boys [rip]"
ACCENTED = "C/Cafe Tacvba/Reves [rip]"

DOT_ARTIST = ".38 Special"

# ACCENTED's release as MusicBrainz might send it (letter plus combining acute,
# U+0301) and the same text composed, as the engine must write it. Escapes,
# because an editor on macOS may normalise a literal without saying so.
NFD_ARTIST = "Cafe\u0301 Tacvba"
NFD_TITLE = "Re\u0301ves"
NFD_TRACKS = ["E\u0301te\u0301", "Two"]
NFC_ARTIST = "Caf\u00e9 Tacvba"
NFC_TITLE = "R\u00e9ves"
NFC_TRACKS = ["\u00c9t\u00e9", "Two"]


def written_tracks(root: Path) -> dict[str, dict]:
    return {path.relative_to(root).as_posix(): builders.read_tags(path) for path in sorted(root.rglob("*.flac"))}


class AFixedNameTheSecondTime(unittest.TestCase):
    """`.38 Special` and decomposed text applied by `j1`, then `j2` over the written library.

    The first job has to change both albums, or "no change" in the second
    proves nothing: DOTTED moves to `#/_38 Special` and ACCENTED's tags go
    from the rip's loose text to MusicBrainz's, composed. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        dotted = release(1, DOT_ARTIST, "Wild-Eyed Southern Boys", TITLES)
        accented = release(2, NFD_ARTIST, NFD_TITLE, NFD_TRACKS)
        lib.catalogue.extend([dotted, accented])
        album(lib.root, DOTTED, TITLES, release_id=release_id(dotted))
        # The rip's titles equal the release's, still decomposed, so the files
        # match the release as well as DOTTED's do.
        album(lib.root, ACCENTED, NFD_TRACKS, release_id=release_id(accented))
        lib.identify()
        cls.first = lib.entries()
        cls.applied = lib.apply()
        # Read now, before the second job runs, so a case sees what the
        # first apply wrote and nothing a later step did to it.
        cls.written = written_tracks(lib.root)
        _, cls.identified, cls.again = identify_second_job(lib)

    def destination(self, key: str) -> str:
        """Where the first job put `key`, after checking it applied `key` at all."""
        self.assertIn(key, applied_sources(self.lib.job), f"the first job did not apply {key}: {self.applied}")
        return self.first[key]["destination"]

    def tracks_in(self, destination: str) -> list[dict]:
            return [tags for path, tags in self.written.items() if path.rpartition("/")[0] == destination]

    def assertProposesNothing(self, destination: str) -> None:
        self.assertIn(destination, self.again, f"not in the new job; identify said: {self.identified}")
        entry = self.again[destination]
        # `changes` carries every move, tag rewrite, image and deletion.
        self.assertEqual((entry["state"], entry["holds"], entry["changes"]), ("unchanged", [], []))

    def test_the_first_job_files_dot_38_special_under_hash_underscore_and_keeps_the_dot_in_the_tag(self):
        destination = self.destination(DOTTED)
        self.assertEqual(destination.split("/")[:2], ["#", "_38 Special"])
        tracks = self.tracks_in(destination)
        self.assertEqual(len(tracks), len(TITLES), f"{destination} is not on disk as planned: {list(self.written)}")
        for number, tags in enumerate(tracks, start=1):
            with self.subTest(track=number):
                self.assertEqual((tags.get(key_of("artist")), tags.get(key_of("albumartist"))),
                                 ([DOT_ARTIST], [DOT_ARTIST]))
        # The rip's own folder is emptied, so the new job sees only the renamed one.
        self.assertEqual([path for path in self.written if path.startswith(DOTTED + "/")], [])

    def test_the_first_job_writes_decomposed_musicbrainz_text_to_the_tags_composed(self):
        destination = self.destination(ACCENTED)
        tracks = self.tracks_in(destination)
        self.assertEqual(len(tracks), len(NFC_TRACKS), f"{destination} is not on disk as planned: {list(self.written)}")
        for number, (tags, title) in enumerate(zip(tracks, NFC_TRACKS), start=1):
            with self.subTest(track=number):
                self.assertEqual((tags.get(key_of("artist")), tags.get(key_of("album")), tags.get(key_of("title"))),
                                 ([NFC_ARTIST], [NFC_TITLE], [title]))
                # Not only the three above: an artist sort name or a
                # release-group title copied from MusicBrainz is text too.
                decomposed = [value for values in tags.values() for value in values
                              if isinstance(value, str) and not unicodedata.is_normalized("NFC", value)]
                self.assertEqual(decomposed, [])

    def test_a_new_job_proposes_no_change_to_hash_underscore_38_special_or_to_composed_text(self):
        for key in (DOTTED, ACCENTED):
            with self.subTest(album=key):
                self.assertProposesNothing(self.destination(key))


FIRST = "A/Alpha/First [rip]"
SECOND = "B/Beta/Second [rip]"
THIRD = "C/Gamma/Third [rip]"


class Reopen(unittest.TestCase):
    """Three albums applied in `j1`. `j2` reopens two; `j3` runs without `--reopen`, then accepts one; `j4` after.

    FIRST is reopened by its absolute path, SECOND by its path relative to
    ROOT, and THIRD is never reopened. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_library(cls)
        for number, key in enumerate((FIRST, SECOND, THIRD), start=1):
            lib.add(key, number)
        lib.identify()
        cls.first = lib.entries()
        cls.applied = lib.apply()
        cls.dest = {key: entry["destination"] for key, entry in cls.first.items()}

        jobs = lib.base / ".musiclib" / "jobs"
        services = Services(lib.catalogue)
        # Unresolved: on macOS the temp folder sits under a symlink, as a
        # path typed on the box might.
        reopen = (str(lib.root / cls.dest[FIRST]), cls.dest[SECOND])
        cls.j2 = run_identify(lib.root, jobs / "j2", lib.memory, services, reopen), entries(jobs / "j2")
        cls.memory_after_reopen = read_memory(lib)

        j3 = jobs / "j3"
        cls.j3 = run_identify(lib.root, j3, lib.memory, services), entries(j3)
        accepted = cls.j3[1].get(cls.dest[FIRST], {})
        (j3 / "decisions.json").write_text(json.dumps({"job": "j3", "albums": {cls.dest[FIRST]: {
            "action": "accept", "release_id": accepted.get("release_id"), "edits": {}, "game": None}}}),
            encoding="utf-8")
        cls.j3_folded = run_identify(lib.root, j3, lib.memory, services)
        cls.j3_apply = apply_job(lib, j3)
        cls.j3_applied = applied_sources(j3)
        cls.memory_after_accept = read_memory(lib)

        cls.j4 = run_identify(lib.root, jobs / "j4", lib.memory, services), entries(jobs / "j4")

    def assertReopened(self, planned: dict, key: str) -> None:
        entry = planned.get(self.dest[key])
        self.assertIsNotNone(entry, f"{self.dest[key]} is not in the job")
        # Held for being reopened and nothing else, with nothing to change:
        # the album is exactly as the batch wrote it.
        self.assertEqual((entry["state"], entry["holds"], entry["changes"]),
                         ("held", [{"kind": "reopened", "detail": ""}], []))

    def assertUnchanged(self, planned: dict, key: str) -> None:
        entry = planned.get(self.dest[key])
        self.assertIsNotNone(entry, f"{self.dest[key]} is not in the job")
        self.assertEqual((entry["state"], entry["holds"], entry["changes"]), ("unchanged", [], []))

    def test_reopen_by_absolute_path_or_path_relative_to_root_holds_an_applied_album_that_plans_no_change(self):
        self.assertEqual(sorted(applied_sources(self.lib.job)), [FIRST, SECOND, THIRD], self.applied)
        _out, planned = self.j2
        for key, given in ((FIRST, "absolute"), (SECOND, "relative to ROOT")):
            with self.subTest(given=given):
                self.assertReopened(planned, key)
        # The control: the same kind of album, not reopened.
        self.assertUnchanged(planned, THIRD)

    def test_a_reopened_album_is_kept_in_the_memory_and_held_by_the_next_job_without_reopen(self):
        # Reopening is how an auto-applied album gets corrected. The
        # correction is decided in a later sitting, from a later identify.
        self.assertEqual(sorted(self.memory_after_reopen.get("reopened", [])),
                         sorted([self.dest[FIRST], self.dest[SECOND]]))
        _out, planned = self.j3
        self.assertReopened(planned, FIRST)
        self.assertReopened(planned, SECOND)
        self.assertUnchanged(planned, THIRD)

    def test_applying_an_accept_of_a_reopened_album_takes_only_that_album_out_of_the_memory(self):
        code, _out, err = self.j3_apply
        self.assertEqual(code, 0, err)
        self.assertEqual(self.j3_applied, [self.dest[FIRST]])
        self.assertEqual(self.memory_after_accept.get("reopened"), [self.dest[SECOND]])
        _out, planned = self.j4
        self.assertUnchanged(planned, FIRST)
        # Still reopened: the owner has not decided it yet.
        self.assertReopened(planned, SECOND)


if __name__ == "__main__":
    unittest.main()
