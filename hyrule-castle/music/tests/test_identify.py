"""Which MusicBrainz release an album unit is, and how sure the engine is.

Files that already carry one release ID are looked up, never searched, and
come out `certain` when counts and durations agree. Anything else is
searched by title, album artist and track count, the candidates ranked, and
the top one `auto` only when nothing about it is in doubt. A separate status
covers identification that cannot run at all.

MusicBrainz is the real client over a temporary cache, talking to a fake
server that answers by URL and records every URL it was asked for. "No
search" means no `/ws/2/release/?query=` URL was requested. Track lengths
are set by hand, so a difference of exactly 3.0 s is exactly that.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from musiclib.batch.identify import _candidate_dict
from musiclib.identify import chosen, identify
from musiclib import files, mb, units
from musiclib.cache import Cache
from musiclib.units import Unit
from tests import builders

SEARCH_PATH = "/ws/2/release/"
RELEASE_GROUP_PATH = "/ws/2/release-group/"
RELEASE_ID_KEY = {
    "mp3": "TXXX:MusicBrainz Album Id",
    "flac": "MUSICBRAINZ_ALBUMID",
    "ogg": "MUSICBRAINZ_ALBUMID",
    "m4a": "----:com.apple.iTunes:MusicBrainz Album Id",
}

# Real-shaped MBIDs whose first characters make their sorted order obvious.
TAGGED = "3f1b0c0e-5a4d-4c1e-9d2a-7b6f0e1a2c3d"
OTHER = "7a2e9d41-0b3c-4f5e-8a6d-2c1b0e9f8d7a"
METEORA = "ccb9e64d-0c6f-3e66-bcda-cc9c190f836f"


def mbid(prefix: str) -> str:
    return f"{prefix:0<8}-0000-4000-8000-000000000000"


# --- MusicBrainz as a fake server -----------------------------------------


class FakeClock:
    """A monotonic clock that moves only when somebody sleeps on it."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.reads = 0

    def __call__(self) -> float:
        # A client that polls this clock, which stands still, would spin
        # forever. Fail it rather than hang the suite.
        self.reads += 1
        if self.reads > 10_000:
            raise AssertionError("the client polled the clock instead of sleeping")
        return self.now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError(f"sleep length must be non-negative: {seconds}")
        self.now += seconds


def release_json(release_id: str, lengths: list[list[float]], date: str = "1994-03-08",
                 *, recording_only: bool = False) -> dict:
    """A release as `mb.release` returns it: one list of track lengths (seconds) per medium.

    `recording_only` leaves the track's own length empty, as MusicBrainz does
    for some releases, so only the recording carries one.
    """
    media = []
    for position, medium in enumerate(lengths, start=1):
        tracks = []
        for number, seconds in enumerate(medium, start=1):
            ms = round(seconds * 1000)
            tracks.append({
                "position": number, "number": str(number), "title": f"Track {number}",
                "length": None if recording_only else ms,
                "recording": {"id": mbid(f"{position}{number:02d}"), "title": f"Track {number}", "length": ms},
            })
        media.append({"position": position, "format": "CD", "track-count": len(tracks), "tracks": tracks})
    return {
        "id": release_id, "title": "The Downward Spiral", "status": "Official", "date": date,
        "release-group": {"id": mbid("9"), "title": "The Downward Spiral", "primary-type": "Album"},
        "artist-credit": [{"name": "Nine Inch Nails", "joinphrase": "", "artist": {"id": mbid("8"), "name": "Nine Inch Nails"}}],
        "media": media,
    }


def search_json(*releases: dict) -> dict:
    """A search answer listing `releases`, in the order given, with their media counts.

    A release with no `date` key has none in the answer either, as
    MusicBrainz leaves it out for a release nobody dated. The status is
    listed too, as MusicBrainz lists it.
    """
    return {
        "count": len(releases), "offset": 0,
        "releases": [
            {
                "id": r["id"], "score": 100 - i, "title": r["title"],
                **({"date": r["date"]} if "date" in r else {}),
                **({"status": r["status"]} if "status" in r else {}),
                "track-count": sum(len(m["tracks"]) for m in r["media"]),
                "media": [{"format": "CD", "track-count": len(m["tracks"])} for m in r["media"]],
            }
            for i, r in enumerate(releases)
        ],
    }


def titled_json(release_id: str, tracks: list[tuple[str, float | None]], date: str = "1994-03-08",
                status: str = "Official") -> dict:
    """One medium of `(title, seconds)` tracks, as `mb.release` returns it.

    A length of `None` leaves it off both the track and its recording, as
    MusicBrainz does for a track nobody has timed.
    """
    release = release_json(release_id, [[seconds or 0 for _, seconds in tracks]], date)
    release["status"] = status
    for mb_track, (title, seconds) in zip(release["media"][0]["tracks"], tracks):
        mb_track["title"] = mb_track["recording"]["title"] = title
        if seconds is None:
            mb_track["length"] = mb_track["recording"]["length"] = None
    return release


def release_group_json(group_id: str = mbid("9"), secondary_types: tuple[str, ...] = (),
                       tags: tuple[tuple[str, int], ...] = ()) -> dict:
    """A release group as `mb.release_group` returns it, with `(name, count)` folksonomy tags.

    The default id is the one `release_json` points every release at.
    """
    return {
        "id": group_id, "title": "The Downward Spiral", "primary-type": "Album",
        "secondary-types": list(secondary_types), "first-release-date": "1994-03-08",
        "genres": [], "tags": [{"name": name, "count": count} for name, count in tags],
    }


class Server:
    """Answers MusicBrainz URLs from what it was given, and records every one.

    A release it does not know is a 404. A release group it does not know
    is a plain album with no secondary type and no tags, so a case that is
    not about release groups need not give one. `unavailable` answers 503
    to everything.
    """

    def __init__(self, releases: tuple[dict, ...] = (), search: dict | None = None,
                 unavailable: bool = False, release_groups: tuple[dict, ...] = ()) -> None:
        self.releases = {r["id"]: r for r in releases}
        self.search = search
        self.unavailable = unavailable
        self.release_groups = {g["id"]: g for g in release_groups}
        self.urls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.urls.append(url)
        if self.unavailable:
            return 503, b"<html>503 Service Temporarily Unavailable</html>"
        path = urlsplit(url).path
        if path.startswith(RELEASE_GROUP_PATH):
            group_id = path[len(RELEASE_GROUP_PATH):]
            return 200, json.dumps(self.release_groups.get(group_id) or release_group_json(group_id)).encode()
        if path == SEARCH_PATH or path == SEARCH_PATH.rstrip("/"):
            if self.search is None:
                return 404, b'{"error": "no search expected"}'
            return 200, json.dumps(self.search).encode()
        if path.startswith(SEARCH_PATH):
            found = self.releases.get(path[len(SEARCH_PATH):])
            if found is None:
                return 404, b'{"error": "Not Found"}'
            return 200, json.dumps(found).encode()
        return 404, b'{"error": "Not Found"}'

    def searches(self) -> list[dict[str, str]]:
        return [
            {k: v[0] for k, v in parse_qs(urlsplit(u).query).items()}
            for u in self.urls if "query=" in u
        ]

    def fetched(self) -> list[str]:
        return [urlsplit(u).path[len(SEARCH_PATH):] for u in self.urls
                if urlsplit(u).path.startswith(SEARCH_PATH) and "query=" not in u]


# --- album units ----------------------------------------------------------


def vorbis(folder: Path, rel: str, length: float, /, **tags: str | list[str]) -> files.Track:
    """A FLAC track at `folder/rel`, as `files.read` would give it back.

    Vorbis keys are lower case in `Track.tags`, and every value is a list.
    """
    return files.Track(
        path=str(folder / rel), family="vorbis",
        tags={k: v if isinstance(v, list) else [v] for k, v in tags.items()},
        length=length,
    )


def unit(album: Path, tracks: list[files.Track], **fields) -> Unit:
    return Unit(**{
        "path": album, "rel": "N/Nine Inch Nails/(1994) The Downward Spiral",
        "tracks": tracks, "unreadable": [], "others": [], "status": None, "reason": None,
        **fields,
    })


class IdentifyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.album = self.root / "N" / "Nine Inch Nails" / "(1994) The Downward Spiral"
        self.clock = FakeClock()

    def client(self, server: Server) -> mb.MusicBrainz:
        (self.root / "cache-dir").mkdir(exist_ok=True)
        return mb.MusicBrainz(Cache(self.root / "cache-dir"), transport=server,
                              clock=self.clock, sleep=self.clock.sleep)

    def identify(self, the_unit: Unit, server: Server, **kwargs):
        return identify(the_unit, self.client(server), **kwargs)

    def forget(self) -> None:
        """Empty the MusicBrainz cache, so a subtest that reuses an MBID fetches its own release."""
        shutil.rmtree(self.root / "cache-dir", ignore_errors=True)

    def tagged(self, lengths: list[float], release_id: str | None = TAGGED, **tags) -> list[files.Track]:
        """One medium of FLAC tracks, numbered, each carrying `release_id` if given."""
        out = []
        for number, length in enumerate(lengths, start=1):
            extra = dict(tags)
            if release_id:
                extra["musicbrainz_albumid"] = release_id
            out.append(vorbis(self.album, f"{number:02d}. Track {number}.flac", length,
                              tracknumber=str(number), album="The Downward Spiral",
                              albumartist="Nine Inch Nails", artist="Nine Inch Nails", **extra))
        return out


class ExistingReleaseId(IdentifyTestCase):
    def test_agreeing_counts_and_durations_are_certain_without_a_search(self) -> None:
        server = Server(releases=(release_json(TAGGED, [[200, 180, 240]]),))
        result = self.identify(unit(self.album, self.tagged([201, 178.5, 240])), server)
        self.assertEqual(result.status, "certain")
        self.assertEqual(server.searches(), [])
        self.assertEqual(server.fetched(), [TAGGED])

    def test_the_tagged_release_says_whether_its_credit_is_the_files_artist(self) -> None:
        # The page reads a release whose artist was never compared as one that differs.
        server = Server(releases=(release_json(TAGGED, [[200, 180, 240]]),))
        for artist, agrees in (("Nine Inch Nails", True), ("Nirvana", False)):
            with self.subTest(artist=artist):
                self.forget()
                tracks = self.tagged([200, 180, 240])
                for track in tracks:
                    track.tags["albumartist"] = [artist]
                    track.tags["artist"] = [artist]
                result = self.identify(unit(self.album, tracks), server)
                self.assertEqual(result.status, "certain")
                self.assertEqual([c.artist_agrees for c in result.candidates], [agrees])

    def test_a_duration_20_seconds_off_is_review_still_without_a_search(self) -> None:
        # The titles agree, so the limit is 15 s, and 20 s is past it.
        server = Server(releases=(release_json(TAGGED, [[200, 180, 240]]),))
        result = self.identify(unit(self.album, self.tagged([200, 200, 240])), server)
        self.assertEqual(result.status, "review")
        self.assertEqual(server.searches(), [])

    def test_exactly_3_seconds_off_is_still_within(self) -> None:
        server = Server(releases=(release_json(TAGGED, [[200, 180, 240]]),))
        result = self.identify(unit(self.album, self.tagged([203, 177, 240])), server)
        self.assertEqual(result.status, "certain")

    def test_the_release_id_is_read_under_each_formats_own_tag(self) -> None:
        # From real files, so the value is whatever `files.read` really
        # gives back for each format, then the length set by hand.
        for ext in ("mp3", "flac", "ogg", "m4a"):
            with self.subTest(ext=ext):
                album = self.root / ext
                album.mkdir()
                tracks = []
                for number in (1, 2):
                    path = builders.copy_fixture(album, ext, f"0{number}. Track {number}")
                    builders.write_tags(path, {RELEASE_ID_KEY[ext]: TAGGED})
                    tracks.append(dataclasses.replace(files.read(path), length=200.0))
                server = Server(releases=(release_json(TAGGED, [[200, 200]]),))
                result = self.identify(unit(album, tracks), server)
                self.assertEqual(result.status, "certain")
                self.assertEqual(server.searches(), [])

    def test_the_recording_length_stands_in_when_the_track_has_none(self) -> None:
        server = Server(releases=(release_json(TAGGED, [[200, 180]], recording_only=True),))
        self.assertEqual(self.identify(unit(self.album, self.tagged([200, 180])), server).status, "certain")

    def test_cd_folders_are_the_media_in_order(self) -> None:
        # Two discs of 2 and 1 match a release of 2 then 1, and not one of
        # 1 then 2, which has the same total.
        tracks = [
            vorbis(self.album, "CD2/01. Track 1.flac", 300, musicbrainz_albumid=TAGGED, tracknumber="1"),
            vorbis(self.album, "CD1/02. Track 2.flac", 180, musicbrainz_albumid=TAGGED, tracknumber="2"),
            vorbis(self.album, "CD1/01. Track 1.flac", 200, musicbrainz_albumid=TAGGED, tracknumber="1"),
        ]
        server = Server(releases=(release_json(TAGGED, [[200, 180], [300]]),))
        self.assertEqual(self.identify(unit(self.album, tracks), server).status, "certain")

    def test_disc_number_tags_are_the_media_when_there_are_no_cd_folders(self) -> None:
        tracks = [
            vorbis(self.album, "01. Track 1.flac", 200, musicbrainz_albumid=TAGGED, discnumber="1", tracknumber="1"),
            vorbis(self.album, "02. Track 2.flac", 180, musicbrainz_albumid=TAGGED, discnumber="1", tracknumber="2"),
            vorbis(self.album, "03. Track 1.flac", 300, musicbrainz_albumid=TAGGED, discnumber="2", tracknumber="1"),
        ]
        server = Server(releases=(release_json(TAGGED, [[200, 180], [300]]),))
        self.assertEqual(self.identify(unit(self.album, tracks), server).status, "certain")

    def test_tracks_pair_with_the_release_by_track_number_before_filename(self) -> None:
        # Filename order pairs each file with the other track, 100 s off and
        # under another title. Track-number order pairs them exactly.
        tracks = [
            vorbis(self.album, "01. Piggy.flac", 300, musicbrainz_albumid=TAGGED, tracknumber="2"),
            vorbis(self.album, "02. Mr. Self Destruct.flac", 200, musicbrainz_albumid=TAGGED, tracknumber="1"),
        ]
        release = release_json(TAGGED, [[200, 300]])
        for mb_track, title in zip(release["media"][0]["tracks"], ("Mr. Self Destruct", "Piggy")):
            mb_track["title"] = mb_track["recording"]["title"] = title
        server = Server(releases=(release,))
        self.assertEqual(self.identify(unit(self.album, tracks), server).status, "certain")

    def test_a_tagged_bootleg_that_fits_stays_certain_though_an_older_official_edition_exists(self) -> None:
        # The edition choice is for search and fingerprint candidates. The
        # server would answer a search with the older Official one.
        bootleg = release_json(TAGGED, [[200, 180, 240]], date="2004-11-23")
        bootleg["status"] = "Bootleg"
        official = release_json(OTHER, [[200, 180, 240]], date="1990-01-01")
        server = Server(releases=(bootleg, official), search=search_json(official))
        result = self.identify(unit(self.album, self.tagged([200, 180, 240])), server)
        self.assertEqual(result.status, "certain")
        self.assertEqual([c.release_id for c in result.candidates], [TAGGED])
        self.assertEqual(server.searches(), [])

    def test_counts_that_differ_from_the_tagged_release_mean_a_search(self) -> None:
        server = Server(releases=(release_json(TAGGED, [[200, 180, 240, 100]]),), search=search_json())
        result = self.identify(unit(self.album, self.tagged([200, 180, 240])), server)
        self.assertNotEqual(len(server.searches()), 0)
        self.assertNotIn(result.status, ("certain", "auto"))

    def test_the_same_total_split_differently_from_the_tagged_release_is_not_certain(self) -> None:
        # Discs of 2 and 1 against a release of 1 and 2: the totals agree,
        # the media do not, so the tag is no longer trusted and it searches.
        # The album and artist tags give the search something to ask by.
        named = {"musicbrainz_albumid": TAGGED, "album": "The Downward Spiral", "artist": "Nine Inch Nails"}
        tracks = [
            vorbis(self.album, "CD1/01. Track 1.flac", 200, tracknumber="1", **named),
            vorbis(self.album, "CD1/02. Track 2.flac", 180, tracknumber="2", **named),
            vorbis(self.album, "CD2/01. Track 1.flac", 300, tracknumber="1", **named),
        ]
        server = Server(releases=(release_json(TAGGED, [[200], [180, 300]]),), search=search_json())
        result = self.identify(unit(self.album, tracks), server)
        self.assertNotEqual(result.status, "certain")
        self.assertNotEqual(len(server.searches()), 0)

    def test_files_with_different_release_ids_mean_a_search(self) -> None:
        tracks = self.tagged([200, 180])
        tracks[1] = dataclasses.replace(tracks[1], tags={**tracks[1].tags, "musicbrainz_albumid": [OTHER]})
        server = Server(search=search_json(release_json(TAGGED, [[200, 180]])),
                        releases=(release_json(TAGGED, [[200, 180]]),))
        self.identify(unit(self.album, tracks), server)
        self.assertEqual(len(server.searches()), 1)

    def test_one_file_without_the_release_id_means_a_search(self) -> None:
        # "Every audio file carries the same ID": most of them is not enough.
        tracks = self.tagged([200, 180])
        tracks[1] = dataclasses.replace(
            tracks[1], tags={k: v for k, v in tracks[1].tags.items() if k != "musicbrainz_albumid"})
        server = Server(search=search_json(release_json(TAGGED, [[200, 180]])),
                        releases=(release_json(TAGGED, [[200, 180]]),))
        result = self.identify(unit(self.album, tracks), server)
        self.assertEqual(len(server.searches()), 1)
        self.assertNotEqual(result.status, "certain")


class Search(IdentifyTestCase):
    FILES = [200, 180, 240]

    def search_unit(self, lengths=None, **tags) -> Unit:
        return unit(self.album, self.tagged(lengths or self.FILES, release_id=None, **tags))

    def titled_unit(self, titled: list[tuple[str, float]]) -> Unit:
        """FLAC tracks from `(title tag, length)`, numbered in order, with no release ID."""
        return unit(self.album, [
            vorbis(self.album, f"{n:02d}. {title}.flac", length, tracknumber=str(n), title=title,
                   album="The Downward Spiral", albumartist="Nine Inch Nails", artist="Nine Inch Nails")
            for n, (title, length) in enumerate(titled, start=1)
        ])

    def test_the_search_asks_by_album_title_and_album_artist_with_no_track_count(self) -> None:
        # A search result's track count takes in data tracks, which the files
        # never have, so a count filter hides every enhanced CD.
        tracks = [
            vorbis(self.album, "CD1/01. Track 1.flac", 200, tracknumber="1",
                   album=["Halo 8", "Halo Eight"], albumartist="Nine Inch Nails", artist="Trent Reznor"),
            vorbis(self.album, "CD1/02. Track 2.flac", 180, tracknumber="2",
                   album="Halo 8", albumartist="Nine Inch Nails", artist="Trent Reznor"),
            vorbis(self.album, "CD2/01. Track 1.flac", 240, tracknumber="1",
                   album="Halo 8", albumartist="Nine Inch Nails", artist="Trent Reznor"),
        ]
        server = Server(search=search_json())
        self.identify(unit(self.album, tracks), server)
        params = server.searches()[0]
        lucene = params["query"]
        self.assertIn("release:(halo 8)", lucene)
        self.assertNotIn("halo eight", lucene.lower())
        self.assertIn("artist:(nine inch nails)", lucene)
        self.assertNotIn("trent reznor", lucene.lower())
        self.assertNotIn("tracks:", lucene)
        self.assertNotIn('"', lucene)

    def test_files_by_several_artists_search_for_various_artists_instead_of_an_artist(self) -> None:
        # With and without an album artist tag. Without one, the first file's
        # artist would otherwise be searched as if it were the whole album's.
        for label, album_artist in (("no album artist", {}), ("Various Artists", {"albumartist": "Various Artists"})):
            with self.subTest(label):
                self.forget()
                tracks = [
                    vorbis(self.album, f"0{n}. Track {n}.flac", 200, tracknumber=str(n),
                           album="Nothing Records Sampler", artist=artist, **album_artist)
                    for n, artist in enumerate(("Nine Inch Nails", "Marilyn Manson", "Nine Inch Nails"), start=1)
                ]
                server = Server(search=search_json())
                self.identify(unit(self.album, tracks), server)
                params = server.searches()[0]
                self.assertIn(f"arid:{VARIOUS_ARTISTS}", params["query"])
                self.assertNotIn("artist:", params["query"])
                self.assertIn("release:(nothing records sampler)", params["query"])

    def test_an_album_artist_named_on_the_files_is_searched_even_when_track_artists_differ(self) -> None:
        # A featured artist on one track does not make the album a
        # compilation. Various Artists is for rips with no album artist.
        tracks = [
            vorbis(self.album, f"0{n}. Track {n}.flac", 200, tracknumber=str(n),
                   album="Nevermind", albumartist="Nirvana", artist=artist)
            for n, artist in enumerate(("Nirvana", "Nirvana feat. Kurt", "Nirvana"), start=1)
        ]
        server = Server(search=search_json())
        self.identify(unit(self.album, tracks), server)
        params = server.searches()[0]
        self.assertNotIn("arid:", params["query"])
        # Loose on the term's shape, which the album-artist test above pins.
        self.assertRegex(params["query"].replace("\\", "").lower(), r'\bartist:[\s("]*nirvana\b')

    def test_without_an_album_artist_the_search_uses_the_artist(self) -> None:
        tracks = [vorbis(self.album, f"0{n}. Track.flac", 200, tracknumber=str(n),
                         album="Pretty Hate Machine", artist="Nine Inch Nails") for n in (1, 2)]
        server = Server(search=search_json())
        self.identify(unit(self.album, tracks), server)
        params = server.searches()[0]
        self.assertRegex(params["query"].replace("\\", "").lower(), r'\bartist:[\s("]*nine inch nails')

    def test_candidates_rank_by_counts_then_total_duration_difference_then_mbid(self) -> None:
        # Files are 200, 180 and 240 s. Each naive order gets this wrong:
        # search score, MBID alone, the signed sum of differences, and its
        # absolute value (which A's +1 and -1 cancel to 0).
        a2 = release_json(mbid("a2"), [[201.5, 180, 240]])  # |diff| 1.5
        c3 = release_json(mbid("c3"), [[201, 179, 240]])    # 2.0, signed 0
        e5 = release_json(mbid("e5"), [[200, 180, 238]])    # 2.0, ties with c3
        b4 = release_json(mbid("b4"), [[205, 180, 240]])    # 5.0
        f0 = release_json(mbid("0f"), [[200, 180]])         # counts differ
        server = Server(search=search_json(e5, f0, b4, c3, a2), releases=(a2, c3, e5, b4))
        result = self.identify(self.search_unit(), server)
        self.assertEqual(
            [c.release_id for c in result.candidates],
            [mbid("a2"), mbid("c3"), mbid("e5"), mbid("b4"), mbid("0f")],
        )
        self.assertEqual([c.matches_counts for c in result.candidates], [True] * 4 + [False])
        self.assertAlmostEqual(result.candidates[0].duration_diff, 1.5)
        self.assertEqual(result.candidates[0].release, a2)
        # A count mismatch is known from the search answer, so its release
        # is never fetched: that would cost a second against the rate limit.
        self.assertNotIn(mbid("0f"), server.fetched())

    def test_the_plans_candidates_keep_what_the_search_listed_for_a_release_never_fetched(self) -> None:
        a2 = release_json(mbid("a2"), [[201.5, 180, 240]])
        f0 = release_json(mbid("0f"), [[200, 180]], date="2001")
        search = search_json(f0, a2)
        search["releases"][0].update({"country": "JP", "artist-credit": a2["artist-credit"]})
        server = Server(search=search, releases=(a2,))
        result = self.identify(self.search_unit(), server)
        entries = [_candidate_dict(c, {}) for c in result.candidates]
        ranked = {k: entries[0][k] for k in ("release_id", "checked", "artist_agrees", "failing_tracks", "status")}
        self.assertEqual(ranked, {"release_id": mbid("a2"), "checked": True, "artist_agrees": True,
                                  "failing_tracks": 0, "status": "Official"})
        unchecked = {k: v for k, v in entries[1].items() if k != "thumbnail"}
        self.assertEqual(unchecked, {
            "release_id": mbid("0f"), "title": "The Downward Spiral", "artist": "Nine Inch Nails",
            "date": "2001", "country": "JP", "format": "CD", "track_counts": [2], "matches_counts": False,
            "duration_diff": None, "checked": False, "artist_agrees": False, "failing_tracks": None,
            "status": "Official",
        })

    def test_the_same_total_split_differently_does_not_match_counts(self) -> None:
        tracks = [
            vorbis(self.album, "CD1/01. Track 1.flac", 200, tracknumber="1", album="Fixed", albumartist="Nine Inch Nails"),
            vorbis(self.album, "CD1/02. Track 2.flac", 180, tracknumber="2", album="Fixed", albumartist="Nine Inch Nails"),
            vorbis(self.album, "CD2/01. Track 1.flac", 240, tracknumber="1", album="Fixed", albumartist="Nine Inch Nails"),
        ]
        split = release_json(mbid("a1"), [[200], [180, 240]])
        server = Server(search=search_json(split), releases=(split,))
        result = self.identify(unit(self.album, tracks), server)
        self.assertEqual([c.matches_counts for c in result.candidates], [False])
        self.assertNotIn(result.status, ("certain", "auto"))

    def test_a_lone_full_match_within_3_seconds_is_auto(self) -> None:
        exact = release_json(mbid("a1"), [[203, 177, 240]])  # 3.0 s both ways
        server = Server(search=search_json(exact), releases=(exact,))
        self.assertEqual(self.identify(self.search_unit(), server).status, "auto")

    def test_one_track_20_seconds_off_is_review(self) -> None:
        # The titles agree, so the limit is 15 s, and 20 s is past it.
        off = release_json(mbid("a1"), [[220, 180, 240]])
        server = Server(search=search_json(off), releases=(off,))
        self.assertEqual(self.identify(self.search_unit(), server).status, "review")

    def test_the_3_second_limit_is_per_track_not_for_the_total(self) -> None:
        # 2.5 + 2.5 + 2.5 is 7.5 s in all, and every track is within 3.
        close = release_json(mbid("a1"), [[202.5, 177.5, 242.5]])
        server = Server(search=search_json(close), releases=(close,))
        self.assertEqual(self.identify(self.search_unit(), server).status, "auto")

    def test_full_editions_from_different_years_are_auto_with_the_oldest_first(self) -> None:
        # The 2010 and 2004 reissues fit the files more closely than the
        # 1994 CD, so ranking alone puts the 1994 one third. The 1990 one is
        # older still and matches the counts, but one track is 20 s off, so it
        # is not full and never chosen. The rest keep their ranked order.
        latest = release_json(mbid("a1"), [[200, 180, 240]], date="2010-09-14")          # 0.0
        reissue = release_json(mbid("b2"), [[200.5, 180, 240]], date="2004-11-23")       # 0.5
        original = release_json(mbid("c3"), [[201, 180, 240]], date="1994-03-08")        # 1.0
        not_full = release_json(mbid("d4"), [[200, 180, 260]], date="1990-01-01")        # 20.0
        server = Server(search=search_json(reissue, not_full, latest, original),
                        releases=(latest, reissue, original, not_full))
        result = self.identify(self.search_unit(), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual([c.release_id for c in result.candidates],
                         [mbid("c3"), mbid("a1"), mbid("b2"), mbid("d4")])
        self.assertEqual(result.candidates[0].release, original)

    def test_a_partial_date_counts_as_the_last_day_it_could_be(self) -> None:
        # Two 1999 editions and a 2004 one, so the years differ and the oldest
        # is chosen. `1999` is 1999-12-31 and `1999-05` is 1999-05-31, so the
        # full date wins both times. The partial one ranks higher and sorts
        # first as a string, so neither rank nor string order gets this right.
        for partial in ("1999", "1999-05"):
            with self.subTest(partial=partial):
                self.forget()
                top = release_json(mbid("a1"), [[200, 180, 240]], date="2004-11-23")       # 0.0
                vague = release_json(mbid("b2"), [[200.5, 180, 240]], date=partial)        # 0.5
                exact = release_json(mbid("c3"), [[201, 180, 240]], date="1999-05-12")     # 1.0
                server = Server(search=search_json(exact, vague, top), releases=(top, vague, exact))
                result = self.identify(self.search_unit(), server)
                self.assertEqual(result.status, "auto")
                self.assertEqual([c.release_id for c in result.candidates],
                                 [mbid("c3"), mbid("a1"), mbid("b2")])

    def test_two_oldest_editions_on_the_same_date_choose_the_one_that_ranks_higher(self) -> None:
        # c3 fits the files better than b2, so it ranks first of the two. The
        # date ties, and the ranking decides, not the MBID, which would give b2.
        top = release_json(mbid("a1"), [[200, 180, 240]], date="2004-11-23")        # 0.0
        closer = release_json(mbid("c3"), [[200.5, 180, 240]], date="1999-05-12")   # 0.5
        lower = release_json(mbid("b2"), [[201, 180, 240]], date="1999-05-12")      # 1.0
        server = Server(search=search_json(top, lower, closer), releases=(top, closer, lower))
        result = self.identify(self.search_unit(), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual([c.release_id for c in result.candidates],
                         [mbid("c3"), mbid("a1"), mbid("b2")])

    def test_a_full_edition_with_no_date_is_never_chosen_over_a_dated_one(self) -> None:
        # The undated one ranks first. A missing date that sorts as empty,
        # or as year zero, would make it the oldest. MusicBrainz sends either
        # no date key or an empty one, so both are tried.
        for label, undated_date in (("no date key", None), ("empty date", "")):
            with self.subTest(label):
                self.forget()
                undated = release_json(mbid("a1"), [[200, 180, 240]])                        # 0.0
                if undated_date is None:
                    del undated["date"]
                else:
                    undated["date"] = undated_date
                dated = release_json(mbid("b2"), [[200.5, 180, 240]], date="2004-11-23")     # 0.5
                server = Server(search=search_json(undated, dated), releases=(undated, dated))
                result = self.identify(self.search_unit(), server)
                self.assertEqual(result.status, "auto")
                self.assertEqual([c.release_id for c in result.candidates], [mbid("b2"), mbid("a1")])

    def test_two_fitting_editions_of_the_same_year_choose_the_earlier_date(self) -> None:
        # The later of the two in 1994 ranks first. Oldest is by date, so a
        # rule that compares only the year keeps the ranked one.
        top = release_json(mbid("a1"), [[200, 180, 240]], date="1994-06-01")      # 0.0
        earlier = release_json(mbid("b2"), [[200.5, 180, 240]], date="1994-03-08")  # 0.5
        server = Server(search=search_json(top, earlier), releases=(top, earlier))
        result = self.identify(self.search_unit(), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual([c.release_id for c in result.candidates], [mbid("b2"), mbid("a1")])

    def test_an_edition_that_fits_ranks_above_one_closer_in_total_length_that_does_not(self) -> None:
        # a1 is 16 s off on one track, 16 in all, so that pair fails. b2 is
        # 10 s off on two tracks, 20 in all, and fits. Ranking by total length
        # first puts a1 on top and makes the album review. a1 is also the
        # older, so choosing the oldest of every candidate, fitting or not,
        # gets it wrong too.
        off = release_json(mbid("a1"), [[216, 180, 240]], date="1994-03-08")         # 16.0, fails
        fits = release_json(mbid("b2"), [[210, 170, 240]], date="2004-11-23")        # 20.0, fits
        server = Server(search=search_json(off, fits), releases=(off, fits))
        result = self.identify(self.search_unit(), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual([c.release_id for c in result.candidates], [mbid("b2"), mbid("a1")])

    def test_an_edition_whose_titles_agree_ranks_above_one_with_another_track_3_whatever_the_lengths(self) -> None:
        # Two editions with the same counts. a1 has another song as track 3,
        # every length exact. b2 has the files' track 3, every length 5 s off.
        # The MBID and the total length both put a1 first.
        on_files = [("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)]
        other = titled_json(mbid("a1"), [("Mr. Self Destruct", 200), ("Piggy", 180), ("March of the Pigs", 240)])
        same = titled_json(mbid("b2"), [("Mr. Self Destruct", 205), ("Piggy", 185), ("Heresy", 245)])
        server = Server(search=search_json(other, same), releases=(other, same))
        result = self.identify(self.titled_unit(on_files), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual([c.release_id for c in result.candidates], [mbid("b2"), mbid("a1")])

    def test_candidates_that_fail_rank_by_how_many_pairs_fail_then_total_length(self) -> None:
        # Nothing fits, so the album is review and the ranking is all a person
        # sees. c3 fails one pair, on its title. b2 and a1 fail two each: b2
        # on titles with exact lengths, a1 on lengths 16 s off. Every simpler
        # key gets the order wrong: total length ([b2, a1, c3]), MBID
        # ([a1, b2, c3]), only title failures counted ([a1, c3, b2]), only
        # length failures counted ([b2, c3, a1]).
        on_files = [("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)]
        one = titled_json(mbid("c3"), [("Mr. Self Destruct", 214), ("Piggy", 194), ("March of the Pigs", 254)])
        two_titles = titled_json(mbid("b2"), [("Mr. Self Destruct", 200), ("Closer", 180), ("March of the Pigs", 240)])
        two_lengths = titled_json(mbid("a1"), [("Mr. Self Destruct", 216), ("Piggy", 196), ("Heresy", 240)])
        short = titled_json(mbid("0f"), [("Mr. Self Destruct", 200), ("Piggy", 180)])
        server = Server(search=search_json(two_lengths, short, two_titles, one),
                        releases=(one, two_titles, two_lengths, short))
        result = self.identify(self.titled_unit(on_files), server)
        self.assertEqual(result.status, "review")
        self.assertEqual([c.release_id for c in result.candidates],
                         [mbid("c3"), mbid("b2"), mbid("a1"), mbid("0f")])

    def test_a_musicbrainz_track_with_no_length_adds_nothing_to_the_total_length(self) -> None:
        # Both editions fit, on the same date. b2's track 2 has no length and
        # a1 is 2 s off on it. Counted as 0 s, b2's track would be 180 s off
        # and a1 would rank first, as it does by MBID.
        on_files = [("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)]
        off = titled_json(mbid("a1"), [("Mr. Self Destruct", 200), ("Piggy", 182), ("Heresy", 240)])
        untimed = titled_json(mbid("b2"), [("Mr. Self Destruct", 200), ("Piggy", None), ("Heresy", 240)])
        server = Server(search=search_json(off, untimed), releases=(off, untimed))
        result = self.identify(self.titled_unit(on_files), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual([c.release_id for c in result.candidates], [mbid("b2"), mbid("a1")])

    def test_a_remembered_title_edit_counts_as_agreeing_when_candidates_are_ranked(self) -> None:
        # a1's track 2 is `Closer` on MusicBrainz, and the owner once retitled
        # it `Piggy`, as the file says. Both editions fit, on the same date,
        # and a1 is exact where b2 is 5 s off. Ranking that ignores the edit
        # counts one failing pair on a1 and puts b2 first.
        on_files = [("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)]
        edited = titled_json(mbid("a1"), [("Mr. Self Destruct", 200), ("Closer", 180), ("Heresy", 240)])
        plain = titled_json(mbid("b2"), [("Mr. Self Destruct", 205), ("Piggy", 185), ("Heresy", 245)])
        server = Server(search=search_json(plain, edited), releases=(edited, plain))
        owner = {"composers": {}, "edits": {mbid("a1"): {"1-2": {"title": ["Piggy"]}}}}
        result = self.identify(self.titled_unit(on_files), server, owner_input=owner)
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.candidates[0].release_id, mbid("a1"))

    def test_an_official_edition_is_chosen_over_older_bootleg_and_promotion_ones(self) -> None:
        # All three fit. The Bootleg and the Promotion are older and rank
        # higher, so oldest-first or rank-first each pick one of them.
        bootleg = titled_json(mbid("a1"), [("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)],
                              date="1993-05-01", status="Bootleg")
        promotion = titled_json(mbid("b2"), [("Mr. Self Destruct", 200.5), ("Piggy", 180), ("Heresy", 240)],
                                date="1993-02-01", status="Promotion")
        official = titled_json(mbid("c3"), [("Mr. Self Destruct", 201), ("Piggy", 180), ("Heresy", 240)],
                               date="1994-03-08")
        server = Server(search=search_json(bootleg, promotion, official), releases=(bootleg, promotion, official))
        result = self.identify(self.titled_unit([("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)]),
                               server)
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.candidates[0].release_id, mbid("c3"))
        self.assertEqual(result.candidates[0].release, official)

    def test_a_release_with_no_status_is_not_official(self) -> None:
        # The unstatused one is older and ranks higher, so only reading a
        # missing status as not Official picks the other.
        on_files = [("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)]
        unstatused = titled_json(mbid("a1"), on_files, date="1993-05-01")
        del unstatused["status"]
        official = titled_json(mbid("b2"), [("Mr. Self Destruct", 201), ("Piggy", 180), ("Heresy", 240)],
                               date="1994-03-08")
        server = Server(search=search_json(unstatused, official), releases=(unstatused, official))
        result = self.identify(self.titled_unit(on_files), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.candidates[0].release_id, mbid("b2"))

    def test_an_enhanced_cd_listed_with_its_data_tracks_matches_on_its_audio_tracks(self) -> None:
        # Meteora: search lists 15 tracks, the lookup has 13 plus 2 data
        # tracks, and the files are the 13. Comparing the listed count with
        # the files skips it without a lookup.
        lengths = [13, 188, 165, 185, 186, 197, 172, 168, 182, 162, 176, 196, 217]
        meteora = release_json(METEORA, [lengths], date="2003-03-24")
        medium = meteora["media"][0]
        medium["track-count"] = 15
        medium["data-tracks"] = [
            {"position": n, "number": str(n), "title": "[data track]", "length": None,
             "recording": {"id": mbid(f"1{n:02d}"), "title": "[data track]", "length": None}}
            for n in (14, 15)
        ]
        search = search_json(meteora)
        search["releases"][0]["track-count"] = 15
        search["releases"][0]["media"][0]["track-count"] = 15
        server = Server(search=search, releases=(meteora,))
        result = self.identify(self.search_unit(lengths), server)
        self.assertEqual(result.status, "auto")
        self.assertEqual(result.candidates[0].release_id, METEORA)

    def test_another_year_that_matches_counts_but_not_durations_does_not_stop_auto(self) -> None:
        # "Also matches" means a full match: counts and every duration.
        original = release_json(mbid("a1"), [[200, 180, 240]], date="1994-03-08")
        remaster = release_json(mbid("b2"), [[200, 180, 260]], date="2004-11-23")
        server = Server(search=search_json(remaster, original), releases=(original, remaster))
        self.assertEqual(self.identify(self.search_unit(), server).status, "auto")

    def test_no_count_match_is_neither_auto_nor_certain_and_fetches_nothing_more(self) -> None:
        short = release_json(mbid("a1"), [[200, 180]])
        server = Server(search=search_json(short))
        result = self.identify(self.search_unit(), server)
        self.assertNotIn(result.status, ("certain", "auto"))
        self.assertEqual(server.fetched(), [])

    def test_a_file_with_no_artist_tag_does_not_make_the_track_artists_differ(self) -> None:
        # A file nobody tagged has no artist to differ with. Counted as one,
        # a Nirvana album with one bare file is searched as a compilation.
        # The bare file is not the first, which the search reads its artist from.
        tracks = [vorbis(self.album, "01. Track 1.flac", 200, tracknumber="1", album="Nevermind", artist="Nirvana"),
                  vorbis(self.album, "02. Track 2.flac", 180, tracknumber="2", album="Nevermind"),
                  vorbis(self.album, "03. Track 3.flac", 240, tracknumber="3", album="Nevermind", artist="Nirvana")]
        server = Server(search=search_json())
        self.identify(unit(self.album, tracks), server)
        params = server.searches()[0]
        self.assertNotIn("arid:", params["query"])
        self.assertIn("artist:(nirvana)", params["query"])

    def test_files_with_no_album_tag_and_one_artist_are_searched_by_the_artist_alone(self) -> None:
        # An empty `release:()` is a query of its own to MusicBrainz, not a
        # term that matches anything.
        tracks = [vorbis(self.album, f"0{n}. Track {n}.flac", 200, tracknumber=str(n), artist="Nirvana")
                  for n in (1, 2)]
        server = Server(search=search_json())
        self.identify(unit(self.album, tracks), server)
        [params] = server.searches()
        self.assertNotIn("release:", params["query"])
        self.assertIn("artist:(nirvana)", params["query"])

    def test_files_with_no_album_tag_and_no_single_artist_are_not_searched_and_go_to_the_fingerprints(self) -> None:
        # With no title, Various Artists alone asks MusicBrainz for any 25
        # compilations, none of them this album; no artist at all asks for
        # anything. Either goes where a search with no results would send
        # it. No AcoustID key is the fingerprint path's own reason, so
        # seeing it shows that path ran.
        for label, artists in (("no artist tag", (None, None)),
                               ("track artists differ", ("Nine Inch Nails", "Marilyn Manson")),
                               ("track artists differ under Various Artists", ("Nine Inch Nails", "Marilyn Manson"))):
            with self.subTest(label):
                self.forget()
                extra = {"albumartist": "Various Artists"} if label.endswith("Various Artists") else {}
                tracks = [vorbis(self.album, f"0{n}. Track {n}.flac", 200, tracknumber=str(n),
                                 **({"artist": artist} if artist else {}), **extra)
                          for n, artist in enumerate(artists, start=1)]
                server = Server(search=search_json())
                result = self.identify(unit(self.album, tracks), server, env={}, which=lambda name: "/usr/bin/fpcalc")
                self.assertEqual(server.searches(), [])
                self.assertEqual((result.status, result.reason), ("unidentified", "ACOUSTID_API_KEY not set"))

    def test_a_release_with_no_track_lengths_has_a_length_difference_of_0_on_every_path(self) -> None:
        # Nothing to compare adds nothing to the total, as an untimed track
        # does on its own. The fingerprint path is in test_identify_acoustid,
        # where its ranking shows the same thing.
        on_files = [("Mr. Self Destruct", 200), ("Piggy", 180), ("Heresy", 240)]
        untimed = titled_json(TAGGED, [(title, None) for title, _ in on_files])
        titled = self.titled_unit(on_files)
        tagged = dataclasses.replace(titled, tracks=[
            dataclasses.replace(t, tags={**t.tags, "musicbrainz_albumid": [TAGGED]}) for t in titled.tracks])
        paths = {
            "search": lambda client: identify(titled, client),
            "tagged": lambda client: identify(tagged, client),
            "chosen": lambda client: chosen(titled, client, TAGGED),
        }
        for path, run in paths.items():
            with self.subTest(path):
                self.forget()
                server = Server(search=search_json(untimed), releases=(untimed,))
                result = run(self.client(server))
                self.assertEqual([(c.release_id, c.duration_diff) for c in result.candidates], [(TAGGED, 0.0)])

    def test_a_release_the_owner_chose_is_judged_on_its_artist_like_one_the_search_found(self) -> None:
        # Unjudged, the owner's pick read as "artist differs" whatever its credit.
        for label, artist, agrees in (("same artist", "Nine Inch Nails", True), ("another", "Filter", False)):
            with self.subTest(label):
                self.forget()
                server = Server(releases=(release_json(TAGGED, [[200, 180]]),))
                files = [vorbis(self.album, f"0{n}. Track {n}.flac", length, tracknumber=str(n),
                                album="The Downward Spiral", albumartist=artist)
                         for n, length in ((1, 200), (2, 180))]
                result = chosen(unit(self.album, files), self.client(server), TAGGED)
                self.assertEqual([c.artist_agrees for c in result.candidates], [agrees])

    def test_a_release_whose_media_do_not_pair_with_the_files_has_no_length_difference(self) -> None:
        # Disc folders of 2 and 1 against media of 1 and 2: the total of 3
        # gets it fetched, and no file has a track to be compared with. That
        # is not a difference of 0, which would read as a perfect fit.
        # `chosen` already says so; the search path is the one to hold to it.
        # Files with no disc folders would be paired across the media in
        # order (criterion 13), so the folders are what keeps them apart.
        split_files = unit(self.album, [
            vorbis(self.album, rel, length, tracknumber=number, album="Fixed", albumartist="Nine Inch Nails")
            for rel, length, number in (("CD1/01. Track 1.flac", 200, "1"), ("CD1/02. Track 2.flac", 180, "2"),
                                        ("CD2/01. Track 1.flac", 240, "1"))
        ])
        split = release_json(TAGGED, [[200], [180, 240]])
        paths = {
            "search": lambda client: identify(split_files, client, env={}),
            "chosen": lambda client: chosen(split_files, client, TAGGED),
        }
        for path, run in paths.items():
            with self.subTest(path):
                self.forget()
                server = Server(search=search_json(split), releases=(split,))
                result = run(self.client(server))
                self.assertEqual(server.fetched(), [TAGGED])
                self.assertEqual([(c.release_id, c.matches_counts, c.duration_diff) for c in result.candidates],
                                 [(TAGGED, False, None)])


# --- which files make which medium, in what order ------------------------


class Media(IdentifyTestCase):
    def folders(self, the_unit: Unit) -> list[list[str]]:
        """Each medium `group_media` gives, as the folder each of its files is in."""
        return [[Path(t.path).parent.name for t in medium] for medium in units.group_media(the_unit)]

    def in_folders(self, counts: dict[str, int]) -> Unit:
        """`counts[folder]` numbered tracks in each subfolder, with no disc number tag, in the order given."""
        return unit(self.album, [
            vorbis(self.album, f"{folder}/{n:02d}. Track {n}.flac", 200, tracknumber=str(n))
            for folder, count in counts.items() for n in range(1, count + 1)
        ])

    def test_files_with_no_track_number_pair_in_the_numeric_order_of_their_filenames(self) -> None:
        # In string order `10 - Charlie` comes before `2 - Bravo`, which pairs
        # Bravo and Charlie with each other's tracks. Every length is the
        # same, so only the titles can tell.
        tracks = [vorbis(self.album, name, 200, album="The Downward Spiral", artist="Nine Inch Nails",
                         musicbrainz_albumid=TAGGED)
                  for name in ("10 - Charlie.flac", "1 - Alpha.flac", "2 - Bravo.flac")]
        release = titled_json(TAGGED, [("Alpha", 200), ("Bravo", 200), ("Charlie", 200)])
        result = self.identify(unit(self.album, tracks), Server(releases=(release,)))
        self.assertEqual(result.status, "certain")

    def test_cd_disc_and_disk_folders_in_any_case_with_or_without_a_space_are_the_media_by_number(self) -> None:
        # The second set is out of alphabetical order, so sorting the folder
        # names gets it wrong where reading the number does not.
        cases = {
            "as the spec names them": {"disk 3": 3, "CD 1": 1, "Disc 2": 2},
            "numbers against the alphabet": {"CD 2": 2, "disk 3": 3, "Disc 1": 1},
        }
        for label, counts in cases.items():
            with self.subTest(label):
                media = self.folders(self.in_folders(counts))
                self.assertEqual([len(m) for m in media], [1, 2, 3])
                self.assertEqual([set(m) for m in media],
                                 [{name} for name, _ in sorted(counts.items(), key=lambda item: item[1])])

    def test_a_disc_folder_may_carry_a_title_after_its_number(self) -> None:
        media = self.folders(self.in_folders({"CD 2": 2, "CD1 - Live": 1}))
        self.assertEqual(media, [["CD1 - Live"], ["CD 2", "CD 2"]])

    def test_a_disc_word_and_number_ending_a_name_in_brackets_or_after_a_dash_is_the_medium_by_number(self) -> None:
        # Each set sorts against its numbers by name, so sorting the folder
        # names gets it wrong where reading the number does not. The last
        # mixes a leading disc folder with a trailing one.
        cases = {
            "each form": {"Album (CD 2)": 2, "Album - Disc 3": 3, "Album [CD1]": 1},
            "the other forms": {"Album - CD 2": 2, "Album [Disc 1]": 1},
            "a name either end": {"Album [CD2]": 2, "Disc 1": 1},
        }
        for label, counts in cases.items():
            with self.subTest(label):
                media = self.folders(self.in_folders(counts))
                self.assertEqual([set(m) for m in media],
                                 [{name} for name, _ in sorted(counts.items(), key=lambda item: item[1])])
                self.assertEqual([len(m) for m in media], sorted(counts.values()))

    def test_black_tie_white_noise_is_two_media_by_folder_disc_1_first_with_no_disc_tags(self) -> None:
        # Both folders begin with the year, so reading the first number in
        # the name puts every file on one medium, numbered 2004.
        album = "2004.Black Tie White Noise"
        media = self.folders(self.in_folders({f"{album} [Disc 2]": 11, f"{album} [Disc 1]": 12}))
        self.assertEqual(media, [[f"{album} [Disc 1]"] * 12, [f"{album} [Disc 2]"] * 11])

    def test_a_folder_named_anything_else_is_not_a_disc(self) -> None:
        # Beside a real disc folder, so every file would have a disc if the
        # other folder counted. Not counting, all the files are one medium.
        # `Bonus CD 2` ends in the words of a disc folder with no bracket or
        # dash before them, and `Disc Two` spells its number.
        for other in ("Bonus", "Scans", "Bonus CD 2", "Disc Two"):
            with self.subTest(other):
                media = self.folders(self.in_folders({"CD1": 2, other: 1}))
                self.assertEqual(len(media), 1)
                self.assertEqual(sorted(media[0]), sorted(["CD1", "CD1", other]))


# --- when identification cannot run -------------------------------------


class CannotIdentify(IdentifyTestCase):
    def test_a_unit_that_needs_a_person_stays_so_and_asks_nothing(self) -> None:
        server = Server()
        needs = unit(self.album, self.tagged([200]), status="needs a person",
                     reason="album tags disagree: 'Hotel', 'Raining Again'")
        result = self.identify(needs, server)
        self.assertEqual(result.status, "needs a person")
        self.assertIn("Hotel", result.reason)
        self.assertIn("Raining Again", result.reason)
        self.assertEqual(server.urls, [])

    def test_unreadable_files_leave_the_album_unidentified_and_ask_nothing(self) -> None:
        server = Server()
        broken = unit(self.album, self.tagged([200]),
                      unreadable=[("02. Track 2.flac", "not a recognised audio file")])
        result = self.identify(broken, server)
        self.assertEqual((result.status, result.reason), ("unidentified", "unreadable files"))
        self.assertEqual(server.urls, [])

    def test_musicbrainz_down_leaves_the_album_unidentified(self) -> None:
        # Both ways in: the lookup of a tagged release, and a search.
        for label, release_id in (("lookup", TAGGED), ("search", None)):
            with self.subTest(label):
                self.clock = FakeClock()
                server = Server(unavailable=True)
                result = self.identify(unit(self.album, self.tagged([200], release_id=release_id)), server)
                self.assertEqual((result.status, result.reason), ("unidentified", "musicbrainz unavailable"))
                self.assertEqual(len(server.urls), 5)


VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"

# What holds a Soundtrack-type album, and what settles it, is `tests.test_soundtracks`.

if __name__ == "__main__":
    unittest.main()
