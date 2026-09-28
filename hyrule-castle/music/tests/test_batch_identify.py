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


if __name__ == "__main__":
    unittest.main()
