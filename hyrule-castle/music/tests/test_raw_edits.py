"""Raw edits: an `accept` naming a tag by the file's own key, laid last, checked, remembered.

Besides the neutral fields the page offers, an `accept`'s edits take, per
position, a key of that file's own format (`TCOM` on an MP3, `composer` on a
FLAC, a `----:` atom on an M4A) with a list of values, or `null` to remove
it. The edit is laid after the engine's own tags and after residue, so it
wins, and the plan is then checked like any other: a value `check` rejects
holds the album for validation, naming the key. A key that is a MusicBrainz
ID, a rating, a binary frame or no key the format can hold refuses the whole
`decisions.json`, naming the key. Applied raw edits are remembered by
release and position and laid again by a later job over that release.

Everything runs the real way: rips on disk, `batch identify`, a
`decisions.json` written by hand, identify again, `batch apply`, and a
second job over an untouched copy of the rips with the same memory. The
fakes and the job layout are `tests.test_batch_identify`'s and
`tests.test_batch_apply`'s. The MusicBrainz fake answers every release
lookup, whatever its query, with the plain catalogue release, so the
composer lookup finds no composers and plans nothing for every album here
but the one in `OwnerComposerOverMusicBrainz`.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from musiclib import files
from tests import builders
from tests.test_batch_apply import JOB_ID, Library
from tests.test_batch_identify import Services, no_throttle, release, run_identify

MP3 = "M/Mp3 Band/Record [rip]"
FLAC = "F/Flac Band/Record [rip]"
M4A = "A/Aac Band/Record [rip]"

TITLES = ["One", "Two"]

#: A tag every MP3 rip here carries on both tracks, which no residue rule
#: removes, so it leaves a file only when an edit removes it.
MOOD = "TXXX:MOOD"
MP4_MOOD = "----:com.apple.iTunes:MOOD"


def rip(root: Path, catalogue: list, key: str, number: int, ext: str, titles: list[str] = TITLES,
        extra: dict | None = None) -> str:
    """An album at `root/key` in `ext`, tagged with release `number`, which joins `catalogue`. Its release ID.

    `extra` is raw tags written into every track as well, by the format's own keys.
    """
    artist, title = key.split("/")[1], key.split("/")[2].split(" [")[0]
    found, group = release(number, artist, title, titles)
    catalogue.append((found, group))
    base = root / key
    base.mkdir(parents=True)
    for position, name in enumerate(titles, start=1):
        path = base / f"{position:02d} {name.lower()}.{ext}"
        shutil.copyfile(builders.FIXTURES / f"tone.{ext}", path)
        fields = {"title": [name.lower()], "artist": [artist], "album": [title], "date": ["1989"],
                  "release id": [found["id"]]}
        builders.write_tags(path, builders.picard_tags(ext, fields, track=(position, len(titles)),
                                                       disc=(1, 1)), v2_version=4)
        if extra:
            builders.write_tags(path, extra, v2_version=4)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return found["id"]


def entries(job: Path) -> dict[str, dict]:
    doc = json.loads((job / "plan.json").read_text(encoding="utf-8"))
    return {entry["source"]: entry for entry in doc["albums"]}


def after(entry: dict, position: str) -> dict:
    """The tags the entry plans for the file at `position`."""
    return next(f for f in entry["files"] if f["position"] == position)["after"]


def written(root: Path, entry: dict) -> dict[str, dict[str, list[str]]]:
    """The album apply wrote for `entry`, by position: the tags on disk of each track."""
    return {f["position"]: files.read(root / f["destination"]).tags for f in entry["files"]}


def accept(release_id: str, edits: dict) -> dict:
    return {"action": "accept", "release_id": release_id, "edits": edits, "game": None}


class _Lib(Library):
    """`tests.test_batch_apply.Library`, with the MusicBrainz fake given as a class."""

    services = Services

    def identify(self) -> None:
        run_identify(self.root, self.job, self.memory, self.services(self.catalogue))


def decided_and_applied(case, decisions, services=Services, lay_rips=None) -> None:
    """On `case`: rips laid by `lay_rips`, job j1 identified, decided, applied; then j2 over a fresh copy.

    Sets `lib`, `planned`, `decided`, `code`, `out`, `err`, `remembered` and
    `again` on `case`. `decisions` maps album key to edits, given the
    release IDs `lay_rips` returned.
    """
    tmp = tempfile.TemporaryDirectory()
    case.addClassCleanup(tmp.cleanup)
    base = Path(tmp.name)
    no_throttle(case)

    catalogue: list = []
    rips = base / "rips"
    rips.mkdir()
    ids = lay_rips(rips, catalogue)

    lib = case.lib = _Lib(base)
    lib.services = services
    lib.root.rmdir()
    shutil.copytree(rips, lib.root)
    lib.catalogue = catalogue

    lib.identify()
    case.planned = lib.entries()
    lib.decide({key: accept(ids[key], edits) for key, edits in decisions.items()})
    case.decided = lib.entries()
    case.code, case.out, case.err = lib.apply()
    case.remembered = json.loads(lib.memory.read_text(encoding="utf-8")) if lib.memory.exists() else None
    case.ids = ids

    fresh = base / "fresh" / "library"
    shutil.copytree(rips, fresh)
    again_job = base / ".musiclib" / "jobs" / "j2"
    again_job.mkdir(parents=True)
    run_identify(fresh, again_job, lib.memory, services(catalogue))
    case.again = entries(again_job)


#: The owner's edits, by album. Each album's track 2 carries no edit, so it
#: shows what the engine alone would have planned.
EDITS = {
    MP3: {"1-1": {"TCOM": ["Jane Doe"], MOOD: None}},
    FLAC: {"1-1": {"composer": ["Jane Doe", "John Roe"]}},
    M4A: {"1-1": {MP4_MOOD: ["Calm"]}},
}


def three_formats(root: Path, catalogue: list) -> dict[str, str]:
    return {MP3: rip(root, catalogue, MP3, 1, "mp3", extra={MOOD: "Calm"}),
            FLAC: rip(root, catalogue, FLAC, 2, "flac"),
            M4A: rip(root, catalogue, M4A, 3, "m4a")}


class Written(unittest.TestCase):
    """An MP3, a FLAC and an M4A album, each accepted with raw edits at track 1, applied, then planned again."""

    @classmethod
    def setUpClass(cls):
        decided_and_applied(cls, EDITS, lay_rips=three_formats)
        # Each case reads the plan as a precondition: an album held or
        # refused for a reason of its own would pass or fail every case below
        # for that reason alone.
        for key in EDITS:
            if cls.planned.get(key, {}).get("state") != "auto":
                raise AssertionError(f"{key} is not auto before any decision: {cls.planned.get(key)}")

    def assertDecidedCleanly(self) -> None:
        # A refused decisions.json leaves the first plan standing, with no
        # decision on any album, and every case below would read that plan.
        for key in EDITS:
            entry = self.decided[key]
            self.assertEqual(entry["decision"], "accept", f"{key} was not accepted: {entry}")
            self.assertEqual(entry["holds"], [], f"{key} is held after its edits")

    def test_raw_keys_of_each_files_own_format_are_planned_at_the_edited_position_only(self):
        self.assertDecidedCleanly()
        cases = [(MP3, "TCOM", ["Jane Doe"]), (FLAC, "composer", ["Jane Doe", "John Roe"]),
                 (M4A, MP4_MOOD, ["Calm"])]
        for key, tag, values in cases:
            with self.subTest(album=key, tag=tag):
                self.assertEqual(after(self.decided[key], "1-1").get(tag), values)
                self.assertNotIn(tag, after(self.decided[key], "1-2"))

    def test_null_removes_the_tag_from_the_edited_position_and_the_other_track_keeps_it(self):
        self.assertDecidedCleanly()
        # Track 2 keeping the tag is what shows track 1 lost it to the edit
        # rather than to residue or to the engine dropping it.
        self.assertNotIn(MOOD, after(self.decided[MP3], "1-1"))
        self.assertEqual(after(self.decided[MP3], "1-2").get(MOOD), ["Calm"])

    def test_apply_writes_each_raw_edit_into_the_file_and_removes_the_nulled_tag(self):
        self.assertEqual(self.code, 0, self.out + self.err)
        mp3, flac, m4a = (written(self.lib.root, self.decided[key]) for key in (MP3, FLAC, M4A))
        self.assertEqual(mp3["1-1"].get("TCOM"), ["Jane Doe"])
        self.assertNotIn(MOOD, mp3["1-1"])
        self.assertEqual(mp3["1-2"].get(MOOD), ["Calm"])
        self.assertNotIn("TCOM", mp3["1-2"])
        self.assertEqual(flac["1-1"].get("composer"), ["Jane Doe", "John Roe"])
        self.assertEqual(m4a["1-1"].get(MP4_MOOD), ["Calm"])

    def test_applied_raw_edits_are_remembered_under_their_release_and_position(self):
        self.assertIsNotNone(self.remembered, f"apply wrote no memory.json; it said: {self.out}{self.err}")
        for key, edits in EDITS.items():
            with self.subTest(album=key):
                self.assertEqual(self.remembered.get("edits", {}).get(self.ids[key]), edits)

    def test_a_later_job_over_untouched_rips_lays_every_remembered_raw_edit_again(self):
        mp3 = self.again[MP3]
        self.assertEqual(after(mp3, "1-1").get("TCOM"), ["Jane Doe"])
        self.assertNotIn(MOOD, after(mp3, "1-1"))
        self.assertEqual(after(mp3, "1-2").get(MOOD), ["Calm"])
        self.assertEqual(after(self.again[FLAC], "1-1").get("composer"), ["Jane Doe", "John Roe"])
        self.assertEqual(after(self.again[M4A], "1-1").get(MP4_MOOD), ["Calm"])


LAID_LAST = "L/Last Band/Record [rip]"
OWNER_ARTIST = "Guest Singer"


class LaidOverTheEngine(unittest.TestCase):
    """A raw edit to a key the engine plans itself, and one to a key residue strips."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        no_throttle(cls)
        lib = cls.lib = Library(Path(tmp.name))
        cls.release_id = rip(lib.root, lib.catalogue, LAID_LAST, 1, "mp3")
        lib.identify()
        cls.planned = lib.entries()[LAID_LAST]
        lib.decide({LAID_LAST: accept(cls.release_id, {"1-2": {"TPE1": [OWNER_ARTIST]}})})
        cls.decided = lib.entries()[LAID_LAST]

    def test_a_raw_edit_to_a_tag_the_engine_plans_replaces_the_engines_value(self):
        # The engine plans TPE1 from MusicBrainz's credit, `Last Band`. Laid
        # before the engine's tags, the edit would be overwritten by it.
        self.assertEqual(after(self.planned, "1-2").get("TPE1"), ["Last Band"])
        self.assertEqual(after(self.decided, "1-2").get("TPE1"), [OWNER_ARTIST])
        self.assertEqual(after(self.decided, "1-1").get("TPE1"), ["Last Band"])


HELD = "H/Held Band/Record [rip]"
HELD_TITLES = ["One", "Two", "Three"]

#: One value `check` rejects at each position: a year tag residue strips, a
#: value with stray whitespace, and an MP3 track total kept apart from TRCK.
BAD = {
    "1-1": {"TXXX:YEAR": ["1989"]},
    "1-2": {"TCOM": [" Jane Doe"]},
    "1-3": {"TXXX:TOTALTRACKS": ["3"]},
}
FIXED = {"1-2": {"TCOM": ["Jane Doe"]}}


class HeldForValidation(unittest.TestCase):
    """An MP3 album accepted with values `check` rejects, applied, then accepted again with them fixed."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        no_throttle(cls)
        lib = cls.lib = Library(Path(tmp.name))
        cls.release_id = rip(lib.root, lib.catalogue, HELD, 1, "mp3", HELD_TITLES)
        lib.identify()
        cls.planned = lib.entries()[HELD]
        cls.source_before = builders.tree(lib.root / HELD)

        lib.decide({HELD: accept(cls.release_id, BAD)})
        cls.held = lib.entries()[HELD]
        cls.apply_code, cls.apply_out, cls.apply_err = lib.apply()
        cls.source_after_apply = builders.tree(lib.root / HELD)
        cls.memory_after_apply = lib.memory.exists()

        lib.decide({HELD: accept(cls.release_id, FIXED)})
        # `None` where apply wrote the album anyway, and moved it away from its source.
        cls.fixed = lib.entries().get(HELD)

    def validation(self, entry: dict) -> list[str]:
        return [hold["detail"] for hold in entry["holds"] if hold["kind"] == "validation"]

    def test_each_rejected_value_is_a_validation_hold_naming_its_key(self):
        self.assertEqual(self.planned["state"], "auto", "held before any edit")
        details = self.validation(self.held)
        for key in ("TXXX:YEAR", "TCOM", "TXXX:TOTALTRACKS"):
            with self.subTest(key=key):
                self.assertTrue(any(key in detail for detail in details),
                                f"no validation hold names {key}: {self.held['holds']}")

    def test_the_held_album_is_still_planned_with_the_owners_values_where_they_were_put(self):
        # Laid after residue, the year tag is in the plan to be judged, not
        # stripped before anyone sees it.
        self.assertEqual(self.held["decision"], "accept")
        self.assertEqual(after(self.held, "1-1").get("TXXX:YEAR"), ["1989"])
        self.assertEqual(after(self.held, "1-2").get("TCOM"), [" Jane Doe"])
        self.assertEqual(after(self.held, "1-3").get("TXXX:TOTALTRACKS"), ["3"])

    def test_apply_does_not_write_an_album_held_for_a_raw_edit(self):
        self.assertEqual(self.held["state"], "held")
        self.assertEqual(self.source_after_apply, self.source_before, "apply wrote the held album")
        self.assertFalse((self.lib.root / self.held["destination"]).exists())
        self.assertFalse(self.memory_after_apply, "a held album's edits were remembered")

    def test_changing_the_rejected_values_clears_the_holds(self):
        self.assertTrue(self.validation(self.held), "the precondition: the bad edits held the album")
        self.assertIsNotNone(self.fixed, "apply wrote the held album, so there was nothing left to fix")
        self.assertEqual(self.fixed["holds"], [])
        self.assertEqual(after(self.fixed, "1-2").get("TCOM"), ["Jane Doe"])
        self.assertNotIn("TXXX:YEAR", after(self.fixed, "1-1"))


#: Keys refused at each album's track 1, each with why. The file's family at
#: that position decides: `composer` and `©wrt` are fine on a FLAC and an
#: M4A, and no ID3 frame.
REFUSED = [
    (MP3, "TXXX:MusicBrainz Album Id", "a MusicBrainz ID"),
    (MP3, "UFID:http://musicbrainz.org", "the recording ID"),
    (MP3, "TXXX:MusicBrainz Release Track Id", "a MusicBrainz ID"),
    (MP3, "POPM:someone@example.com", "a rating"),
    (MP3, "TXXX:FMPS_Rating", "a rating"),
    (MP3, "APIC:", "a picture"),
    (MP3, "GEOB:blob", "a binary frame"),
    (MP3, "PRIV:owner", "a binary frame"),
    (MP3, "XYZZ", "no ID3 frame"),
    (MP3, "composer", "a Vorbis name, no ID3 frame"),
    (MP3, "\xa9wrt", "an MP4 atom, no ID3 frame"),
    (FLAC, "musicbrainz_albumid", "a MusicBrainz ID"),
    (FLAC, "musicbrainz_trackid", "the recording ID"),
    (FLAC, "rating", "a rating"),
    (FLAC, "metadata_block_picture", "a picture"),
    (M4A, "----:com.apple.iTunes:MusicBrainz Album Id", "a MusicBrainz ID"),
    (M4A, "----:com.apple.iTunes:rating", "a rating"),
    (M4A, "rate", "a rating"),
    (M4A, "covr", "a picture"),
    # Only text frames, bare or keyed as `TXXX:`, `COMM:` and `USLT:` are, can be written from a list of values.
    (MP3, "PCNT", "a play counter, not text"),
    (MP3, "MCDI", "a binary frame"),
    (MP3, "TIPL", "a people list, not a plain text frame"),
    (MP3, "SYLT", "synchronised lyrics, not text"),
    (MP3, "TXXX", "a TXXX frame with no description"),
    # Vorbis names are compared case-folded, so an upper-case rating is still a rating.
    (FLAC, "FMPS_RATING", "a rating, upper case"),
    (FLAC, "RATING", "a rating, upper case"),
    (FLAC, "comp=oser", "`=` ends a Vorbis name"),
    (FLAC, "Komp\xf6nist", "a Vorbis name is ASCII"),
    (FLAC, "", "an empty name"),
    (M4A, "tmpo", "an integer atom"),
    (M4A, "cpil", "a flag atom"),
    (M4A, "rtng", "an integer atom"),
    (M4A, "stik", "an integer atom"),
    (M4A, "gnre", "a numbered genre"),
    (M4A, "trkn", "a number pair"),
    (M4A, "disk", "a number pair"),
    (M4A, "foo", "neither four characters nor `----:`"),
    (M4A, "----:com.apple.iTunes:FMPS_Rating", "a rating"),
]

#: A raw key each album may take, laid beside the refused one at the same
#: position and alone at track 2: the message must not name it.
ALLOWED = {MP3: "TXXX:MOOD", FLAC: "mood", M4A: MP4_MOOD}


class Refused(unittest.TestCase):
    """`decisions.read` against a job one real `batch identify` has planned, copied for each case."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        no_throttle(cls)
        cls.lib = lib = Library(base)
        cls.ids = three_formats(lib.root, lib.catalogue)
        lib.identify()
        if not (lib.job / "plan.json").is_file():
            raise AssertionError("identify planned nothing")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.job = Path(tmp.name) / "jobs" / JOB_ID
        shutil.copytree(self.lib.job, self.job)

    def read_with(self, key: str, edits: dict) -> str | None:
        """`decisions.read` of a file accepting `key` with `edits`: the refusal's message, or `None` if read."""
        from musiclib.batch import decisions
        from musiclib.batch.job import Job

        doc = {"job": JOB_ID, "albums": {key: accept(self.ids[key], edits)}}
        (self.job / "decisions.json").write_text(json.dumps(doc), encoding="utf-8")
        try:
            decisions.read(Job(self.job))
        except decisions.DecisionsRejected as exc:
            return str(exc)
        return None

    def test_raw_keys_of_each_format_with_values_or_null_are_read(self):
        # The control for every refusal below: each is this file with one
        # key added, so a reader that refuses every raw key fails here.
        cases = {MP3: {"TCOM": ["Jane Doe"], MOOD: None, "COMM:desc:eng": ["a note"],
                       "USLT:desc:eng": ["words"]},
                 FLAC: {"composer": ["Jane Doe"], "mood": None, "CONDUCTOR": ["Jane Doe"]},
                 M4A: {"\xa9wrt": ["Jane Doe"], MP4_MOOD: ["Calm"]}}
        for key, fields in cases.items():
            with self.subTest(album=key):
                self.assertIsNone(self.read_with(key, {"1-1": fields}))

    def test_an_id_a_rating_a_binary_frame_or_a_key_the_format_cannot_hold_is_refused_naming_it(self):
        for key, refused, why in REFUSED:
            with self.subTest(album=key, key=refused, why=why):
                message = self.read_with(key, {"1-1": {refused: ["x"], ALLOWED[key]: ["x"]},
                                               "1-2": {ALLOWED[key]: ["x"]}})
                self.assertIsNotNone(message, f"{refused!r} on {key} was read")
                # An empty name is in every message; its refusal is the whole assertion.
                if refused:
                    self.assertIn(refused, message)
                # Refusing the position's edits or the whole album's, rather
                # than the key, would name the allowed one too.
                self.assertNotIn(ALLOWED[key], message)

    def test_a_refused_key_given_null_is_refused_too(self):
        # Removing an ID, a rating or a picture is as much an edit of it as setting one.
        for key, refused in ((MP3, "TXXX:MusicBrainz Album Id"), (MP3, "POPM:someone@example.com"),
                             (M4A, "covr")):
            with self.subTest(album=key, key=refused):
                message = self.read_with(key, {"1-1": {refused: None}, "1-2": {ALLOWED[key]: None}})
                self.assertIsNotNone(message, f"{refused!r}: null on {key} was read")
                self.assertIn(refused, message)
                self.assertNotIn(ALLOWED[key], message)

    def test_identify_given_a_refused_key_exits_1_naming_it_and_writes_nothing(self):
        refused = "XYZZ"
        doc = {"job": JOB_ID, "albums": {MP3: accept(self.ids[MP3], {"1-1": {refused: ["x"], "TCOM": ["x"]}})}}
        (self.lib.job / "decisions.json").write_text(json.dumps(doc), encoding="utf-8")
        self.addCleanup((self.lib.job / "decisions.json").unlink)
        before = builders.tree(self.lib.base)

        code, _out, err = run_identify(self.lib.root, self.lib.job, self.lib.memory,
                                       Services(self.lib.catalogue))

        self.assertEqual(code, 1, err)
        self.assertIn(refused, err)
        self.assertNotIn("TCOM", err)
        self.assertEqual(builders.tree(self.lib.base), before, "a refused decisions.json changed something")


FOLDED = "V/Vorbis Band/Record [rip]"


class VorbisNamesFolded(unittest.TestCase):
    """A FLAC album accepted with raw edits named in upper case."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        no_throttle(cls)
        lib = cls.lib = Library(Path(tmp.name))
        release_id = rip(lib.root, lib.catalogue, FOLDED, 1, "flac")
        lib.identify()
        lib.decide({FOLDED: accept(release_id, {"1-1": {"COMPOSER": ["Jane Doe"], "ALBUM": ["Other Record"]}})})
        cls.decided = lib.entries()[FOLDED]

    def test_an_upper_case_vorbis_edit_lands_once_under_the_lower_case_name(self):
        self.assertEqual(self.decided["decision"], "accept", f"the edits were refused: {self.decided}")
        planned = after(self.decided, "1-1")
        # `album` is also a key the engine plans: an edit kept apart from it
        # by case would leave the file with two album tags.
        for name, values in (("composer", ["Jane Doe"]), ("album", ["Other Record"])):
            with self.subTest(key=name):
                self.assertEqual([key for key in planned if key.casefold() == name], [name])
                self.assertEqual(planned[name], values)


CROSSED = "X/Cross Band/Record [rip]"


class RememberedForAnotherFormat(unittest.TestCase):
    """A FLAC job over a release remembers `composer`; a second job meets the same release as MP3s."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        no_throttle(cls)
        (base / "first").mkdir()
        (base / "second").mkdir()
        first = cls.first = Library(base / "first")
        release_id = rip(first.root, first.catalogue, CROSSED, 1, "flac")
        first.identify()
        first.decide({CROSSED: accept(release_id, {"1-1": {"composer": ["Jane Doe"]}})})
        cls.first_code, cls.first_out, cls.first_err = first.apply()
        cls.remembered = first.memory.is_file()

        # The same release, tagged with the same release ID, ripped to MP3,
        # with the first job's memory.
        second = cls.second = Library(base / "second")
        rip(second.root, second.catalogue, CROSSED, 1, "mp3")
        if cls.remembered:
            shutil.copyfile(first.memory, second.memory)
        second.identify()
        cls.planned = second.entries()[CROSSED]
        cls.code, cls.out, cls.err = second.apply()

    def test_a_raw_edit_remembered_from_a_flac_is_not_laid_on_an_mp3_of_the_same_release(self):
        self.assertEqual(self.first_code, 0, self.first_out + self.first_err)
        self.assertTrue(self.remembered, "the FLAC job remembered nothing")
        for f in self.planned["files"]:
            with self.subTest(position=f["position"]):
                self.assertNotIn("composer", f["after"])
        self.assertEqual(self.planned["holds"], [])
        self.assertEqual(self.planned["state"], "auto")
        self.assertEqual(self.code, 0, self.out + self.err)
        self.assertFalse((self.second.root / CROSSED).exists(), "apply left the MP3 album where it was")


COMPOSED = "C/Composed Band/Record [rip]"
MB_COMPOSER = {"id": "6f1a2b3c-0000-4000-8000-000900000001", "name": "Mb Composer",
               "sort-name": "Composer, Mb"}
OWNER_COMPOSER = "Someone Else"


class WorksServices(Services):
    """`Services`, with every recording a performance of a work MusicBrainz says `MB_COMPOSER` composed.

    Answers only the relationship lookup that way; the release lookup the
    engine made before composer is the plain catalogue release. The
    composer's own artist lookup is answered too, in case the engine asks
    for aliases.
    """

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc == "musicbrainz.org" and path == f"/ws/2/artist/{MB_COMPOSER['id']}":
            self.answered.append(url)
            return 200, json.dumps({**MB_COMPOSER, "aliases": []}).encode()
        if parts.netloc == "musicbrainz.org" and "work-rels" in parts.query:
            ident = path.removeprefix("/ws/2/release/")
            if ident in self.releases:
                self.answered.append(url)
                return 200, json.dumps(with_works(self.releases[ident])).encode()
        return super().__call__(url, headers)


def with_works(found: dict) -> dict:
    """`found`, each recording with a `performance` of its own work, composed by `MB_COMPOSER`."""
    doc = json.loads(json.dumps(found))
    for medium in doc["media"]:
        for track in medium["tracks"]:
            recording = track["recording"]
            recording["relations"] = [{
                "type": "performance", "target-type": "work", "direction": "forward",
                "work": {"id": recording["id"].replace("-8000-", "-9000-"), "title": track["title"],
                         "relations": [{"type": "composer", "target-type": "artist", "direction": "backward",
                                        "artist": dict(MB_COMPOSER)}]},
            }]
    return doc


def composed(root: Path, catalogue: list) -> dict[str, str]:
    return {COMPOSED: rip(root, catalogue, COMPOSED, 1, "mp3")}


class OwnerComposerOverMusicBrainz(unittest.TestCase):
    """An MP3 album MusicBrainz has a composer for, with the owner's composer at track 1."""

    @classmethod
    def setUpClass(cls):
        decided_and_applied(cls, {COMPOSED: {"1-1": {"TCOM": [OWNER_COMPOSER]}}},
                            services=WorksServices, lay_rips=composed)

    def test_an_owner_composer_edit_wins_over_musicbrainzs_is_written_and_is_laid_again_by_a_later_job(self):
        entry = self.decided[COMPOSED]
        # The control: track 2 has no edit and takes MusicBrainz's composer,
        # so track 1 showing the owner's is the edit winning, not no lookup.
        self.assertEqual(after(entry, "1-2").get("TCOM"), [MB_COMPOSER["name"]])
        self.assertEqual(after(entry, "1-1").get("TCOM"), [OWNER_COMPOSER])

        self.assertEqual(self.code, 0, self.out + self.err)
        on_disk = written(self.lib.root, entry)
        self.assertEqual(on_disk["1-1"].get("TCOM"), [OWNER_COMPOSER])
        self.assertEqual(on_disk["1-2"].get("TCOM"), [MB_COMPOSER["name"]])

        self.assertEqual((self.remembered or {}).get("edits", {}).get(self.ids[COMPOSED]),
                         {"1-1": {"TCOM": [OWNER_COMPOSER]}})
        self.assertEqual(after(self.again[COMPOSED], "1-1").get("TCOM"), [OWNER_COMPOSER])
        self.assertEqual(after(self.again[COMPOSED], "1-2").get("TCOM"), [MB_COMPOSER["name"]])


if __name__ == "__main__":
    unittest.main()
