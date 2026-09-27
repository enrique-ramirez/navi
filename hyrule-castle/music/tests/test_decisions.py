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

from tests import builders
from tests.test_batch_identify import Services, album, no_throttle, release, run_identify

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

    def test_a_game_choice_other_than_the_two_the_page_offers_is_refused_naming_it(self):
        decision = {"action": "accept", "release_id": release_of(ACCEPTED), "edits": {},
                    "game": "soundtrack"}
        self.assertRejected(self.with_album(ACCEPTED, decision), "soundtrack")

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
        doc["albums"][ACCEPTED]["game"] = "soundtrack"
        self.assertRejected(doc, OTHER_JOB, stranger, "approve", "soundtrack")


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


if __name__ == "__main__":
    unittest.main()
