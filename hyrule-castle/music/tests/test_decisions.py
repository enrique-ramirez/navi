"""The owner's `decisions.json`: refused whole when it does not fit the job, and a pasted release planned.

A file for another job, or naming an album the job's `plan.json` does not
have, is refused entire: neither `batch identify` nor `batch apply` writes
anything, and the message names every offence rather than the first. A
decision that pastes a release URL or MBID has the next `batch identify`
plan that album against it and hold it again, however well the release fits.

The rules are read through `decisions.read` directly, which is cheap. What
the commands do with a refused file is read off the disk before and after.
The library, the fakes and the job layout are `tests.test_batch_identify`'s.
"""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from tests import builders
from tests.test_batch_apply import Library
from tests.test_batch_identify import Services, album, no_throttle, release, run_identify
from tests.test_identify import search_json
from tests.test_memory import entries, key_of

ACCEPTED = "A/Alpha/First [rip]"
REPOINTED = "B/Beta/Second [rip]"
SKIPPED = "C/Gamma/Third [rip]"

#: Every album here is tagged with its own release and matches it to the
#: second, so each is `certain` and auto before any decision is made. A
#: held album after a decision was held by the decision.
CATALOGUE = [release(1, "Alpha", "First", ["One", "Two"]),
             release(2, "Beta", "Second", ["One", "Two"]),
             release(4, "Gamma", "Third", ["One", "Two"])]

#: The release the owner pastes for REPOINTED. It fits the files as well as
#: the one they are tagged with, so nothing about the fit would hold it.
PASTED, _PASTED_GROUP = release(3, "Beta", "Second (Remaster)", ["One", "Two"])
SERVICES = CATALOGUE + [(PASTED, _PASTED_GROUP)]

#: A job ID no job here has. Long enough not to turn up in a message by chance.
OTHER_JOB = "some-other-job-7"


def release_of(key: str) -> str:
    return {ACCEPTED: CATALOGUE[0][0]["id"], REPOINTED: CATALOGUE[1][0]["id"],
            SKIPPED: CATALOGUE[2][0]["id"]}[key]


def library(root: Path) -> None:
    for key in (ACCEPTED, REPOINTED, SKIPPED):
        album(root, key, ["One", "Two"], release_id=release_of(key))


def write_decisions(job: Path, doc) -> None:
    """`doc` as the page's export lands in the job: JSON, or a string written as it is."""
    text = doc if isinstance(doc, str) else json.dumps(doc)
    (job / "decisions.json").write_text(text, encoding="utf-8")


def valid(job_id: str = "j1") -> dict:
    """One decision of each kind, every one of them fine for this job."""
    return {"job": job_id, "albums": {
        ACCEPTED: {"action": "accept", "release_id": release_of(ACCEPTED), "edits": {}, "game": None},
        REPOINTED: {"action": "repoint", "release": f"https://musicbrainz.org/release/{PASTED['id']}"},
        SKIPPED: {"action": "skip"},
    }}


class Reading(unittest.TestCase):
    """`decisions.read(job)` against a job one real `batch identify` has planned.

    The job is planned once for the file, then copied for each case, so a
    `decisions.json` one case writes is never read by the next.
    """

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        no_throttle(cls)
        library(base / "library")
        cls.template = base / ".musiclib" / "jobs" / "j1"
        cls.template.mkdir(parents=True)
        cls.planned = run_identify(base / "library", cls.template, base / ".musiclib" / "memory.json",
                                   Services(SERVICES))

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.job = Path(tmp.name) / "jobs" / "j1"
        # A missing plan.json would make every album "unknown", and each
        # refusal below would pass for that reason alone.
        self.assertTrue((self.template / "plan.json").is_file(), self.planned)
        shutil.copytree(self.template, self.job)

    def read(self):
        from musiclib.batch import decisions
        from musiclib.batch.job import Job

        return decisions.read(Job(self.job))

    def assertRejected(self, doc, *named: str) -> None:
        """Reading `doc` raises `DecisionsRejected`, and its message names each of `named`."""
        from musiclib.batch import decisions

        write_decisions(self.job, doc)
        with self.assertRaises(decisions.DecisionsRejected) as raised:
            self.read()
        for offence in named:
            self.assertIn(offence, str(raised.exception))

    def with_album(self, key: str, decision: dict) -> dict:
        """A file that is fine apart from `decision` for `key`."""
        doc = valid()
        doc["albums"][key] = decision
        return doc

    def test_a_job_with_no_decisions_file_reads_as_none(self):
        self.assertIsNone(self.read())

    def test_a_file_with_an_accept_a_repoint_and_a_skip_for_this_job_is_read(self):
        # The control for every refusal below: each of them is this file with
        # one thing wrong, so a reader that refuses everything fails here.
        write_decisions(self.job, valid())
        self.assertIsInstance(self.read(), dict)

    def test_a_file_for_another_job_is_refused_naming_that_job(self):
        # Every album key in it is one this job has, so only the job ID is wrong.
        self.assertRejected(valid(OTHER_JOB), OTHER_JOB)

    def test_a_file_naming_an_album_the_job_does_not_have_is_refused_naming_the_album(self):
        stranger = "N/Nobody/Nothing [rip]"
        self.assertRejected(self.with_album(stranger, {"action": "skip"}), stranger)

    def test_an_action_other_than_accept_repoint_or_skip_is_refused_naming_it(self):
        self.assertRejected(self.with_album(SKIPPED, {"action": "approve"}), "approve")

    def test_a_repoint_to_a_release_group_rather_than_a_release_is_refused_naming_the_paste(self):
        # The easy paste to get wrong: a release group page has an MBID of
        # the same shape, and planning against it would be planning nothing.
        paste = f"https://musicbrainz.org/release-group/{PASTED['release-group']['id']}"
        self.assertRejected(self.with_album(REPOINTED, {"action": "repoint", "release": paste}), paste)

    def test_each_of_the_three_game_choices_and_an_old_exports_not_game_music_is_read(self):
        # 003 criterion 58: the page offers three. `not game music` is what an
        # export from before the amendment says, and job t1's file must
        # still be read (criterion 65).
        from musiclib.batch import decisions

        for game in ("video game music", "soundtrack", "neither", "not game music"):
            with self.subTest(game=game):
                decision = {"action": "accept", "release_id": release_of(ACCEPTED), "edits": {}, "game": game}
                write_decisions(self.job, self.with_album(ACCEPTED, decision))
                try:
                    self.assertIsInstance(self.read(), dict)
                except decisions.DecisionsRejected as refused:
                    self.fail(f"refused: {refused}")

    def test_a_game_choice_other_than_the_three_the_page_offers_is_refused_naming_it(self):
        decision = {"action": "accept", "release_id": release_of(ACCEPTED), "edits": {},
                    "game": "film score"}
        self.assertRejected(self.with_album(ACCEPTED, decision), "film score")

    def accept_with(self, **changes) -> dict:
        """A file that is fine apart from `changes` to ACCEPTED's accept."""
        decision = {"action": "accept", "release_id": release_of(ACCEPTED), "edits": {}, "game": None}
        decision.update(changes)
        return self.with_album(ACCEPTED, decision)

    def test_an_accept_editing_a_field_the_page_offers_at_a_position_the_album_has_is_read(self):
        # The control for the three refusals after it, so a reader that
        # refuses every edit, or every position, fails here.
        write_decisions(self.job, self.accept_with(edits={"1-2": {"title": ["Two (Live)"]}}))
        self.assertIsInstance(self.read(), dict)

    def test_an_accept_with_no_release_id_is_refused_naming_the_album(self):
        doc = self.accept_with()
        del doc["albums"][ACCEPTED]["release_id"]
        self.assertRejected(doc, ACCEPTED)

    def test_an_edit_to_a_field_the_page_does_not_offer_is_refused_naming_the_field(self):
        # `release id` is a neutral field, but one of the six MusicBrainz IDs
        # the page never offers: an edit to it would retag the album as a
        # release nobody planned it against. `mood` is not a neutral field.
        for field in ("release id", "mood"):
            with self.subTest(field=field):
                self.assertRejected(self.accept_with(edits={"1-1": {field: ["x"]}}), field)

    def test_an_edit_at_a_position_the_album_does_not_have_is_refused_naming_the_position(self):
        # The album has two tracks on one disc, so 1-1 and 1-2 only.
        self.assertRejected(self.accept_with(edits={"1-3": {"title": ["Three"]}}), "1-3")

    def test_a_file_that_is_not_json_is_refused_the_same_way(self):
        # A half-saved download. It must come out as a refusal the commands
        # report and exit 1 on, not as a traceback.
        self.assertRejected('{"job": "j1", "albums": {')

    def test_every_offence_in_a_file_is_named_not_only_the_first(self):
        # One pass that stops at the first problem leaves the owner fixing
        # the file once per offence, re-running each time to meet the next.
        stranger = "N/Nobody/Nothing [rip]"
        doc = valid(OTHER_JOB)
        doc["albums"][stranger] = {"action": "skip"}
        doc["albums"][SKIPPED] = {"action": "approve"}
        doc["albums"][ACCEPTED]["game"] = "film score"
        self.assertRejected(doc, OTHER_JOB, stranger, "approve", "film score")

    def wait_on_the_choice(self, key: str) -> None:
        """This case's `plan.json` with `key` held for its soundtrack choice, as identify leaves a Soundtrack-type album."""
        plan = self.job / "plan.json"
        doc = json.loads(plan.read_text(encoding="utf-8"))
        for entry in doc["albums"]:
            if entry["source"] == key:
                entry["game_choice"] = True
                entry["holds"] = [{"kind": "status", "detail": "review: soundtrack choice"}]
                entry["state"] = "held"
        plan.write_text(json.dumps(doc), encoding="utf-8")

    def test_an_accept_with_no_game_of_an_album_waiting_on_its_soundtrack_choice_is_read(self):
        # The page exports an accept with no `game` when
        # the owner accepts the release and leaves the choice for later.
        # Refusing the file for that stopped every other album in it.
        from musiclib.batch import decisions

        self.wait_on_the_choice(ACCEPTED)
        for shape in ("null", "missing"):
            with self.subTest(game=shape):
                doc = self.accept_with()
                if shape == "missing":
                    del doc["albums"][ACCEPTED]["game"]
                write_decisions(self.job, doc)
                try:
                    self.assertIsInstance(self.read(), dict)
                except decisions.DecisionsRejected as refused:
                    self.fail(f"refused: {refused}")

    def test_an_accept_with_no_game_of_an_album_waiting_on_its_choice_is_refused_only_for_what_else_is_wrong(self):
        # Each file has one other offence, which still refuses it. The
        # message names that offence and not the missing choice: the old
        # refusal named the three choices, so they must not turn up.
        self.wait_on_the_choice(ACCEPTED)
        no_release = self.accept_with()
        del no_release["albums"][ACCEPTED]["release_id"]
        other_job = self.accept_with()
        other_job["job"] = OTHER_JOB
        # All three at once, so each is still named, not only the first.
        every = self.accept_with(edits={"1-3": {"title": ["Three"]}})
        every["job"] = OTHER_JOB
        del every["albums"][ACCEPTED]["release_id"]
        cases = {
            "no release_id": (no_release, [ACCEPTED]),
            "unoffered field": (self.accept_with(edits={"1-1": {"mood": ["x"]}}), ["mood"]),
            "missing position": (self.accept_with(edits={"1-3": {"title": ["Three"]}}), ["1-3"]),
            "another job": (other_job, [OTHER_JOB]),
            "all three": (every, [OTHER_JOB, "release_id", "1-3"]),
        }
        from musiclib.batch import decisions

        for name, (doc, named) in cases.items():
            with self.subTest(offence=name):
                write_decisions(self.job, doc)
                with self.assertRaises(decisions.DecisionsRejected) as raised:
                    self.read()
                message = str(raised.exception)
                for offence in named:
                    self.assertIn(offence, message)
                for choice in ("video game music", "neither"):
                    self.assertNotIn(choice, message)


class _Job(unittest.TestCase):
    """The library at `<tmp>/library` and job `j1` at `<tmp>/.musiclib/jobs/j1`, planned once."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "library"
        self.job = self.tmp / ".musiclib" / "jobs" / "j1"
        self.job.mkdir(parents=True)
        self.memory = self.tmp / ".musiclib" / "memory.json"
        no_throttle(self)
        library(self.root)

    def identify(self) -> tuple[int, str, str]:
        return run_identify(self.root, self.job, self.memory, Services(SERVICES))

    def plan_doc(self) -> dict:
        return json.loads((self.job / "plan.json").read_text(encoding="utf-8"))

    def entries(self) -> dict:
        return {entry["source"]: entry for entry in self.plan_doc()["albums"]}

    def first_run(self) -> dict:
        """Plan the job with no decisions, and the entries it gave."""
        code, _out, err = self.identify()
        self.assertEqual(code, 0, err)
        return self.entries()


class RefusedByIdentify(_Job):
    def assertIdentifyWritesNothing(self, doc, named: str) -> None:
        self.first_run()
        write_decisions(self.job, doc)
        before = builders.tree(self.tmp)

        code, _out, err = self.identify()

        self.assertEqual(code, 1, err)
        self.assertIn(named, err)
        # The whole of <tmp>: plan.json, review.html, the cache, the memory
        # and the library. The refused file also skips SKIPPED, which would
        # change plan.json were any of it acted on, so a plan rewritten to the
        # same bytes cannot hide here.
        self.assertEqual(builders.tree(self.tmp), before, "a refused decisions.json changed something")

    def test_identify_given_another_jobs_decisions_exits_1_naming_the_job_and_writes_nothing(self):
        self.assertIdentifyWritesNothing(valid(OTHER_JOB), OTHER_JOB)

    def test_identify_given_decisions_for_an_album_the_job_lacks_exits_1_naming_it_and_writes_nothing(self):
        stranger = "N/Nobody/Nothing [rip]"
        doc = valid()
        doc["albums"][stranger] = {"action": "skip"}
        self.assertIdentifyWritesNothing(doc, stranger)

    def test_identify_on_a_job_never_planned_with_a_refused_file_leaves_no_plan_or_page(self):
        # Before any plan.json there is nothing to compare album keys with,
        # so the file here is refused for its job ID, which is wrong either way.
        write_decisions(self.job, valid(OTHER_JOB))
        library_before = builders.tree(self.root)

        code, _out, err = self.identify()

        self.assertEqual(code, 1, err)
        self.assertIn(OTHER_JOB, err)
        self.assertFalse((self.job / "plan.json").exists(), "plan.json written from a refused file")
        self.assertFalse((self.job / "review.html").exists(), "review.html written from a refused file")
        self.assertEqual(builders.tree(self.root), library_before)


class RefusedByApply(_Job):
    def test_apply_given_another_jobs_decisions_exits_1_naming_the_job_and_writes_nothing(self):
        # Every album is auto, so an apply that went ahead would write all
        # three: the library staying as it was is the refusal, not an empty job.
        entries = self.first_run()
        self.assertEqual({entry["state"] for entry in entries.values()}, {"auto"})
        write_decisions(self.job, valid(OTHER_JOB))
        # foobar2000 not running, as `systemctl is-active` says it, so that is
        # not what stops the apply.
        systemctl = self.tmp / "systemctl"
        systemctl.write_text("#!/bin/sh\necho inactive\nexit 3\n")
        systemctl.chmod(0o755)
        before = builders.tree(self.tmp)

        from musiclib.batch import apply
        from musiclib.batch.job import Job

        out, err = io.StringIO(), io.StringIO()
        code = apply.run(Job(self.job), self.memory, extras_root=self.tmp / "extras",
                         live_root=self.root, systemctl=str(systemctl), transport=Services(SERVICES),
                         out=out, err=err)

        self.assertEqual(code, 1, err.getvalue())
        # Named, so a 1 for some other reason (foobar, a failed album) cannot pass.
        self.assertIn(OTHER_JOB, err.getvalue())
        self.assertEqual(builders.tree(self.tmp), before, "a refused decisions.json changed something")


class Decided(_Job):
    def test_accept_and_skip_are_recorded_on_their_albums_at_the_next_identify(self):
        self.first_run()
        doc = valid()
        del doc["albums"][REPOINTED]
        write_decisions(self.job, doc)

        code, _out, err = self.identify()

        self.assertEqual(code, 0, err)
        entries = self.entries()
        self.assertEqual(entries[ACCEPTED]["decision"], "accept")
        self.assertEqual(entries[SKIPPED]["decision"], "skip")
        # An album the file does not name has no decision.
        self.assertIsNone(entries[REPOINTED]["decision"])


class Repointed(_Job):
    def assertPlannedAgainstThePaste(self, paste: str) -> None:
        # The control: before the paste the album is planned, auto, against
        # the release its files are tagged with.
        before = self.first_run()[REPOINTED]
        self.assertEqual((before["release_id"], before["state"]), (release_of(REPOINTED), "auto"))
        write_decisions(self.job, {"job": "j1", "albums": {REPOINTED: {"action": "repoint", "release": paste}}})

        code, _out, err = self.identify()

        self.assertEqual(code, 0, err)
        entry = self.entries()[REPOINTED]
        self.assertEqual(entry["release_id"], PASTED["id"])
        self.assertEqual(entry["decision"], "repoint")
        # What apply rebuilds the plan from: the pasted release, marked as
        # the owner's choice rather than the engine's.
        self.assertIsNotNone(entry["inputs"], entry)
        self.assertEqual(entry["inputs"]["release_id"], PASTED["id"])
        self.assertIs(entry["inputs"]["chosen"], True)
        # Held for the paste itself. The pasted release fits the files to the
        # second, so no other reason is needed for it to be held; what else
        # the engine says about an owner's pick is not this case's business.
        self.assertEqual(entry["state"], "held")
        self.assertIn({"kind": "repointed", "detail": PASTED["id"]}, entry["holds"])

    def test_a_pasted_release_url_is_planned_against_at_the_next_identify_and_held_as_repointed(self):
        self.assertPlannedAgainstThePaste(f"https://musicbrainz.org/release/{PASTED['id']}")

    def test_a_pasted_bare_mbid_is_planned_against_and_held_the_same_way(self):
        self.assertPlannedAgainstThePaste(PASTED["id"])



T1 = "t1"
T1_TRACKS = ["One", "Two"]

# Soundtrack-type, tagged with their releases. The old page asked the
# composer question on both, and the export answers it both ways.
OLD_ANSWER = "O/Oleander/Old Score [rip]"
GAME_ANSWER = "G/Gorse/Overworld [rip]"
# Plain and tagged: one accepted with an edit, one skipped.
EDITED = "E/Elder/Edited [rip]"
T1_SKIPPED = "K/Kale/Skipped [rip]"
# Not Soundtrack-type, but its files carry `video game music`, which is what
# made the old page ask the question too.
GAME_ON_THE_FILES = "V/Vetch/Chiptunes [rip]"
# Untagged, so found by search. Its one release credits somebody other than
# the files' artist: criterion 47 holds it, the old engine did not.
NOT_THEIRS = "D/Dahlia/Borrowed [rip]"
# Untagged. The search finds two editions of one date: the one the old
# engine put on top fits closest but credits somebody else, and the amended
# engine ranks the other, credited to the files' artist, above it.
TWO_EDITIONS = "M/Mallow/Editions [rip]"

T1_TAGGED = (OLD_ANSWER, GAME_ANSWER, EDITED, T1_SKIPPED, GAME_ON_THE_FILES)
T1_SEARCHED = (NOT_THEIRS, TWO_EDITIONS)


def _t1_release(number: int, key: str, *, credited: str | None = None, soundtrack_type: bool = False,
                length_ms: int | None = None) -> tuple[dict, dict]:
    """A release that fits the rip at `key`, credited to `credited` rather than the rip's own artist if given."""
    artist, title = key.split("/")[1], key.split("/")[2]
    found, group = release(number, credited or artist, title, T1_TRACKS)
    if soundtrack_type:
        group["secondary-types"] = ["Soundtrack"]
        found["release-group"]["secondary-types"] = ["Soundtrack"]
    if length_ms is not None:
        for track in found["media"][0]["tracks"]:
            track["length"] = track["recording"]["length"] = length_ms
    return found, group


T1_RELEASES = {
    OLD_ANSWER: _t1_release(41, OLD_ANSWER, soundtrack_type=True),
    GAME_ANSWER: _t1_release(42, GAME_ANSWER, soundtrack_type=True),
    EDITED: _t1_release(43, EDITED),
    T1_SKIPPED: _t1_release(44, T1_SKIPPED),
    GAME_ON_THE_FILES: _t1_release(45, GAME_ON_THE_FILES),
    NOT_THEIRS: _t1_release(46, NOT_THEIRS, credited="Somebody Else"),
}
#: TWO_EDITIONS' editions: the one job t1 put on top and the owner accepted,
#: and the one the amended engine puts there. Same date, both fit.
CLOSEST, _CLOSEST_GROUP = _t1_release(47, TWO_EDITIONS, credited="Somebody Else")
AGREEING, _AGREEING_GROUP = _t1_release(48, TWO_EDITIONS, length_ms=2000)
T1_SEARCH = {NOT_THEIRS: [T1_RELEASES[NOT_THEIRS][0]], TWO_EDITIONS: [CLOSEST, AGREEING]}
T1_CATALOGUE = [*T1_RELEASES.values(), (CLOSEST, _CLOSEST_GROUP), (AGREEING, _AGREEING_GROUP)]


def t1_release_of(key: str) -> str:
    """The release job t1 planned `key` against, and the one its export accepts."""
    return CLOSEST["id"] if key == TWO_EDITIONS else T1_RELEASES[key][0]["id"]


#: `decisions.json` as the page before the amendment exported it: every
#: accept names a release and carries `edits` and `game`, `game` is `null`
#: wherever the page did not ask, and the old pair is the only answer there is.
T1_EXPORT = {"job": T1, "albums": {
    OLD_ANSWER: {"action": "accept", "release_id": t1_release_of(OLD_ANSWER), "edits": {},
                 "game": "not game music"},
    GAME_ANSWER: {"action": "accept", "release_id": t1_release_of(GAME_ANSWER), "edits": {},
                  "game": "video game music"},
    GAME_ON_THE_FILES: {"action": "accept", "release_id": t1_release_of(GAME_ON_THE_FILES), "edits": {},
                        "game": "not game music"},
    EDITED: {"action": "accept", "release_id": t1_release_of(EDITED),
             "edits": {"1-2": {"title": ["Two (Live)"]}}, "game": None},
    T1_SKIPPED: {"action": "skip"},
    NOT_THEIRS: {"action": "accept", "release_id": t1_release_of(NOT_THEIRS), "edits": {}, "game": None},
    TWO_EDITIONS: {"action": "accept", "release_id": t1_release_of(TWO_EDITIONS), "edits": {}, "game": None},
}}


def t1_plan(root: Path) -> dict:
    """`plan.json` for job t1 in the shape the engine wrote it before the amendment.

    The entry keys are the old `_blank_entry`'s, `composer` among them.
    `game_choice` is true on every Soundtrack-type album and on one whose
    files say `video game music`. An unsettled Soundtrack album was held
    `review: unsettled soundtrack`, and nothing was held for its artist.
    Only what an entry's decision is checked against has to be right: its
    source, `game_choice` and the positions in `fields`.
    """
    def entry(key: str) -> dict:
        found = T1_RELEASES[key][0] if key != TWO_EDITIONS else CLOSEST
        soundtrack_type = "Soundtrack" in found["release-group"]["secondary-types"]
        artist_id = found["artist-credit"][0]["artist"]["id"]
        artist = key.split("/")[1]
        holds = [{"kind": "status", "detail": "review: unsettled soundtrack"}] if soundtrack_type else []
        return {
            "source": key, "status": "review" if soundtrack_type else "certain", "holds": holds,
            "decision": None, "release_id": found["id"],
            "destination": f"{artist}/{artist} - 1989 - {found['title']}",
            "composer": artist_id, "game_choice": soundtrack_type or key == GAME_ON_THE_FILES,
            "candidates": [], "files": [],
            "fields": {position: {"title": [title]} for position, title in zip(("1-1", "1-2"), T1_TRACKS)},
            "images": {}, "residue": [], "deletions": [], "extras": [], "kept": [], "changes": [],
            "inputs": None, "plan_digest": None, "game": None, "owner_edits": {},
            "state": "held" if holds else "auto",
        }

    keys = sorted(T1_TAGGED + T1_SEARCHED)
    return {"job": T1, "root": str(root.resolve()), "albums": [entry(key) for key in keys]}


class T1Services(Services):
    """`Services`, with a search that finds the releases `T1_SEARCH` lists for an album, and artist lookups.

    A search is matched to its album by the album's title in the query, so
    each untagged rip finds its own releases and no other. An artist is any
    one a release in the catalogue credits, with no aliases.
    """

    def __init__(self, catalogue: list[tuple[dict, dict]]) -> None:
        super().__init__(catalogue)
        self.artists = {part["artist"]["id"]: part["artist"] for found, _group in catalogue
                        for part in found["artist-credit"]}

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc == "musicbrainz.org" and path == "/ws/2/release":
            self.answered.append(url)
            query = unquote(parts.query).casefold()
            for key, found in T1_SEARCH.items():
                if key.split("/")[2].split(" [")[0].casefold() in query:
                    return 200, json.dumps(search_json(*found)).encode()
            return 200, b'{"releases": [], "count": 0}'
        if parts.netloc == "musicbrainz.org" and path.startswith("/ws/2/artist/"):
            self.answered.append(url)
            artist = self.artists.get(path.removeprefix("/ws/2/artist/"))
            if artist is None:
                return 404, b'{"error": "Not Found"}'
            return 200, json.dumps({**artist, "aliases": [], "genres": []}).encode()
        return super().__call__(url, headers)


def t1_rips(root: Path) -> None:
    for key in T1_TAGGED:
        album(root, key, T1_TRACKS, release_id=t1_release_of(key))
    for key in T1_SEARCHED:
        album(root, key, T1_TRACKS)
    for path in (root / GAME_ON_THE_FILES).glob("*.flac"):
        builders.write_tags(path, {key_of("genre"): ["Video Game Music"]})


class JobT1sExportFromBeforeTheAmendment(unittest.TestCase):
    """Job `t1` holding the old `plan.json`, its old export, and the old memory, then identify and apply once.

    Criterion 65: the amended engine's first `batch identify` on `t1` takes
    the export, and every album it accepts is planned against the release
    it names, with `not game music` read as `soundtrack` (criterion 58).
    `undecided` is the same rips planned by the amended engine in another
    job with no decisions at all: what the engine would choose on its own,
    so the cases can show the export is what overrode it. The cases only read.
    """

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        base = Path(tmp.name)
        no_throttle(cls)

        rips = base / "rips"
        t1_rips(rips)

        lib = cls.lib = Library(base)
        lib.root.rmdir()
        shutil.copytree(rips, lib.root)
        lib.job = base / ".musiclib" / "jobs" / T1
        lib.job.mkdir(parents=True)
        lib.catalogue = T1_CATALOGUE
        # The memory as job t1's engine left it: the composer memory, no
        # soundtracks yet.
        lib.memory.write_text(json.dumps({"edits": {}, "composers": {}, "reopened": []}), encoding="utf-8")
        (lib.job / "plan.json").write_text(json.dumps(t1_plan(lib.root)), encoding="utf-8")
        write_decisions(lib.job, T1_EXPORT)

        cls.identified = run_identify(lib.root, lib.job, lib.memory, T1Services(T1_CATALOGUE))
        cls.planned = lib.entries() if cls.identified[0] == 0 else {}
        cls.applied = lib.apply() if cls.identified[0] == 0 else None
        cls.log = {line["source"]: line["outcome"] for line in lib.log()}
        cls.remembered = json.loads(lib.memory.read_text(encoding="utf-8"))

        fresh = base / "fresh"
        shutil.copytree(rips, fresh)
        undecided = base / ".musiclib" / "jobs" / "u1"
        undecided.mkdir(parents=True)
        cls.undecided_run = run_identify(fresh, undecided, base / "fresh-memory.json", T1Services(T1_CATALOGUE))
        cls.undecided = entries(undecided) if cls.undecided_run[0] == 0 else {}

    def entry(self, key: str) -> dict:
        code, _out, err = self.identified
        self.assertEqual(code, 0, f"the first identify on t1 refused its old export: {err}")
        return self.planned[key]

    def genres(self, key: str) -> list[list[str] | None]:
        entry = self.entry(key)
        return [entry["fields"][position].get("genre") for position in ("1-1", "1-2")]

    def assertPlannedAgainst(self, key: str, release_id: str) -> None:
        """`key` planned against `release_id`, the plan apply rebuilds names it too, and apply wrote it."""
        entry = self.entry(key)
        self.assertEqual(entry["decision"], "accept")
        self.assertEqual(entry["release_id"], release_id)
        self.assertIsNotNone(entry["inputs"], entry)
        self.assertEqual(entry["inputs"]["release_id"], release_id)
        self.assertEqual(self.log.get(key), "applied", f"apply said: {self.applied}")

    def test_the_first_identify_on_t1_takes_the_export_it_was_made_for(self):
        code, _out, err = self.identified
        self.assertEqual(code, 0, err)
        self.assertEqual({key: entry["decision"] for key, entry in self.planned.items()},
                         {key: decision["action"] for key, decision in T1_EXPORT["albums"].items()})

    def test_an_accept_from_the_old_export_is_written_with_its_edit_and_a_skip_is_not_written(self):
        entry = self.entry(EDITED)
        self.assertEqual(entry["fields"]["1-2"].get("title"), ["Two (Live)"])
        self.assertEqual(self.log.get(EDITED), "applied", f"apply said: {self.applied}")
        self.assertNotIn(T1_SKIPPED, self.log)

    def test_not_game_music_is_planned_and_remembered_as_soundtrack_and_video_game_music_as_itself(self):
        # The release group's own genre is `rock`.
        with self.subTest(game="not game music"):
            self.assertEqual(self.genres(OLD_ANSWER), [["soundtrack", "rock"]] * 2)
            self.assertEqual(self.log.get(OLD_ANSWER), "applied", f"apply said: {self.applied}")
        with self.subTest(game="video game music"):
            self.assertEqual(self.genres(GAME_ANSWER), [["video game music", "rock"]] * 2)
        # The old value is stored as what it meant, so no later job reads it.
        self.assertEqual(self.remembered.get("soundtracks", {}).get(t1_release_of(OLD_ANSWER)), "soundtrack")
        self.assertEqual(self.remembered.get("soundtracks", {}).get(t1_release_of(GAME_ANSWER)), "video game music")

    def test_not_game_music_on_an_album_whose_files_say_video_game_music_puts_soundtrack_first(self):
        # The old page asked on this album because of its files, and the
        # amended engine no longer asks: left to itself it plans `video game
        # music` first. The owner's old answer still reads as `soundtrack`,
        # first. Whether `video game music` may stay further down is not
        # settled by the spec, so only the first genre is pinned.
        alone = self.undecided.get(GAME_ON_THE_FILES)
        self.assertIsNotNone(alone, self.undecided_run)
        self.assertEqual(alone["fields"]["1-1"].get("genre", [None])[0], "video game music")
        self.assertEqual([genres[0] if genres else None for genres in self.genres(GAME_ON_THE_FILES)],
                         ["soundtrack"] * 2)
        self.assertEqual(self.log.get(GAME_ON_THE_FILES), "applied", f"apply said: {self.applied}")

    def test_an_accept_the_artist_rule_would_hold_is_planned_against_the_release_it_names_and_written(self):
        # The control: left to itself the amended engine holds this album
        # for its artist (criterion 47), against the same release.
        alone = self.undecided.get(NOT_THEIRS)
        self.assertIsNotNone(alone, self.undecided_run)
        self.assertIn({"kind": "status", "detail": "review: artist does not agree"}, alone["holds"])
        self.assertPlannedAgainst(NOT_THEIRS, t1_release_of(NOT_THEIRS))

    def test_an_accept_of_an_edition_the_amended_engine_ranks_second_is_planned_against_the_one_named(self):
        # The control: left to itself the amended engine plans the edition
        # credited to the files' artist, not the one t1 put on top.
        alone = self.undecided.get(TWO_EDITIONS)
        self.assertIsNotNone(alone, self.undecided_run)
        self.assertEqual(alone["release_id"], AGREEING["id"])
        self.assertPlannedAgainst(TWO_EDITIONS, CLOSEST["id"])


if __name__ == "__main__":
    unittest.main()
