"""`musiclib batch identify ROOT --job DIR`: every album planned into one job, and a run picked up again.

What the job holds is `plan.json` and `review.html`. The page's content
belongs to `tests.test_review_page`, so here it only has to exist. Which
album is held and why is `tests.test_batch_holds`.

MusicBrainz and the Cover Art Archive sit behind one fake transport that
answers by URL and records every URL it answered. Every release here is
tagged on its files, so identify looks it up directly and never searches,
except for an album with no release ID, which finds nothing. AcoustID is
unavailable in every run (`env={}`, no `fpcalc`), so nothing reaches the
network.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from musiclib import mb
from musiclib.__main__ import main
from tests import builders

#: `tone.flac` is one second long. A release whose tracks are this long
#: matches the files to the second, which is what makes a tagged album
#: `certain`. The stock 240 s tracks are four minutes off, and `review`.
TONE_MS = 1000

#: A genre on the official list, so a release group carrying it gives a plan
#: that passes validation.
GENRE = "rock"


def mbid(kind: int, number: int) -> str:
    """A well-formed MBID, distinct per `kind` (1 release, 2 group, 3 artist) and `number`."""
    return f"6f1a2b3c-0000-4000-8000-{kind:04d}{number:08d}"


def release(number: int, artist: str, title: str, titles: list[str], *, exact: bool = True,
            genres: dict[str, int] | None = None) -> tuple[dict, dict]:
    """A one-medium release and its release group, as `mb.release` and `mb.release_group` return them.

    `exact=False` keeps the stock four-minute track lengths, so an album
    tagged with this release is `review` rather than `certain`. `genres`
    of `{}` is a release group with no genre at all; `None` is `GENRE`.
    """
    credit = builders.mb_credit(mbid(3, number), artist, artist)
    group = {"id": mbid(2, number), "title": title, "primary-type": "Album", "secondary-types": [],
             "first-release-date": "1989-05-02", "tags": [],
             "genres": [{"name": name, "count": count}
                        for name, count in ({GENRE: 1} if genres is None else genres).items()]}
    medium = builders.mb_medium(1, titles, credit=credit)
    if exact:
        for track in medium["tracks"]:
            track["length"] = TONE_MS
            track["recording"]["length"] = TONE_MS
    found = builders.mb_release(
        id=mbid(1, number), title=title, **{"artist-credit": credit}, media=[medium],
        **{"release-group": {key: group[key] for key in
                             ("id", "title", "primary-type", "secondary-types", "first-release-date")}},
    )
    return found, group


def album(root: Path, key: str, titles: list[str], *, release_id: str | None = None) -> Path:
    """An album the way a rip arrives at `root/key`: lower-case titles, loose names, no genre.

    `release_id` tags every file with it, the way a Picard rip or an
    earlier batch leaves it. Without one, identify has to search.
    """
    base = root / key
    base.mkdir(parents=True)
    for number, title in enumerate(titles, start=1):
        path = base / f"{number:02d} {title.lower()}.flac"
        shutil.copyfile(builders.FIXTURES / "tone.flac", path)
        fields = {"title": [title.lower()], "artist": [key.split("/")[1]],
                  "album": [key.split("/")[2]], "date": ["1989"]}
        if release_id:
            fields["release id"] = [release_id]
        builders.write_tags(path, builders.picard_tags("flac", fields, track=(number, len(titles)),
                                                       disc=(1, 1)), v2_version=4)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


class Services:
    """MusicBrainz and the Cover Art Archive behind one transport, answering by URL.

    Any release or release group it was given is a 200. A search finds
    nothing. The archive has no art for anything, so each album keeps the
    rip's own cover.jpg. `answered` is every URL it gave an answer to, in
    order and with repeats.

    `interrupt` is a string: the first request whose URL contains it raises
    `KeyboardInterrupt` instead of answering, the way Ctrl-C or a killed
    process stops a run. It is a `BaseException`, so the engine's retries,
    which catch network errors, do not swallow it.
    """

    def __init__(self, catalogue: list[tuple[dict, dict]], interrupt: str | None = None) -> None:
        self.releases = {found["id"]: found for found, _group in catalogue}
        self.groups = {group["id"]: group for _found, group in catalogue}
        self.interrupt = interrupt
        self.interrupted: str | None = None
        self.answered: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if self.interrupt and self.interrupted is None and self.interrupt in url:
            self.interrupted = url
            raise KeyboardInterrupt(url)
        self.answered.append(url)
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc == "musicbrainz.org":
            if path == "/ws/2/release":
                return 200, b'{"releases": [], "count": 0}'
            kind, _, ident = path.removeprefix("/ws/2/").partition("/")
            found = {"release": self.releases, "release-group": self.groups}.get(kind, {}).get(ident)
            if found is not None:
                return 200, json.dumps(found).encode()
            return 404, b'{"error": "Not Found"}'
        return 404, b"Not Found"


class Stream(io.StringIO):
    """A captured stream that also keeps what it held when last flushed.

    `flushed` is what a reader on the other end of a pipe or a log file
    had seen by then. Anything written after the last flush was still
    sitting in a buffer.
    """

    flushed = ""

    def flush(self) -> None:
        super().flush()
        self.flushed = self.getvalue()


def run_identify(root: Path, job: Path, memory: Path, transport, reopen: tuple[str, ...] = (),
                 err: Stream | None = None) -> tuple[int, str, str]:
    """`batch.identify.run` offline: its exit code, stdout and stderr.

    Imported here rather than at the top, so this file loads while the
    module does not exist yet and each case fails on its own.
    """
    from musiclib.batch.identify import run
    from musiclib.batch.job import Job

    out, err = io.StringIO(), err or Stream()
    code = run(root, Job(job), memory, list(reopen), transport=transport, env={},
               which=lambda _name: None, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def no_throttle(case) -> None:
    """Drop MusicBrainz's one-second gap between requests for the rest of `case`.

    `run` takes a transport but no clock, so the client it builds sleeps
    for real between requests. A fake transport needs no rate limit, and
    ten albums would otherwise cost ten seconds or more.
    """
    patcher = mock.patch.object(mb, "_MIN_INTERVAL", 0.0)
    patcher.start()
    cleanup = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    cleanup(patcher.stop)


class _Job(unittest.TestCase):
    """A library at `<tmp>/library` and a job at `<tmp>/.musiclib/jobs/j1`, as on the box."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "library"
        self.root.mkdir()
        self.job = self.tmp / ".musiclib" / "jobs" / "j1"
        self.job.mkdir(parents=True)
        self.memory = self.tmp / ".musiclib" / "memory.json"
        no_throttle(self)

    def plan_doc(self) -> dict:
        return json.loads((self.job / "plan.json").read_text(encoding="utf-8"))


class Planning(_Job):
    def test_every_album_unit_under_root_is_planned_into_plan_json_and_review_html_is_written(self):
        # Created out of path order, so a plan.json in creation order shows.
        catalogue = [release(1, "Zebra", "Last", ["One", "Two"]),
                     release(2, "Aardvark", "First", ["Three"]),
                     release(3, "Moth", "Middle", ["Four", "Five"])]
        keys = ["Z/Zebra/Last [rip]", "A/Aardvark/First [rip]", "M/Moth/Middle [rip]"]
        for key, (found, _group) in zip(keys, catalogue):
            album(self.root, key, [t["title"] for t in found["media"][0]["tracks"]],
                  release_id=found["id"])

        run_identify(self.root, self.job, self.memory, Services(catalogue))

        doc = self.plan_doc()
        self.assertEqual(doc["job"], "j1")
        # The temp directory is under a symlink on macOS (/var -> /private/var),
        # so an unresolved root shows here.
        self.assertEqual(doc["root"], str(self.root.resolve()))
        self.assertEqual([entry["source"] for entry in doc["albums"]], sorted(keys))
        by_source = {entry["source"]: entry for entry in doc["albums"]}
        for key, (found, _group) in zip(keys, catalogue):
            self.assertEqual(by_source[key]["release_id"], found["id"], key)
            self.assertEqual(by_source[key]["status"], "certain", key)
        page = self.job / "review.html"
        self.assertTrue(page.is_file(), "no review.html in the job")
        self.assertGreater(page.stat().st_size, 0, "review.html is empty")

    def test_the_cli_runs_batch_identify_on_a_library_and_writes_the_job(self):
        # An empty library, so the real transport the CLI builds is never
        # called and the case stays offline.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                code = main(["batch", "identify", str(self.root), "--job", str(self.job)])
            except SystemExit as exc:
                # argparse refusing the subcommand; its message is in `err`.
                code = exc.code

        self.assertEqual(code, 0, err.getvalue())
        self.assertEqual(self.plan_doc(), {"job": "j1", "root": str(self.root.resolve()), "albums": []})
        self.assertTrue((self.job / "review.html").is_file(), "no review.html in the job")


class Progress(_Job):
    def test_each_album_puts_its_number_and_key_on_stderr_flushed_as_it_starts(self):
        # Created out of path order, so lines written in creation order show.
        catalogue = [release(1, "Zebra", "Last", ["One", "Two"]),
                     release(2, "Aardvark", "First", ["Three"]),
                     release(3, "Moth", "Middle", ["Four", "Five"])]
        keys = ["Z/Zebra/Last [rip]", "A/Aardvark/First [rip]", "M/Moth/Middle [rip]"]
        for key, (found, _group) in zip(keys, catalogue):
            album(self.root, key, [t["title"] for t in found["media"][0]["tracks"]],
                  release_id=found["id"])
        expected = [f"identify: {n}/3 {key}" for n, key in enumerate(sorted(keys), start=1)]
        release_of = {key: found["id"] for key, (found, _group) in zip(keys, catalogue)}

        # What stderr had flushed when each album's first request went out.
        # A line printed only at the end, or printed and left in a buffer,
        # tells the owner nothing during a run that takes hours.
        err = Stream()
        services = Services(catalogue)
        seen_at_start: dict[str, list[str]] = {}

        def transport(url, headers):
            for key, rid in release_of.items():
                if rid in url:
                    seen_at_start.setdefault(key, err.flushed.splitlines())
            return services(url, headers)

        code, out, text = run_identify(self.root, self.job, self.memory, transport, err=err)

        self.assertEqual(code, 0, text)
        self.assertEqual(text.splitlines(), expected)
        for n, key in enumerate(sorted(keys), start=1):
            self.assertEqual(seen_at_start.get(key), expected[:n], f"stderr when {key} started")
        # The counts are all stdout carries, as before this change.
        self.assertEqual(out.splitlines(), ["status certain: 3", "state auto: 3"])


class Resume(_Job):
    def test_a_run_interrupted_at_the_third_of_four_albums_repeats_no_request_when_run_again(self):
        catalogue = [release(n, f"Band {n}", f"Album {n}", ["One", "Two"]) for n in range(1, 5)]
        keys = [f"B/Band {n}/Album {n} [rip]" for n in range(1, 5)]
        for key, (found, _group) in zip(keys, catalogue):
            album(self.root, key, ["One", "Two"], release_id=found["id"])
        third = catalogue[2][0]["id"]

        first = Services(catalogue, interrupt=third)
        with contextlib.suppress(KeyboardInterrupt):
            run_identify(self.root, self.job, self.memory, first)

        # The first run got as far as album 3 and had answers for 1 and 2,
        # or there is nothing for the second run to repeat.
        self.assertIsNotNone(first.interrupted, "the first run never asked for album 3")
        for found, _group in catalogue[:2]:
            self.assertTrue(any(found["id"] in url for url in first.answered),
                            f"the first run never asked for {found['id']}")

        second = Services(catalogue)
        run_identify(self.root, self.job, self.memory, second)

        self.assertEqual(sorted(set(first.answered) & set(second.answered)), [],
                         "asked again for what the first run already has")
        self.assertIn(first.interrupted, second.answered, "the second run did not finish album 3")
        self.assertEqual([entry["source"] for entry in self.plan_doc()["albums"]], keys)


#: A 14-track album whose third track is the one that goes missing.
V_TITLES = ["Sugar", "Maps", "It Was Always You", "Animals", "Unkiss Me", "Leaving California",
            "In Your Pocket", "New Love", "Coming Back for You", "Feelings", "My Heart Is Open",
            "Shoot Love", "Sex and Candy", "Lost Stars"]

#: A few bytes under an `.mp3` name: what a drop cut off in the first frame leaves.
TRUNCATED = b"ID3\x04\x00garbage"


class Unreadable(_Job):
    """`plan_entry(..., drop_unreadable=True)`: an album with a file or folder it cannot read is planned from the rest and held.

    Every readable file here carries the release ID of a 14-track release, so
    MusicBrainz is asked for that release directly. A rip one file short does
    not match its counts, so identify goes on to search, and the search here
    answers with every release in the catalogue, the way MusicBrainz's would
    for the album's own title.
    """

    ARTIST, ALBUM = "Maroon 5", "V"
    KEY = "M/Maroon 5/V"

    class Searching(Services):
        """`Services`, with a release search that lists every release it was given."""

        def __call__(self, url, headers):
            path = urlsplit(url).path.rstrip("/")
            if urlsplit(url).netloc == "musicbrainz.org" and path == "/ws/2/release":
                self.answered.append(url)
                listing = [{"id": found["id"], "title": found["title"], "score": 100,
                            "media": [{"track-count": len(m["tracks"])} for m in found["media"]]}
                           for found in self.releases.values()]
                return 200, json.dumps({"releases": listing, "count": len(listing)}).encode()
            return super().__call__(url, headers)

    def rip(self, titles: list[str], release_id: str | None, *, leave_out=(), unreadable=(),
            numbers: dict[int, int] | None = None, names: dict[int, str] | None = None,
            tag_numbers: bool = True, key: str | None = None) -> Path:
        """The album at `key` (else `KEY`): one tagged FLAC per title, less `leave_out`, and `unreadable` as truncated MP3s.

        A file is `NN Title.flac` for its 1-based position. `numbers` gives a
        position another track number tag, `names` another filename, and
        `tag_numbers=False` writes no track or disc number at all, so the
        filename is all that says where a file goes.
        """
        base = self.root / (key or self.KEY)
        base.mkdir(parents=True)
        for number, title in enumerate(titles, start=1):
            if number in leave_out:
                continue
            path = base / ((names or {}).get(number) or f"{number:02d} {title}.flac")
            shutil.copyfile(builders.FIXTURES / "tone.flac", path)
            fields = {"title": [title], "artist": [self.ARTIST], "album": [self.ALBUM], "date": ["2014"]}
            if release_id:
                fields["release id"] = [release_id]
            tagged = (numbers or {}).get(number, number)
            builders.write_tags(path, builders.picard_tags(
                "flac", fields, track=(tagged, len(titles)) if tag_numbers else None,
                disc=(1, 1) if tag_numbers else None))
        for name in unreadable:
            (base / name).write_bytes(TRUNCATED)
        shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
        return base

    def entry(self, catalogue, *, decision: dict | None = None, **flags) -> dict:
        """The album's `plan_entry` against `catalogue`, the flags passed as given."""
        from musiclib.batch.identify import clients, plan_entry
        from musiclib.batch.job import Job
        from musiclib.units import units

        [unit] = units(self.root)
        built = clients(Job(self.job), transport=self.Searching(catalogue), env={}, which=lambda _name: None)
        entry, _plan = plan_entry(unit, self.root, built, {}, decision, False, env={},
                                  which=lambda _name: None, **flags)
        return entry

    @staticmethod
    def missing(entry: dict) -> list[str]:
        return [hold["detail"] for hold in entry["holds"] if hold["kind"] == "missing"]

    def v(self, number: int = 1, titles: list[str] = V_TITLES, title: str = "V") -> tuple[dict, dict]:
        return release(number, self.ARTIST, title, titles)

    def test_a_truncated_track_is_left_out_and_the_album_is_planned_from_its_other_13_files(self):
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"])

        entry = self.entry([v], drop_unreadable=True)

        self.assertNotIn("unidentified: unreadable files", [h["detail"] for h in entry["holds"]])
        self.assertEqual([c["release_id"] for c in entry["candidates"]], [v[0]["id"]])
        self.assertEqual(entry["release_id"], v[0]["id"])
        # Each file on its own track: the fourth file is track 4, not the gap at 3.
        expected = {f"{self.KEY}/{n:02d} {title}.flac": f"1-{n}"
                    for n, title in enumerate(V_TITLES, start=1) if n != 3}
        self.assertEqual({f["source"]: f["position"] for f in entry["files"]}, expected)

    def test_a_truncated_track_whose_number_fits_the_gap_is_named_as_the_missing_track(self):
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"])

        entry = self.entry([v], drop_unreadable=True)

        self.assertEqual(entry["holds"].count(
            {"kind": "missing",
             "detail": 'track 3, "It Was Always You": 03 It Was Always You.mp3 could be it, but it cannot be read'}), 1)
        self.assertEqual(len(self.missing(entry)), 1, entry["holds"])

    def test_the_gap_is_found_from_track_number_tags_before_filenames(self):
        # Files renamed 01 to 13 in order, tags still 1, 2, 4 to 14: by name
        # the gap would be track 14. The unreadable file has no number, so
        # nothing on disk "could be it".
        v = self.v()
        names = {n: f"{(n if n < 3 else n - 1):02d} {title}.flac" for n, title in enumerate(V_TITLES, start=1)}
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["It Was Always You.mp3"], names=names)

        entry = self.entry([v], drop_unreadable=True)

        self.assertEqual(self.missing(entry), ['track 3, "It Was Always You"'])

    def test_with_no_track_number_tags_the_gap_is_found_from_filenames(self):
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"],
                 tag_numbers=False)

        entry = self.entry([v], drop_unreadable=True)

        self.assertEqual(self.missing(entry), [
            'track 3, "It Was Always You": 03 It Was Always You.mp3 could be it, but it cannot be read'])

    def test_the_missing_hold_stays_when_the_owner_accepts_the_top_release(self):
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"])

        entry = self.entry([v], decision={"action": "accept", "release_id": v[0]["id"]}, drop_unreadable=True)

        self.assertEqual(entry["decision"], "accept")
        self.assertEqual(self.missing(entry), [
            'track 3, "It Was Always You": 03 It Was Always You.mp3 could be it, but it cannot be read'])

    def test_the_missing_hold_stays_under_an_accept_of_another_release_and_names_its_track(self):
        # The accepted release is what the album would be written as, so its
        # third track names the gap. Release 1 sorts first, so it is the top
        # candidate until the owner picks release 2.
        v = self.v()
        deluxe_titles = V_TITLES[:2] + ["Its Always You (Deluxe)"] + V_TITLES[3:]
        deluxe = self.v(2, deluxe_titles, "V (Deluxe)")
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"])

        entry = self.entry([v, deluxe], decision={"action": "accept", "release_id": deluxe[0]["id"]},
                           drop_unreadable=True)

        self.assertEqual(entry["decision"], "accept")
        self.assertEqual(self.missing(entry), [
            'track 3, "Its Always You (Deluxe)": 03 It Was Always You.mp3 could be it, but it cannot be read'])

    def test_two_unreadable_files_against_a_release_one_track_longer_each_get_the_fallback_line(self):
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3},
                 unreadable=["03 It Was Always You.mp3", "15 Hidden Track.mp3"])

        entry = self.entry([v], drop_unreadable=True)

        self.assertCountEqual(self.missing(entry), [
            "a track is missing: 03 It Was Always You.mp3 cannot be read",
            "a track is missing: 15 Hidden Track.mp3 cannot be read",
        ])

    def test_a_position_claimed_twice_gives_the_fallback_line_even_when_the_counts_fit(self):
        # Track 5's file is tagged 4, so 3 and 5 are both unclaimed and the
        # one unreadable file could be either.
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"], numbers={5: 4})

        entry = self.entry([v], drop_unreadable=True)

        self.assertEqual(self.missing(entry), ["a track is missing: 03 It Was Always You.mp3 cannot be read"])

    def test_with_no_release_found_each_unreadable_file_gets_the_fallback_line(self):
        self.rip(V_TITLES, None, leave_out={3}, unreadable=["03 It Was Always You.mp3"])

        entry = self.entry([], drop_unreadable=True)

        self.assertEqual(entry["candidates"], [])
        self.assertEqual(self.missing(entry), ["a track is missing: 03 It Was Always You.mp3 cannot be read"])

    def test_an_unreadable_file_in_a_subfolder_is_named_by_its_path_in_the_album(self):
        # Where the album holds no release to name the track from, the file
        # still has to be found on disk: its path from the album folder.
        base = self.rip(V_TITLES, None, leave_out={3})
        (base / "Extras").mkdir()
        (base / "Extras" / "03 It Was Always You.mp3").write_bytes(TRUNCATED)

        entry = self.entry([], drop_unreadable=True)

        self.assertEqual(self.missing(entry), ["a track is missing: Extras/03 It Was Always You.mp3 cannot be read"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root lists a folder whatever its mode")
    def test_a_subfolder_that_cannot_be_listed_holds_the_album_and_the_rest_is_still_planned(self):
        v = self.v()
        base = self.rip(V_TITLES, v[0]["id"])
        scans = base / "Scans"
        scans.mkdir()
        shutil.copyfile(builders.FIXTURES / "cover.jpg", scans / "back.jpg")
        os.chmod(scans, 0)
        # Registered after the temp directory's cleanup, so it runs first and
        # the directory can be removed.
        self.addCleanup(os.chmod, scans, 0o755)

        entry = self.entry([v], drop_unreadable=True)

        self.assertEqual(self.missing(entry), ["tracks may be missing: Scans cannot be read"])
        self.assertEqual(entry["release_id"], v[0]["id"])
        self.assertEqual(len(entry["files"]), 14)

    def test_without_the_flag_an_album_with_an_unreadable_file_is_unidentified_and_planned_no_further(self):
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"])

        entry = self.entry([v])

        self.assertEqual(entry["status"], "unidentified")
        self.assertEqual(entry["holds"], [{"kind": "status", "detail": "unidentified: unreadable files"}])
        self.assertEqual((entry["candidates"], entry["files"], entry["release_id"]), ([], [], None))

    def test_batch_identify_without_the_flag_still_reports_unreadable_files(self):
        v = self.v()
        self.rip(V_TITLES, v[0]["id"], leave_out={3}, unreadable=["03 It Was Always You.mp3"])

        code, _out, err = run_identify(self.root, self.job, self.memory, self.Searching([v]))

        self.assertEqual(code, 0, err)
        [entry] = self.plan_doc()["albums"]
        self.assertEqual(entry["holds"], [{"kind": "status", "detail": "unidentified: unreadable files"}])

    def test_the_cli_passes_drop_unreadable_through_to_each_album(self):
        # Files that disagree on the album tag stop identify before any
        # request, so the real transport the CLI builds is never called. The
        # missing hold in plan.json is the flag arriving at the album.
        base = self.rip(["One", "Two"], None, unreadable=["03 Three.mp3"])
        builders.write_tags(base / "02 Two.flac", {"ALBUM": ["Something Else"]})

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                code = main(["batch", "identify", str(self.root), "--job", str(self.job), "--drop-unreadable"])
            except SystemExit as exc:
                # argparse refusing the flag; its message is in `err`.
                code = exc.code

        self.assertEqual(code, 0, err.getvalue())
        [entry] = self.plan_doc()["albums"]
        self.assertEqual([h for h in entry["holds"] if h["kind"] == "missing"],
                         [{"kind": "missing", "detail": "a track is missing: 03 Three.mp3 cannot be read"}])



class StraysArchive(Services):
    """`Services`, with a Cover Art Archive that has `art` for every release: `(types, bytes)` per image, in order."""

    def __init__(self, catalogue: list[tuple[dict, dict]], art: list[tuple[list[str], bytes]]) -> None:
        super().__init__(catalogue)
        self.art = art

    def __call__(self, url, headers):
        parts = urlsplit(url)
        if parts.netloc == "coverartarchive.org":
            self.answered.append(url)
            path = parts.path.rstrip("/")
            for found in self.releases.values():
                base = f"/release/{found['id']}"
                if path == base:
                    listing = [{"id": n, "types": types, "front": "Front" in types, "back": "Back" in types,
                                "image": f"https://coverartarchive.org{base}/{n}.jpg", "thumbnails": {}}
                               for n, (types, _data) in enumerate(self.art, 1)]
                    return 200, json.dumps({"images": listing}).encode()
                for n, (_types, data) in enumerate(self.art, 1):
                    if path == f"{base}/{n}.jpg":
                        return 200, data
            return 404, b"Not Found"
        return super().__call__(url, headers)


class Strays(unittest.TestCase):
    """The owner's answers for strays, planned by identify and rebuilt by apply.

    The album is `tests.test_batch_apply.Library`'s, so identify, the
    decision and apply run the way a round does. Its strays:

    - `COVERS/first-back.jpg`, which agitha guesses as `back.jpg`;
    - `COVERS/IMG_0001.jpg`, which has no guess, so it holds the album with
      `subfolder: COVERS` until the owner names it;
    - `Extras/info.txt`, which keeps its own name.

    Every image has its own pixel size, so no two are copies of each other.
    """

    KEY = "A/Alpha/First [rip]"
    BACK = "COVERS/first-back.jpg"
    UNNAMED = "COVERS/IMG_0001.jpg"
    INFO = "Extras/info.txt"

    def setUp(self):
        # Imported here: `tests.test_batch_apply` imports this module at its top.
        from tests.test_batch_apply import Library

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        no_throttle(self)
        self.lib = Library(Path(tmp.name))
        self.base = self.lib.add(self.KEY, 1)
        self.bytes = {self.BACK: builders.jpeg(700, 600), self.UNNAMED: builders.jpeg(640, 480),
                      self.INFO: b"ripped by me"}

    def strays(self, *paths: str) -> None:
        for rel in paths:
            (self.base / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.base / rel).write_bytes(self.bytes[rel])

    def accept(self, answers: dict) -> dict:
        """Identify, then an accept of the album's own release carrying `answers`, folded in by identify again."""
        self.lib.identify()
        self.lib.decide({self.KEY: {**self.lib.accept(self.KEY), "strays": answers}})
        return self.lib.entries()[self.KEY]

    def destination(self) -> Path:
        return self.lib.root / self.lib.entries()[self.KEY]["destination"]

    def assertRefusedAsChanged(self) -> None:
        before = builders.tree(self.lib.root)
        code, _out, err = self.lib.apply()
        self.assertEqual(code, 1, err)
        self.assertIn(f"{self.KEY}: its plan has changed since identify; refused", err.splitlines())
        self.assertEqual(self.lib.log(), [])
        self.assertEqual(builders.tree(self.lib.root), before)

    def test_an_accepts_strays_replace_agithas_answers_in_the_entry_and_a_path_it_leaves_out_keeps_agithas(self):
        self.strays(self.BACK, self.UNNAMED, self.INFO)

        entry = self.accept({self.UNNAMED: "booklet-01.jpg", self.BACK: None})

        rows = {row["path"]: row for row in entry.get("strays") or []}
        self.assertEqual(rows, {
            self.BACK: {"path": self.BACK, "kind": "image", "answer": {"delete": True}, "why": "owner",
                        "against": None, "size": [700, 600]},
            self.UNNAMED: {"path": self.UNNAMED, "kind": "image", "answer": {"keep": "booklet-01.jpg"},
                           "why": "owner", "against": None, "size": [640, 480]},
            self.INFO: {"path": self.INFO, "kind": "text", "answer": {"keep": "info.txt"}, "why": "guessed",
                        "against": None, "size": None},
        })

    def test_an_accepts_named_stray_is_a_move_into_the_album_folder_and_its_null_stray_a_deletion(self):
        self.strays(self.BACK, self.UNNAMED)

        entry = self.accept({self.UNNAMED: "booklet-01.jpg", self.BACK: None})

        self.assertIn(f"move: {self.KEY}/{self.UNNAMED} -> {entry['destination']}/booklet-01.jpg", entry["changes"])
        self.assertIn(f"delete: {self.KEY}/{self.BACK}", entry["changes"])
        # Nothing is left in COVERS, so nothing holds the album.
        self.assertEqual(entry["holds"], [])

    def test_an_album_whose_strays_all_have_a_guess_is_planned_with_no_subfolder_hold(self):
        self.strays(self.BACK, self.INFO)

        self.lib.identify()

        entry = self.lib.entries()[self.KEY]
        # The control: both strays are in the plan, moved, so the missing hold is not for want of a subfolder.
        self.assertIn(f"move: {self.KEY}/{self.BACK} -> {entry['destination']}/back.jpg", entry["changes"])
        self.assertIn(f"move: {self.KEY}/{self.INFO} -> {entry['destination']}/info.txt", entry["changes"])
        self.assertEqual(entry["holds"], [])
        self.assertEqual(entry["state"], "auto")

    def test_apply_rebuilds_an_accept_with_strays_to_the_same_digest_and_lands_them_under_the_owners_names(self):
        self.strays(self.BACK, self.UNNAMED, self.INFO)
        self.accept({self.UNNAMED: "booklet-01.jpg", self.BACK: None})

        code, _out, err = self.lib.apply()

        self.assertEqual(code, 0, err)
        destination = self.destination()
        self.assertEqual((destination / "booklet-01.jpg").read_bytes(), self.bytes[self.UNNAMED])
        self.assertEqual((destination / "info.txt").read_bytes(), self.bytes[self.INFO])
        self.assertFalse((destination / "back.jpg").exists(), "the stray the owner deleted was kept")
        self.assertFalse((self.base / "COVERS").exists(), "COVERS is still in the rip")

    def test_a_stray_that_beats_the_archives_image_is_rebuilt_from_the_warm_cache_to_the_same_digest(self):
        # The quality test reads the archive's pixel sizes, so apply has to
        # read the same bytes identify did. The stray has
        # more than 10 % more pixels than the archive's back, so it wins.
        archive_back = builders.jpeg(500, 500)
        self.strays(self.BACK)
        services = StraysArchive(self.lib.catalogue, [(["Back"], archive_back)])
        run_identify(self.lib.root, self.lib.job, self.lib.memory, services)
        entry = self.lib.entries()[self.KEY]
        self.assertEqual(entry["state"], "auto", entry["holds"])
        # The control: the archive's back was fetched and not saved, so the quality test ran against it.
        self.assertTrue(any(url.endswith("/1.jpg") for url in services.answered), services.answered)
        self.assertNotIn("back.jpg", entry["images"])

        code, _out, err = self.lib.apply()

        self.assertEqual(code, 0, err)
        self.assertEqual((self.destination() / "back.jpg").read_bytes(), self.bytes[self.BACK])

    def test_apply_refuses_the_album_as_changed_when_a_stray_the_owner_named_has_other_bytes(self):
        self.strays(self.BACK, self.UNNAMED)
        self.accept({self.UNNAMED: "booklet-01.jpg"})
        # Bytes after the JPEG's end: the same picture at the same size, so
        # only the bytes tell it from the file identify saw.
        with open(self.base / self.UNNAMED, "ab") as handle:
            handle.write(b"\0changed")

        self.assertRefusedAsChanged()

    def test_apply_refuses_the_album_as_changed_when_a_stray_kept_under_agithas_guess_has_other_bytes(self):
        self.strays(self.BACK, self.INFO)
        self.lib.identify()
        self.assertEqual(self.lib.states(), {self.KEY: "auto"})
        with open(self.base / self.BACK, "ab") as handle:
            handle.write(b"\0changed")

        self.assertRefusedAsChanged()

    def test_apply_refuses_the_album_as_changed_when_a_kept_stray_is_gone(self):
        self.strays(self.BACK, self.UNNAMED)
        self.accept({self.UNNAMED: "booklet-01.jpg"})
        (self.base / self.UNNAMED).unlink()

        self.assertRefusedAsChanged()


if __name__ == "__main__":
    unittest.main()
