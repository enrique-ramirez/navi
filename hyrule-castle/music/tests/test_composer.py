"""Composer and composer sort, from the works MusicBrainz links each recording to.

For every release it plans, a
job makes one more lookup, `/release/{mbid}?inc=recordings+recording-level-
rels+work-rels+work-level-rels+artist-rels`. A track's composers are the
artists of every `composer` relationship on each work its recording has a
`performance` relationship to, in MusicBrainz's order, each artist once. They
are written under Picard's two keys, the names in the English alias where the
name is not Latin, the sort names as MusicBrainz gives them. A track with no
composer keeps the two tags its file has. `--no-composer` makes no lookup and
touches neither tag.

`tests/fixtures/mb/release-works.json` has the shape of the real answer for
the *Chrono Cross* soundtrack (`d85cdc92-44dd-352f-925c-8970a3942b5c`,
fetched 2026-09-29): each track's recording carries `relations`, a
`performance` one to a work (`target-type` `work`, `direction` `forward`)
beside artist relations such as `arranger` and `instrument`. The work carries
its own `relations`: `composer`, `lyricist` and `writer` ones to an artist
(`direction` `backward`, the artist with `id`, `name` and `sort-name`), and
work-to-work ones such as `arrangement`. The release has its own artist
relations at the top. The four tracks and their works are made up:

1. one work, composed by `光田康典`, then `下村陽子`, then `光田康典` again,
   with a `lyricist` relationship and an `arrangement` between them. The
   recording also has `光田康典` as `arranger`.
2. a medley: two `performance` relationships, to a work composed by Kenji Ito
   and to one composed by Hiroki Kikuta, then written by Wanda Writer, then
   composed by Kenji Ito. So the track's composers are Kenji Ito, then Hiroki
   Kikuta: not the alphabetical order, and not the second work's order.
3. one work with only `writer` and `lyricist` relationships.
4. no work at all.

The release itself is credited a `composer` at the top level, which no track
may take.

`光田康典`'s artist lookup lists a primary alias with locale `en`, `Yasunori
Mitsuda`, after an English one that is not primary. `下村陽子` has an English
alias that is not primary and a primary one in Japanese, so no English one:
her name stays as it is.

Every job is built the real way, with `tests.test_batch_identify`'s fake
MusicBrainz, extended here to answer the work relations lookup from the
fixture, to answer artist lookups with aliases, and to fail on demand. Each
album is tagged with its own release, whose four recordings are the
fixture's, and its files already carry a composer and a composer sort, so
what a plan keeps and what it replaces both show. Apply gets a transport
that refuses every request: identify left the cache warm.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from mutagen.asf import ASF
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4

from musiclib import mb
from musiclib.__main__ import main
from tests import builders
from tests import test_batch_identify as batch

WORKS: dict = json.loads((builders.FIXTURES / "mb" / "release-works.json").read_text(encoding="utf-8"))
WORKS_URL = ("https://musicbrainz.org/ws/2/release/{mbid}"
             "?inc=recordings+recording-level-rels+work-rels+work-level-rels+artist-rels&fmt=json")

RELEASE_PATH = "/ws/2/release/"
ARTIST_PATH = "/ws/2/artist/"

#: The fixture's four recordings, track 1 to 4.
RECORDINGS = [track["recording"]["id"] for track in WORKS["media"][0]["tracks"]]
TITLES = [track["title"] for track in WORKS["media"][0]["tracks"]]

MITSUDA_ID = "118bf512-9ce9-42a5-95e0-10359bb3e3ea"
SHIMOMURA_ID = "c5c5c5c5-0000-4000-8000-000000000002"


def artist_json(artist_id: str, name: str, sort_name: str, aliases: list[tuple[str, str, str | None, bool]]) -> dict:
    """An artist as `mb.artist` returns it, with `(name, sort name, locale, primary)` aliases."""
    return {"id": artist_id, "name": name, "sort-name": sort_name, "genres": [],
            "aliases": [{"name": alias, "sort-name": sort, "type": "Artist name", "locale": locale,
                         "primary": primary, "begin": None, "end": None, "ended": False}
                        for alias, sort, locale, primary in aliases]}


#: Only the artist lookup has aliases, never the work relations lookup. Each
#: alias has a sort name of its own, which the composer sort must not take.
ARTISTS = {
    MITSUDA_ID: artist_json(MITSUDA_ID, "光田康典", "Mitsuda, Yasunori", [
        ("Mitsuda Yasunori", "Mitsuda Yasunori", "en", False),
        ("Yasunori Mitsuda", "Yasunori Mitsuda", "en", True),
    ]),
    SHIMOMURA_ID: artist_json(SHIMOMURA_ID, "下村陽子", "Shimomura, Yoko", [
        ("Yoko Shimomura", "Yoko Shimomura", "en", False),
        ("下村陽子", "下村陽子", "ja", True),
    ]),
}

#: Tracks 1 and 2: `(composer, composer sort)` as planned and written.
COMPOSED = {
    1: (["Yasunori Mitsuda", "下村陽子"], ["Mitsuda, Yasunori", "Shimomura, Yoko"]),
    2: (["Kenji Ito", "Hiroki Kikuta"], ["Ito, Kenji", "Kikuta, Hiroki"]),
}
#: What every file carries before any job, and what tracks 3 and 4 keep.
OWN = (["Old Composer"], ["Composer, Old"])
UNCOMPOSED = (3, 4)

#: Picard's composer and composer sort keys, as `files.read` names them.
KEYS = {
    "mp3": ("TCOM", "TSOC"),
    "flac": ("composer", "composersort"),
    "m4a": ("\xa9wrt", "soco"),
    "wma": ("WM/Composer", "WM/ComposerSortOrder"),
}
FORMATS = tuple(KEYS)


def works_for(release_id: str) -> dict:
    return {**copy.deepcopy(WORKS), "id": release_id}


class Catalogue(batch.Services):
    """`tests.test_batch_identify.Services`, answering work relations and artists as well.

    The base answers any `/ws/2/release/<id>` with the release, whatever it
    asks to include, so a work relations lookup is told apart here by
    `work-rels` in its query. `works` maps a release ID to what that lookup
    answers instead of the fixture: a status, or `"down"` for a network that
    fails. `failing_artists` answer 503.
    """

    def __init__(self, catalogue, *, works: dict[str, int | str] | None = None,
                 failing_artists: tuple[str, ...] = ()) -> None:
        super().__init__(catalogue)
        self.works = works or {}
        self.failing_artists = set(failing_artists)

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        if parts.netloc == "musicbrainz.org" and parts.path.startswith(RELEASE_PATH) and "work-rels" in parts.query:
            self.answered.append(url)
            release_id = parts.path[len(RELEASE_PATH):]
            failure = self.works.get(release_id)
            if failure == "down":
                raise ConnectionError(url)
            if failure is not None:
                return failure, b'{"error": "failed"}'
            if release_id not in self.releases:
                return 404, b'{"error": "Not Found"}'
            return 200, json.dumps(works_for(release_id)).encode()
        if parts.netloc == "musicbrainz.org" and parts.path.startswith(ARTIST_PATH):
            self.answered.append(url)
            artist_id = parts.path[len(ARTIST_PATH):]
            if artist_id in self.failing_artists:
                return 503, b"<html>503 Service Temporarily Unavailable</html>"
            found = ARTISTS.get(artist_id)
            if found is None:
                return 404, b'{"error": "Not Found"}'
            return 200, json.dumps(found).encode()
        return super().__call__(url, headers)

    def works_urls(self) -> list[str]:
        return [url for url in self.answered if "work-rels" in url]


def own_composer(ext: str) -> dict:
    """`OWN` under `ext`'s composer keys, as `builders.write_tags` takes them."""
    name, sort = KEYS[ext]
    if ext == "flac":
        name, sort = name.upper(), sort.upper()
    if ext == "mp3":
        return {name: OWN[0][0], sort: OWN[1][0]}
    return {name: list(OWN[0]), sort: list(OWN[1])}


def release_for(number: int, artist: str, title: str, *, genres: dict[str, int] | None = None) -> tuple[dict, dict]:
    """A release and group as `tests.test_batch_identify.release` builds them, on the fixture's recordings."""
    found, group = batch.release(number, artist, title, TITLES, genres=genres)
    for track, recording in zip(found["media"][0]["tracks"], RECORDINGS):
        track["recording"]["id"] = recording
    return found, group


def rip(root: Path, key: str, ext: str, release_id: str) -> Path:
    """An album of `ext` files at `root/key`, tagged with `release_id`, each carrying `OWN`."""
    base = root / key
    base.mkdir(parents=True)
    artist, album = key.split("/")[1], key.split("/")[2].split(" [")[0]
    for number, title in enumerate(TITLES, start=1):
        path = builders.copy_fixture(base, ext, f"{number:02d} {title.lower()}")
        fields = {"title": [title.lower()], "artist": [artist], "album": [album], "date": ["1999"],
                  "release id": [release_id]}
        tags = builders.picard_tags(ext, fields, track=(number, len(TITLES)), disc=(1, 1))
        tags.update(own_composer(ext))
        builders.write_tags(path, tags, v2_version=4)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


def on_disk(path: Path, ext: str) -> tuple[list[str] | None, list[str] | None]:
    """The composer and composer sort values in the file, read with mutagen."""
    if ext == "mp3":
        tags = ID3(path)
        return tuple(list(tags[key].text) if key in tags else None for key in KEYS[ext])
    if ext == "flac":
        tags = FLAC(path)
        return tuple(tags.get(key) for key in KEYS[ext])
    if ext == "m4a":
        tags = MP4(path).tags or {}
        return tuple(list(tags[key]) if key in tags else None for key in KEYS[ext])
    tags = ASF(path).tags or {}
    return tuple([str(value) for value in tags[key]] if key in tags else None for key in KEYS[ext])


def expected(number: int) -> tuple[list[str], list[str]]:
    return COMPOSED.get(number, OWN)


class Base:
    """A library at `<base>/library`, jobs at `<base>/.musiclib/jobs/<id>`, as on the box."""

    def __init__(self, case) -> None:
        tmp = tempfile.TemporaryDirectory()
        cleanup = case.addClassCleanup if isinstance(case, type) else case.addCleanup
        cleanup(tmp.cleanup)
        batch.no_throttle(case)
        self.base = Path(tmp.name)
        self.root = self.base / "library"
        self.root.mkdir()
        self.memory = self.base / ".musiclib" / "memory.json"
        self.catalogue: list[tuple[dict, dict]] = []
        self.keys: dict[str, str] = {}

    def job(self, name: str) -> Path:
        path = self.base / ".musiclib" / "jobs" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def add(self, number: int, ext: str, **release_args) -> str:
        """One album of `ext` files with release `number`; its key."""
        key = f"C/Composer {number} {ext}/Works {number} [rip]"
        found, group = release_for(number, f"Composer {number} {ext}", f"Works {number}", **release_args)
        self.catalogue.append((found, group))
        rip(self.root, key, ext, found["id"])
        self.keys[key] = ext
        return key

    def release_ids(self) -> list[str]:
        return [found["id"] for found, _group in self.catalogue]

    def identify(self, job: str, services) -> dict[str, dict]:
        batch.run_identify(self.root, self.job(job), self.memory, services)
        return self.entries(job)

    def identify_by_cli(self, job: str, services, *flags: str) -> tuple[int, str, dict[str, dict]]:
        """`musiclib batch identify ROOT --job DIR [flags]` with `services` as the network.

        AcoustID is unavailable: no key in the environment.
        """
        err = io.StringIO()
        argv = ["batch", "identify", str(self.root), "--job", str(self.job(job)), *flags]
        with mock.patch.object(mb, "default_transport", services), \
                mock.patch.dict(os.environ, {"ACOUSTID_API_KEY": ""}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                code = main(argv)
            except SystemExit as exc:
                # argparse refusing a flag; its message is in `err`.
                code = exc.code
        entries = self.entries(job) if code == 0 else {}
        return code, err.getvalue(), entries

    def entries(self, job: str) -> dict[str, dict]:
        doc = json.loads((self.job(job) / "plan.json").read_text(encoding="utf-8"))
        return {entry["source"]: entry for entry in doc["albums"]}

    def apply(self, job: str) -> tuple[int, str, list[dict]]:
        """`batch.apply.run` on `job`, with a transport that refuses: its exit code, stderr and log."""
        from musiclib.batch.apply import run
        from musiclib.batch.job import Job

        def refuse(url, headers):
            raise AssertionError(f"apply went to the network for {url}")

        systemctl = self.base / "systemctl"
        systemctl.write_text("#!/bin/sh\necho inactive\nexit 3\n")
        systemctl.chmod(0o755)
        err = io.StringIO()
        code = run(Job(self.job(job)), self.memory, extras_root=self.base / "extras", live_root=self.root,
                   systemctl=str(systemctl), transport=refuse, out=io.StringIO(), err=err)
        log_path = self.job(job) / "applied.jsonl"
        log = ([json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
               if log_path.exists() else [])
        return code, err.getvalue(), log


def planned(entry: dict, number: int) -> dict:
    """The `files[]` item for track `number` of a one-medium album."""
    [found] = [f for f in entry["files"] if f["position"] == f"1-{number}"]
    return found


def composer_tags(tags: dict, ext: str) -> tuple[list[str] | None, list[str] | None]:
    return tuple(tags.get(key) for key in KEYS[ext])


class EveryFormat(unittest.TestCase):
    """One album per format through identify, apply, and a second identify over what apply wrote."""

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = Base(cls)
        cls.album = {ext: lib.add(number, ext) for number, ext in enumerate(FORMATS, start=1)}
        cls.first_services = Catalogue(lib.catalogue)
        cls.first = lib.identify("j1", cls.first_services)
        states = {key: entry["state"] for key, entry in cls.first.items()}
        if set(states.values()) != {"auto"}:
            raise AssertionError(f"the fixture did not plan every album auto: "
                                 f"{ {k: (e['state'], e['holds']) for k, e in cls.first.items()} }")
        cls.applied = lib.apply("j1")
        cls.second = lib.identify("j2", Catalogue(lib.catalogue))

    def test_each_format_plans_the_composers_of_every_performed_work_in_order_once_under_picards_two_keys(self):
        # Track 1 is `光田康典` as `Yasunori Mitsuda`, beside a Japanese name
        # with no primary English alias. Track 2 is a medley.
        for ext, key in self.album.items():
            for number in COMPOSED:
                with self.subTest(format=ext, track=number):
                    self.assertEqual(composer_tags(planned(self.first[key], number)["after"], ext), COMPOSED[number])

    def test_a_track_with_no_work_or_a_work_with_no_composer_keeps_the_files_composer_tags(self):
        for ext, key in self.album.items():
            for number in UNCOMPOSED:
                with self.subTest(format=ext, track=number):
                    self.assertEqual(composer_tags(planned(self.first[key], number)["after"], ext), OWN)

    def test_apply_writes_the_composers_into_each_file(self):
        code, err, log = self.applied
        self.assertEqual((code, sorted(line["source"] for line in log if line["outcome"] == "applied")),
                         (0, sorted(self.album.values())), err)
        for ext, key in self.album.items():
            for number in range(1, len(TITLES) + 1):
                with self.subTest(format=ext, track=number):
                    path = self.lib.root / planned(self.first[key], number)["destination"]
                    self.assertEqual(on_disk(path, ext), expected(number))

    def test_each_release_gets_one_work_relations_lookup_at_its_own_url(self):
        self.assertEqual(sorted(self.first_services.works_urls()),
                         sorted(WORKS_URL.format(mbid=release_id) for release_id in self.lib.release_ids()))

    def test_a_second_job_over_the_applied_albums_proposes_no_change(self):
        # As for every other tag: a value that does not read
        # back the way it was planned would be proposed again every job.
        self.assertEqual(len(self.second), len(self.album), list(self.second))
        for key, entry in self.second.items():
            with self.subTest(album=key):
                self.assertEqual((entry["changes"], entry["state"], entry["holds"]), ([], "unchanged", []))


class WhenTheLookupFails(unittest.TestCase):
    def setUp(self):
        self.lib = Base(self)
        # Five attempts with the real backoff would sleep 30 s per album.
        patcher = mock.patch.object(mb, "_BACKOFF", [0.0] * len(mb._BACKOFF))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_404_for_the_work_relations_means_no_composers_and_the_album_goes_ahead(self):
        key = self.lib.add(1, "flac")
        [release_id] = self.lib.release_ids()
        services = Catalogue(self.lib.catalogue, works={release_id: 404})

        entry = self.lib.identify("j1", services)[key]

        self.assertEqual(services.works_urls(), [WORKS_URL.format(mbid=release_id)])
        self.assertEqual((entry["state"], entry["holds"]), ("auto", []))
        for number in range(1, len(TITLES) + 1):
            with self.subTest(track=number):
                self.assertEqual(composer_tags(planned(entry, number)["after"], "flac"), OWN)

    def test_an_unavailable_work_relations_lookup_stops_the_album_as_an_unavailable_artist_lookup_does(self):
        # The artist lookup for genres is the same case: the album
        # below has no genre anywhere, so its plan asks for the artist's, and
        # MusicBrainz is down for that lookup alone.
        failing_503 = self.lib.add(1, "flac")
        failing_network = self.lib.add(2, "flac")
        reference = self.lib.add(3, "flac", genres={})
        ids = self.lib.release_ids()
        services = Catalogue(self.lib.catalogue, works={ids[0]: 503, ids[1]: "down"},
                             failing_artists=(batch.mbid(3, 3),))

        entries = self.lib.identify("j1", services)

        def outcome(entry):
            return {name: entry[name] for name in ("status", "state", "holds", "files", "plan_digest", "destination")}

        stopped = outcome(entries[reference])
        self.assertTrue(any("musicbrainz unavailable" in hold["detail"] for hold in stopped["holds"]),
                        f"the reference album was not stopped by its artist lookup: {stopped}")
        for key in (failing_503, failing_network):
            with self.subTest(album=key):
                self.assertEqual(outcome(entries[key]), stopped)


    def test_any_other_error_status_holds_the_album_until_the_lookup_answers(self):
        # Only a 404 means no composers. `mb` does not retry these statuses
        # and does not cache them, so apply's rebuild would get a 200, plan
        # composers and refuse the album as changed. Taken as "no composers"
        # here, a library job would skip them silently.
        statuses = (500, 400, 403, 429)
        keys = {status: self.lib.add(number, "flac") for number, status in enumerate(statuses, start=1)}
        ids = dict(zip(statuses, self.lib.release_ids()))

        held = self.lib.identify("j1", Catalogue(self.lib.catalogue,
                                                 works={ids[status]: status for status in statuses}))
        again = self.lib.identify("j1", Catalogue(self.lib.catalogue))

        for status, key in keys.items():
            with self.subTest(status=status):
                entry = held[key]
                self.assertEqual(entry["state"], "held")
                self.assertEqual([h["kind"] for h in entry["holds"]], ["error"], entry["holds"])
                self.assertIn("musicbrainz", entry["holds"][0]["detail"].lower())
                # No plan at all, so no composer tag of any kind is proposed.
                self.assertEqual((entry["files"], entry["plan_digest"]), ([], None))
                # The failure was not remembered: the next identify plans normally.
                self.assertEqual((again[key]["state"], again[key]["holds"]), ("auto", []))
                self.assertEqual(composer_tags(planned(again[key], 1)["after"], "flac"), COMPOSED[1])


class NoComposer(unittest.TestCase):
    """`--no-composer` through the CLI, apply, then a job without it over what apply wrote.

    The job with the flag stands for every job before composers existed, so
    the job after it is the first job with composers over the library.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = Base(cls)
        cls.album = {ext: lib.add(number, ext) for number, ext in enumerate(FORMATS, start=1)}
        cls.skipped_services = Catalogue(lib.catalogue)
        cls.skipped = lib.identify_by_cli("j1", cls.skipped_services, "--no-composer")
        cls.applied = cls.later = None
        if cls.skipped[0] == 0:
            cls.applied = lib.apply("j1")
            cls.later_services = Catalogue(lib.catalogue)
            cls.later = lib.identify_by_cli("j2", cls.later_services)

    def skipped_entries(self) -> dict[str, dict]:
        code, err, entries = self.skipped
        self.assertEqual(code, 0, f"batch identify --no-composer: {err}")
        self.assertEqual(sorted(entries), sorted(self.album.values()))
        return entries

    def test_no_work_relations_url_is_requested(self):
        self.skipped_entries()
        # A job that never reached the fake would pass the check below alone.
        self.assertTrue(any(RELEASE_PATH in url for url in self.skipped_services.answered),
                        self.skipped_services.answered)
        self.assertEqual(self.skipped_services.works_urls(), [])

    def test_every_files_composer_tags_are_planned_as_they_are(self):
        for key, entry in self.skipped_entries().items():
            ext = self.lib.keys[key]
            for number in range(1, len(TITLES) + 1):
                with self.subTest(album=key, track=number):
                    self.assertEqual(composer_tags(planned(entry, number)["after"], ext), OWN)

    def test_each_album_records_the_choice_in_its_inputs(self):
        entries = self.skipped_entries()
        self.assertEqual({key: entry["inputs"].get("composer") for key, entry in entries.items()},
                         {key: False for key in self.album.values()})

    def test_apply_rebuilds_the_plan_to_the_same_digest_and_writes_the_composer_tags_untouched(self):
        entries = self.skipped_entries()
        code, err, log = self.applied
        # A rebuild that looked the composers up would go to the network,
        # which apply's transport refuses. One that laid them without looking
        # would not match the digest. Either way the album is refused.
        self.assertEqual((code, sorted(line["source"] for line in log if line["outcome"] == "applied")),
                         (0, sorted(self.album.values())), err)
        for key, entry in entries.items():
            ext = self.lib.keys[key]
            for number in range(1, len(TITLES) + 1):
                with self.subTest(album=key, track=number):
                    self.assertEqual(on_disk(self.lib.root / planned(entry, number)["destination"], ext), OWN)

    def test_the_next_job_without_the_flag_proposes_the_composer_tags_and_nothing_else(self):
        # Apply moved each album, so the next job knows it by where it went.
        format_of = {entry["destination"]: self.lib.keys[key] for key, entry in self.skipped_entries().items()}
        code, err, entries = self.later
        self.assertEqual(code, 0, f"batch identify: {err}")
        self.assertEqual(sorted(self.later_services.works_urls()),
                         sorted(WORKS_URL.format(mbid=release_id) for release_id in self.lib.release_ids()))
        self.assertEqual(len(entries), len(self.album), list(entries))
        for key, entry in entries.items():
            ext = format_of[key]
            self.assertEqual((entry["inputs"].get("composer"), entry["state"], entry["holds"]), (True, "auto", []), key)
            for number in range(1, len(TITLES) + 1):
                with self.subTest(album=key, track=number):
                    track = planned(entry, number)
                    differing = {k for k in track["before"].keys() | track["after"].keys()
                                 if track["before"].get(k) != track["after"].get(k)}
                    self.assertEqual(differing, set(KEYS[ext]) if number in COMPOSED else set())
                    self.assertEqual(composer_tags(track["after"], ext), expected(number))


if __name__ == "__main__":
    unittest.main()
