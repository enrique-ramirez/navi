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
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from musiclib.identify import identify
from musiclib import files, mb
from musiclib.cache import Cache
from musiclib.units import Unit
from tests import builders

SEARCH_PATH = "/ws/2/release/"
RELEASE_GROUP_PATH = "/ws/2/release-group/"
RECORDING_PATH = "/ws/2/recording/"
RELEASE_ID_KEY = {
    "mp3": "TXXX:MusicBrainz Album Id",
    "flac": "MUSICBRAINZ_ALBUMID",
    "ogg": "MUSICBRAINZ_ALBUMID",
    "m4a": "----:com.apple.iTunes:MusicBrainz Album Id",
}

# Real-shaped MBIDs whose first characters make their sorted order obvious.
TAGGED = "3f1b0c0e-5a4d-4c1e-9d2a-7b6f0e1a2c3d"
OTHER = "7a2e9d41-0b3c-4f5e-8a6d-2c1b0e9f8d7a"


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
    """A search answer listing `releases`, in the order given, with their media counts."""
    return {
        "count": len(releases), "offset": 0,
        "releases": [
            {
                "id": r["id"], "score": 100 - i, "title": r["title"], "date": r["date"],
                "track-count": sum(len(m["tracks"]) for m in r["media"]),
                "media": [{"format": "CD", "track-count": len(m["tracks"])} for m in r["media"]],
            }
            for i, r in enumerate(releases)
        ],
    }


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
    not about release groups need not give one. `recordings` maps a
    recording MBID to the IDs of the releases it appears on. `unavailable`
    answers 503 to everything.
    """

    def __init__(self, releases: tuple[dict, ...] = (), search: dict | None = None,
                 unavailable: bool = False, release_groups: tuple[dict, ...] = (),
                 recordings: dict[str, list[str]] | None = None) -> None:
        self.releases = {r["id"]: r for r in releases}
        self.search = search
        self.unavailable = unavailable
        self.release_groups = {g["id"]: g for g in release_groups}
        self.recordings = dict(recordings or {})
        self.urls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.urls.append(url)
        if self.unavailable:
            return 503, b"<html>503 Service Temporarily Unavailable</html>"
        path = urlsplit(url).path
        if path.startswith(RELEASE_GROUP_PATH):
            group_id = path[len(RELEASE_GROUP_PATH):]
            return 200, json.dumps(self.release_groups.get(group_id) or release_group_json(group_id)).encode()
        if path.startswith(RECORDING_PATH):
            recording_id = path[len(RECORDING_PATH):]
            if recording_id not in self.recordings or "releases" not in parse_qs(urlsplit(url).query).get("inc", [""])[0]:
                return 404, b'{"error": "Not Found"}'
            releases = [{"id": r, "title": "The Downward Spiral", "status": "Official"}
                        for r in self.recordings[recording_id]]
            return 200, json.dumps({"id": recording_id, "title": "Track", "releases": releases}).encode()
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

    def test_a_duration_4_seconds_off_is_review_still_without_a_search(self) -> None:
        server = Server(releases=(release_json(TAGGED, [[200, 180, 240]]),))
        result = self.identify(unit(self.album, self.tagged([200, 184, 240])), server)
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
        # Filename order pairs each file with the other track's recording,
        # 100 s off. Track-number order pairs them exactly.
        tracks = [
            vorbis(self.album, "01. Piggy.flac", 300, musicbrainz_albumid=TAGGED, tracknumber="2"),
            vorbis(self.album, "02. Mr. Self Destruct.flac", 200, musicbrainz_albumid=TAGGED, tracknumber="1"),
        ]
        server = Server(releases=(release_json(TAGGED, [[200, 300]]),))
        self.assertEqual(self.identify(unit(self.album, tracks), server).status, "certain")

    def test_counts_that_differ_from_the_tagged_release_mean_a_search(self) -> None:
        server = Server(releases=(release_json(TAGGED, [[200, 180, 240, 100]]),), search=search_json())
        result = self.identify(unit(self.album, self.tagged([200, 180, 240])), server)
        self.assertNotEqual(len(server.searches()), 0)
        self.assertNotIn(result.status, ("certain", "auto"))

    def test_the_same_total_split_differently_from_the_tagged_release_is_not_certain(self) -> None:
        # Discs of 2 and 1 against a release of 1 and 2: the totals agree,
        # the media do not, so the tag is no longer trusted and it searches.
        tracks = [
            vorbis(self.album, "CD1/01. Track 1.flac", 200, musicbrainz_albumid=TAGGED, tracknumber="1"),
            vorbis(self.album, "CD1/02. Track 2.flac", 180, musicbrainz_albumid=TAGGED, tracknumber="2"),
            vorbis(self.album, "CD2/01. Track 1.flac", 300, musicbrainz_albumid=TAGGED, tracknumber="1"),
        ]
        server = Server(releases=(release_json(TAGGED, [[200], [180, 300]]),), search=search_json())
        result = self.identify(unit(self.album, tracks), server)
        self.assertNotEqual(result.status, "certain")
        self.assertEqual(len(server.searches()), 1)

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

    def test_the_search_asks_by_album_title_album_artist_and_total_track_count(self) -> None:
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
        [params] = server.searches()
        lucene = params["query"].replace("\\", "").lower()
        self.assertRegex(lucene, r'\brelease:[\s("]*halo 8\b')
        self.assertNotIn("halo eight", lucene)
        self.assertRegex(lucene, r'\bartist:[\s("]*nine inch nails')
        self.assertNotIn("trent reznor", lucene)
        self.assertRegex(lucene, r'\btracks:[\s("]*3\b')

    def test_without_an_album_artist_the_search_uses_the_artist(self) -> None:
        tracks = [vorbis(self.album, f"0{n}. Track.flac", 200, tracknumber=str(n),
                         album="Pretty Hate Machine", artist="Nine Inch Nails") for n in (1, 2)]
        server = Server(search=search_json())
        self.identify(unit(self.album, tracks), server)
        [params] = server.searches()
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

    def test_one_track_4_seconds_off_is_review(self) -> None:
        off = release_json(mbid("a1"), [[204, 180, 240]])
        server = Server(search=search_json(off), releases=(off,))
        self.assertEqual(self.identify(self.search_unit(), server).status, "review")

    def test_the_3_second_limit_is_per_track_not_for_the_total(self) -> None:
        # 2.5 + 2.5 + 2.5 is 7.5 s in all, and every track is within 3.
        close = release_json(mbid("a1"), [[202.5, 177.5, 242.5]])
        server = Server(search=search_json(close), releases=(close,))
        self.assertEqual(self.identify(self.search_unit(), server).status, "auto")

    def test_two_full_matches_from_different_years_are_review(self) -> None:
        # The 1994 CD and a 2004 reissue with the same tracks. Which one the
        # files are is the owner's call, since it sets the date and label.
        original = release_json(mbid("a1"), [[200, 180, 240]], date="1994-03-08")
        reissue = release_json(mbid("b2"), [[200.5, 180, 240]], date="2004-11-23")
        server = Server(search=search_json(reissue, original), releases=(original, reissue))
        result = self.identify(self.search_unit(), server)
        self.assertEqual(result.status, "review")
        self.assertEqual(result.candidates[0].release_id, mbid("a1"))

    def test_two_full_matches_from_the_same_year_are_auto(self) -> None:
        one = release_json(mbid("a1"), [[200, 180, 240]], date="1994-03-08")
        other = release_json(mbid("b2"), [[200.5, 180, 240]], date="1994-06-01")
        server = Server(search=search_json(other, one), releases=(one, other))
        self.assertEqual(self.identify(self.search_unit(), server).status, "auto")

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


GENRE_KEY = {"mp3": "TCON", "flac": "genre", "ogg": "genre", "m4a": "\xa9gen"}
# release_json credits Nine Inch Nails, so this is its composer.
COMPOSER = mbid("8")
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"


class SoundtrackSafetyNet(IdentifyTestCase):
    """A Soundtrack release group is held at `review` until something says what it is.

    Held because its custom genre could be `video game music` or
    `soundtrack`, and a wrong guess files a game score beside film scores.
    Every case here would be `certain` or `auto` without the safety net.
    """

    FILES = [200, 180, 240]

    def soundtrack(self, tags: tuple[tuple[str, int], ...] = ()) -> dict:
        return release_group_json(secondary_types=("Soundtrack",), tags=tags)

    def auto(self, group: dict, release: dict | None = None, **file_tags) -> tuple[Unit, Server]:
        """A search that finds one release matching the files exactly, in `group`."""
        release = release or release_json(mbid("a1"), [self.FILES])
        server = Server(search=search_json(release), releases=(release,), release_groups=(group,))
        return unit(self.album, self.tagged(self.FILES, release_id=None, **file_tags)), server

    def test_an_unsettled_soundtrack_that_would_be_certain_is_review(self) -> None:
        # Soundtrack second in the list, as MusicBrainz gives it for a live
        # score: reading only the first secondary type misses it.
        group = release_group_json(secondary_types=("Live", "Soundtrack"))
        server = Server(releases=(release_json(TAGGED, [self.FILES]),), release_groups=(group,))
        result = self.identify(unit(self.album, self.tagged(self.FILES)), server)
        self.assertEqual((result.status, result.reason), ("review", "unsettled soundtrack"))

    def test_an_unsettled_soundtrack_that_would_be_auto_is_review(self) -> None:
        the_unit, server = self.auto(self.soundtrack())
        result = self.identify(the_unit, server)
        self.assertEqual((result.status, result.reason), ("review", "unsettled soundtrack"))

    def test_a_game_tag_on_the_release_group_settles_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack(tags=(("orchestral", 4), ("VGM", 2))))
        self.assertEqual(self.identify(the_unit, server).status, "auto")

    def test_files_carrying_soundtrack_settle_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack(), genre=["Orchestral", "Soundtrack"])
        self.assertEqual(self.identify(the_unit, server).status, "auto")

    def test_soundtrack_on_any_one_file_settles_it_even_when_the_first_has_no_genre(self) -> None:
        # The genre check reads the files, all of them, and the planned
        # genre does too. A check that looks only at the first track holds an album
        # at review whose genre plan then writes `soundtrack` without asking.
        # Second and last are both tried, so neither "the first two" nor
        # "the last one" passes.
        for carrier in (1, 2):
            with self.subTest(track=carrier + 1):
                the_unit, server = self.auto(self.soundtrack())
                the_unit.tracks[carrier] = dataclasses.replace(
                    the_unit.tracks[carrier], tags={**the_unit.tracks[carrier].tags, "genre": ["Soundtrack"]})
                self.assertNotIn("genre", the_unit.tracks[0].tags)
                self.assertEqual(self.identify(the_unit, server).status, "auto")

    def test_files_carrying_video_game_music_settle_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack(), genre=["Video Game Music", "Orchestral"])
        self.assertEqual(self.identify(the_unit, server).status, "auto")

    def test_an_incoming_game_genre_settles_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack())
        self.assertEqual(self.identify(the_unit, server, incoming="Video Game").status, "auto")

    def test_a_composer_remembered_as_video_game_music_settles_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack())
        owner = {"composers": {COMPOSER: "video game music"}}
        self.assertEqual(self.identify(the_unit, server, owner_input=owner).status, "auto")

    def test_a_composer_remembered_as_not_game_music_settles_it(self) -> None:
        the_unit, server = self.auto(self.soundtrack())
        owner = {"composers": {COMPOSER: "not game music"}}
        self.assertEqual(self.identify(the_unit, server, owner_input=owner).status, "auto")

    def test_the_genre_is_read_under_each_formats_own_tag_and_a_settled_one_stays_certain(self) -> None:
        # From real files, as the release ID test above does, so the genre
        # key is whatever `files.read` gives back: TCON, genre and ©gen.
        for ext in ("mp3", "flac", "ogg", "m4a"):
            with self.subTest(ext=ext):
                album = self.root / ext
                album.mkdir()
                tracks = []
                for number in (1, 2):
                    path = builders.copy_fixture(album, ext, f"0{number}. Track {number}")
                    builders.write_tags(path, {RELEASE_ID_KEY[ext]: TAGGED, GENRE_KEY[ext]: "Soundtrack"})
                    tracks.append(dataclasses.replace(files.read(path), length=200.0))
                server = Server(releases=(release_json(TAGGED, [[200, 200]]),), release_groups=(self.soundtrack(),))
                self.assertEqual(self.identify(unit(album, tracks), server).status, "certain")

    def test_a_choice_remembered_under_one_artist_of_a_shared_credit_does_not_settle_it(self) -> None:
        # Two credited artists have no composer, so owner input is never
        # read for them. Either value remembered under either
        # artist would settle it if it were.
        first, second = mbid("81"), mbid("82")
        shared = release_json(mbid("a1"), [self.FILES])
        shared["artist-credit"] = [
            {"name": "Trent Reznor", "joinphrase": " & ", "artist": {"id": first, "name": "Trent Reznor"}},
            {"name": "Atticus Ross", "joinphrase": "", "artist": {"id": second, "name": "Atticus Ross"}},
        ]
        for artist, remembered in ((first, "not game music"), (second, "video game music")):
            with self.subTest(artist=artist, remembered=remembered):
                the_unit, server = self.auto(self.soundtrack(), release=shared)
                result = self.identify(the_unit, server, owner_input={"composers": {artist: remembered}})
                self.assertEqual((result.status, result.reason), ("review", "unsettled soundtrack"))

    def test_a_choice_remembered_under_various_artists_does_not_settle_it(self) -> None:
        # One credited artist, but Various Artists is nobody's composer.
        various = release_json(mbid("a1"), [self.FILES])
        various["artist-credit"] = [
            {"name": "Various Artists", "joinphrase": "", "artist": {"id": VARIOUS_ARTISTS, "name": "Various Artists"}},
        ]
        the_unit, server = self.auto(self.soundtrack(), release=various)
        result = self.identify(the_unit, server, owner_input={"composers": {VARIOUS_ARTISTS: "not game music"}})
        self.assertEqual((result.status, result.reason), ("review", "unsettled soundtrack"))


if __name__ == "__main__":
    unittest.main()
