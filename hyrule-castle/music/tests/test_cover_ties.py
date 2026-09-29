"""The album's own cover breaks a tie between editions that all fit.

On the search and fingerprint paths, where the folder has a cover and two or
more candidates fit, a candidate *shows the cover* when the average hashes of
its front's 250 px thumbnail and the local cover differ in 10 bits or fewer.
One that shows it is chosen over one that does not, before artist agreement,
Official status and age. With no local cover, or one fitting candidate,
nothing is fetched and the choice is the ordinary ranking's.

The pairs are shaped like the owner's Final Fantasy IV and VI: an Official
1994 book and an Official 2001 reissue with the same tracks, so both fit
exactly. The reissue loses on everything but the cover: it is newer, sorts
after the book by MBID and comes second in the search. Only the cover can
put it on top.

The pictures are drawn here with Pillow and never hashed here, so no case
depends on the engine's own hash. A picture white on its left half and one
white on its top half are 32 bits apart whatever the size. Where a case
needs an exact distance, the pictures are 8 by 8 already, black and white,
so the resize changes nothing and each white pixel is one set bit.

MusicBrainz is the fake server of `tests.test_identify`, answering artist
lookups as well. The Cover Art Archive is `Archive` below, behind the real
`CoverArt` client and its on-disk cache, recording every URL it was asked for.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from musiclib import acoustid
from musiclib.caa import CoverArt
from musiclib.cache import Cache
from musiclib.identify import identify
from musiclib.units import Unit
from tests import test_batch_identify as batch
from tests.test_identify import IdentifyTestCase, Server, mbid, search_json, titled_json, unit, vorbis

BOOK = mbid("a1")      # the 1994 edition
REISSUE = mbid("f9")   # the 2001 edition
OTHER = mbid("c3")     # a third edition, where a case needs one

SONGS = [("Prelude", 180.0), ("Main Theme of Final Fantasy IV", 150.0), ("Red Wings", 120.0)]
ANOTHER_TRACK_3 = [*SONGS[:2], ("Kingdom of Baron", 120.0)]

ARCHIVE = "coverartarchive.org"
ARTIST_PATH = "/ws/2/artist/"


# --- pictures -----------------------------------------------------------------


def _encode(image: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    image.save(out, fmt)
    return out.getvalue()


def half(side: str, size: int = 250, fmt: str = "JPEG") -> bytes:
    """A square picture, white on its `left` or `top` half and black on the other."""
    image = Image.new("RGB", (size, size), (0, 0, 0))
    box = (0, 0, size // 2, size) if side == "left" else (0, 0, size, size // 2)
    image.paste((255, 255, 255), box)
    return _encode(image, fmt)


#: What the reissue's thumbnail looks like, and the book's.
REISSUE_FRONT = half("left")
BOOK_FRONT = half("top")
#: The folder's cover, drawn like the reissue's thumbnail at another size:
#: 0 bits from the reissue, 32 from the book.
LOCAL_COVER = half("left", size=600)
#: One flat grey: no pixel is above the mean, so it is 32 bits from either half.
GREY = _encode(Image.new("RGB", (250, 250), (128, 128, 128)), "JPEG")

#: A checkerboard, as the 64 bits of an 8 by 8 picture, first row first.
PATTERN = frozenset(i for i in range(64) if (i // 8 + i % 8) % 2 == 0)


def grid(white: frozenset[int]) -> bytes:
    """An 8 by 8 PNG, white on the pixels in `white` and black on the rest."""
    image = Image.new("RGB", (8, 8), (0, 0, 0))
    for i in white:
        image.putpixel((i % 8, i // 8), (255, 255, 255))
    return _encode(image, "PNG")


def off_by(bits: int) -> bytes:
    """`PATTERN` with its first `bits` pixels turned over: exactly `bits` bits from `grid(PATTERN)`."""
    return grid(PATTERN ^ frozenset(range(bits)))


# --- the Cover Art Archive ----------------------------------------------------


def thumb_url(owner: str, image_id: int, key: str) -> str:
    return f"https://{ARCHIVE}/release/{owner}/{image_id}-{key}.jpg"


class Archive:
    """The Cover Art Archive as a transport: listings by release and release group, images by URL.

    A listing it was not given is a 404, which the client reads as no images.
    So is an image URL it was not given. `requests` is every URL asked for,
    in order and with repeats.
    """

    def __init__(self) -> None:
        self.listings: dict[str, list[dict]] = {}
        self.bodies: dict[str, bytes] = {}
        self.requests: list[str] = []

    def front(self, release_id: str, thumbnail: bytes, **options) -> "Archive":
        """Give `release_id` a front whose 250 px thumbnail is `thumbnail`, and nothing else that looks like it.

        Every other size of it, and the full image, are `GREY`, so an engine
        that compares the wrong one sees a picture that shows nothing.
        """
        return self.image(release_id, 1, {"250": thumbnail}, **options)

    def image(self, release_id: str, image_id: int, thumbnails: dict[str, bytes], *,
              types: tuple[str, ...] = ("Front",), front: bool = True, sizes=("250", "500", "1200", "small", "large"),
              group: bool = False) -> "Archive":
        kind = "release-group" if group else "release"
        full = f"https://{ARCHIVE}/{kind}/{release_id}/{image_id}.jpg"
        urls = {key: f"https://{ARCHIVE}/{kind}/{release_id}/{image_id}-{key}.jpg" for key in sizes}
        self.listings.setdefault(f"/{kind}/{release_id}", []).append({
            "id": image_id, "types": list(types), "front": front, "back": "Back" in types,
            "approved": True, "comment": "", "edit": 1, "image": full, "thumbnails": urls,
        })
        self.bodies[full] = GREY
        for key, url in urls.items():
            self.bodies[url] = thumbnails.get(key, GREY)
        return self

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.requests.append(url)
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if path in self.listings:
            return 200, json.dumps({"images": self.listings[path], "release": url}).encode()
        if url in self.bodies:
            return 200, self.bodies[url]
        return 404, b"Not Found"

    def downloads(self) -> list[str]:
        """Every image asked for, in order: anything that is not a listing."""
        return [u for u in self.requests if urlsplit(u).path.rstrip("/").count("/") > 2]

    def group_requests(self) -> list[str]:
        return [u for u in self.requests if "/release-group/" in u]


# --- MusicBrainz ----------------------------------------------------------------


def artist_json(artist_id: str, name: str, sort_name: str, english: str) -> dict:
    """An artist as `mb.artist` returns it, with its English name as a primary Artist name alias."""
    return {
        "id": artist_id, "name": name, "sort-name": sort_name, "genres": [],
        "aliases": [{"name": english, "sort-name": english, "type": "Artist name", "locale": "en",
                     "primary": True}],
    }


UEMATSU = artist_json(mbid("e1"), "植松伸夫", "Uematsu, Nobuo", "Nobuo Uematsu")
NOMURA = artist_json(mbid("e2"), "野村玲子", "Nomura, Reiko", "Reiko Nomura")
ARTISTS = {a["id"]: a for a in (UEMATSU, NOMURA)}


def credit(*artists: dict) -> list[dict]:
    """A credit to `artists` under their own names, joined with ` & `, as a release lookup gives it."""
    return [{"name": a["name"], "joinphrase": " & " if n < len(artists) - 1 else "",
             "artist": {"id": a["id"], "name": a["name"], "sort-name": a["sort-name"]}}
            for n, a in enumerate(artists)]


def edition(release_id: str, date: str, *, credited=(UEMATSU,), status: str = "Official", songs=SONGS) -> dict:
    release = titled_json(release_id, songs, date=date, status=status)
    release["artist-credit"] = credit(*credited)
    return release


def book(**changes) -> dict:
    return edition(BOOK, "1994-08-26", **changes)


def reissue(**changes) -> dict:
    return edition(REISSUE, "2001-10-31", **changes)


class WithArtists(Server):
    """The fake MusicBrainz server, answering artist lookups from `ARTISTS` as well."""

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        path = urlsplit(url).path
        if self.unavailable or not path.startswith(ARTIST_PATH):
            return super().__call__(url, headers)
        self.urls.append(url)
        found = ARTISTS.get(path[len(ARTIST_PATH):])
        if found is None:
            return 404, b'{"error": "Not Found"}'
        return 200, json.dumps(found).encode()


# --- the engine -----------------------------------------------------------------


class _Tie(IdentifyTestCase):
    def files(self, albumartist: str = "Nobuo Uematsu", songs=SONGS) -> Unit:
        """FLAC files titled and timed as `songs`, with no release ID, so identify searches."""
        return unit(self.album, [
            vorbis(self.album, f"{n:02d}. {title}.flac", seconds, tracknumber=str(n), title=title,
                   album="Final Fantasy IV", albumartist=albumartist, artist="Nobuo Uematsu")
            for n, (title, seconds) in enumerate(songs, start=1)
        ])

    def archive_client(self, archive: Archive) -> CoverArt:
        (self.root / "cache-dir").mkdir(exist_ok=True)
        return CoverArt(Cache(self.root / "cache-dir"), transport=archive)

    def searched(self, releases: tuple[dict, ...], archive: Archive, cover: bytes | None = LOCAL_COVER,
                 files: Unit | None = None):
        """Identify the files against a search that lists `releases` in the order given."""
        server = WithArtists(search=search_json(*releases), releases=releases)
        return identify(files or self.files(), self.client(server),
                        caa=self.archive_client(archive), local_cover=cover)

    def assertChosen(self, result, status: str, reason: str | None, order: list[str]) -> None:
        self.assertEqual((result.status, result.reason), (status, reason))
        self.assertEqual([c.release_id for c in result.candidates], order)


def fronts(book_front: bytes = BOOK_FRONT, reissue_front: bytes = REISSUE_FRONT) -> Archive:
    return Archive().front(BOOK, book_front).front(REISSUE, reissue_front)


class TheCoverChooses(_Tie):
    def test_final_fantasy_iv_with_a_cover_drawn_like_the_reissue_chooses_the_2001_reissue_and_is_auto(self) -> None:
        result = self.searched((book(), reissue()), fronts())
        self.assertChosen(result, "auto", None, [REISSUE, BOOK])

    def test_final_fantasy_iv_with_no_local_cover_chooses_the_1994_book_and_fetches_no_thumbnail(self) -> None:
        archive = fronts()
        result = self.searched((book(), reissue()), archive, cover=None)
        self.assertChosen(result, "auto", None, [BOOK, REISSUE])
        self.assertEqual(archive.downloads(), [])

    def test_final_fantasy_vi_whose_artist_agrees_only_with_the_book_is_review_with_the_reissue_on_top(self) -> None:
        # Reiko Nomura is on the book's credit and not the reissue's. Artist
        # agreement used to come first, which gave the book `auto`. The cover
        # now comes before it, so the reissue is chosen and its artist does
        # not agree.
        files = self.files(albumartist="Reiko Nomura")
        result = self.searched((book(credited=(UEMATSU, NOMURA)), reissue()), fronts(), files=files)
        self.assertChosen(result, "review", "artist does not agree", [REISSUE, BOOK])

    def test_a_bootleg_that_shows_the_cover_is_chosen_over_an_official_edition_that_does_not(self) -> None:
        result = self.searched((book(), reissue(status="Bootleg")), fronts())
        self.assertEqual(result.candidates[0].release_id, REISSUE)


class WhatShowsTheCover(_Tie):
    def test_a_front_10_bits_from_the_cover_shows_it_and_one_11_bits_away_does_not(self) -> None:
        # Were 10 not enough, neither would show and the book would win on
        # age; were 11 enough, both would show and the book would win again.
        result = self.searched((book(), reissue()), fronts(book_front=off_by(11), reissue_front=off_by(10)),
                               cover=grid(PATTERN))
        self.assertEqual(result.candidates[0].release_id, REISSUE)

    def test_where_both_show_the_cover_the_older_is_chosen_however_much_closer_the_newer_is(self) -> None:
        # Showing the cover is yes or no. The distance itself ranks nothing.
        result = self.searched((book(), reissue()), fronts(book_front=off_by(8), reissue_front=off_by(0)),
                               cover=grid(PATTERN))
        self.assertEqual(result.candidates[0].release_id, BOOK)

    def test_only_the_releases_front_is_compared_never_another_image_it_lists_first(self) -> None:
        # The reissue lists a back cover drawn like the local cover before
        # its front. An engine that takes the first image would choose it.
        archive = Archive().front(BOOK, BOOK_FRONT)
        archive.image(REISSUE, 1, {"250": LOCAL_COVER}, types=("Back",), front=False)
        archive.image(REISSUE, 2, {"250": GREY})
        result = self.searched((book(), reissue()), archive)
        self.assertEqual(result.candidates[0].release_id, BOOK)

    def test_the_250_thumbnail_is_compared_and_small_only_where_there_is_no_250(self) -> None:
        # In each listing one size looks like the cover and the other does
        # not, so comparing the wrong size gives the other edition.
        for label, thumbnails, sizes, chosen in (
            ("250 over small", {"250": GREY, "small": REISSUE_FRONT}, ("250", "small"), BOOK),
            ("small with no 250", {"small": REISSUE_FRONT, "large": GREY}, ("small", "large"), REISSUE),
        ):
            with self.subTest(label):
                self.forget()
                archive = Archive().front(BOOK, BOOK_FRONT)
                archive.image(REISSUE, 1, thumbnails, sizes=sizes)
                result = self.searched((book(), reissue()), archive)
                self.assertEqual(result.candidates[0].release_id, chosen)

    def test_a_release_group_front_does_not_show_the_cover_and_is_never_fetched_for_the_tie(self) -> None:
        # The reissue has no image of its own. Its release group has a front
        # drawn like the local cover, which would choose the reissue if it counted.
        archive = Archive().front(BOOK, BOOK_FRONT)
        archive.image(mbid("9"), 1, {"250": LOCAL_COVER}, group=True)
        result = self.searched((book(), reissue()), archive)
        self.assertChosen(result, "auto", None, [BOOK, REISSUE])
        self.assertEqual(archive.group_requests(), [])

    def test_a_thumbnail_that_is_not_an_image_does_not_show_the_cover(self) -> None:
        archive = fronts()
        archive.bodies[thumb_url(REISSUE, 1, "250")] = b"<html>502 Bad Gateway</html>"
        result = self.searched((book(), reissue()), archive)
        self.assertChosen(result, "auto", None, [BOOK, REISSUE])


class WhatIsFetched(_Tie):
    def test_each_fitting_candidate_has_its_thumbnail_fetched_once_and_one_that_does_not_fit_never(self) -> None:
        # The third edition has another song as track 3, so it matches the
        # counts and does not fit.
        archive = fronts().front(OTHER, LOCAL_COVER)
        result = self.searched((book(), edition(OTHER, "1990-01-01", songs=ANOTHER_TRACK_3), reissue()), archive)
        self.assertEqual(result.candidates[0].release_id, REISSUE)
        self.assertEqual(sorted(archive.downloads()),
                         sorted([thumb_url(BOOK, 1, "250"), thumb_url(REISSUE, 1, "250")]))

    def test_one_fitting_candidate_fetches_no_thumbnail(self) -> None:
        archive = fronts()
        result = self.searched((book(songs=ANOTHER_TRACK_3), reissue()), archive)
        self.assertChosen(result, "auto", None, [REISSUE, BOOK])
        self.assertEqual(archive.downloads(), [])

    def test_a_tagged_release_id_is_certain_and_fetches_no_thumbnail(self) -> None:
        # The tagged path is not re-chosen, cover or no cover.
        files = self.files()
        for track in files.tracks:
            track.tags["musicbrainz_albumid"] = [BOOK]
        archive = fronts()
        result = self.searched((book(), reissue()), archive, files=files)
        self.assertChosen(result, "certain", None, [BOOK])
        self.assertEqual(archive.downloads(), [])


class FingerprintPath(_Tie):
    def test_on_the_fingerprint_path_the_cover_chooses_the_reissue_too(self) -> None:
        # The search lists nothing, so the fingerprints decide. Every file
        # fingerprints to both editions.
        from tests.test_identify_acoustid import KEY, FakeClock, Lookups, best

        files = self.files()
        for track in files.tracks:
            Path(track.path).parent.mkdir(parents=True, exist_ok=True)
            Path(track.path).touch()
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp)
            fpcalc = bin_dir / "fpcalc"
            # Names each fingerprint after its file, `FP-01. Prelude.flac`,
            # which is how `Lookups` tells the tracks apart.
            fpcalc.write_text("#!/bin/sh\nfor last; do :; done\n"
                              "printf '{\"duration\": 200.4, \"fingerprint\": \"FP-%s\"}\\n' \"$(basename \"$last\")\"\n")
            fpcalc.chmod(0o755)
            clock = FakeClock()
            client = acoustid.AcoustID(Cache(bin_dir / "acoustid-cache"), KEY,
                                       transport=Lookups({n: [best(BOOK, REISSUE)] for n in (1, 2, 3)}),
                                       clock=clock, sleep=clock.sleep, fpcalc=str(fpcalc))
            server = WithArtists(search=search_json(), releases=(book(), reissue()))
            result = identify(files, self.client(server), acoustid=client, env={"ACOUSTID_API_KEY": "key"},
                              which=lambda name: str(fpcalc) if name == "fpcalc" else None,
                              caa=self.archive_client(fronts()), local_cover=LOCAL_COVER)
        self.assertChosen(result, "auto", None, [REISSUE, BOOK])


# --- a batch job ----------------------------------------------------------------


KEY_IV = "U/Nobuo Uematsu/Final Fantasy IV [rip]"
TITLES = ["Prelude", "Red Wings"]


class JobServices:
    """MusicBrainz and the Cover Art Archive behind one transport, for a job's run.

    The search lists the book, then the reissue. Both are credited to
    `Nobuo Uematsu` under that name, so no artist lookup is needed. `answered`
    is every URL asked for, in order and with repeats.
    """

    def __init__(self) -> None:
        self.editions = [batch.release(1, "Nobuo Uematsu", "Final Fantasy IV", TITLES),
                         batch.release(2, "Nobuo Uematsu", "Final Fantasy IV", TITLES)]
        (self.book, _), (self.reissue, _) = self.editions
        self.book["date"], self.reissue["date"] = "1994-08-26", "2001-10-31"
        self.services = batch.Services(self.editions)
        self.archive = Archive().front(self.book["id"], BOOK_FRONT).front(self.reissue["id"], REISSUE_FRONT)
        self.answered: list[str] = []

    def thumbnails(self) -> list[str]:
        return [thumb_url(r["id"], 1, "250") for r in (self.book, self.reissue)]

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.answered.append(url)
        parts = urlsplit(url)
        if parts.netloc == ARCHIVE:
            return self.archive(url, headers)
        if parts.path.rstrip("/") == "/ws/2/release":
            return 200, json.dumps(search_json(self.book, self.reissue)).encode()
        return self.services(url, headers)


class InABatchJob(batch._Job):
    def setUp(self) -> None:
        super().setUp()
        folder = batch.album(self.root, KEY_IV, TITLES)
        (folder / "cover.jpg").write_bytes(LOCAL_COVER)

    def test_batch_identify_reads_the_folders_cover_and_chooses_the_reissue(self) -> None:
        services = JobServices()
        code, _out, err = batch.run_identify(self.root, self.job, self.memory, services)
        self.assertEqual(code, 0, err)
        [entry] = self.plan_doc()["albums"]
        self.assertEqual((entry["status"], entry["candidates"][0]["release_id"]), ("auto", services.reissue["id"]))

    def test_a_second_identify_on_the_same_job_makes_no_thumbnail_request(self) -> None:
        # The job's own cache, on disk, as a second sitting finds it.
        first, second = JobServices(), JobServices()
        batch.run_identify(self.root, self.job, self.memory, first)
        self.assertEqual(sorted(u for u in first.answered if u in first.thumbnails()), sorted(first.thumbnails()),
                         "the first run did not fetch each fitting edition's thumbnail once")
        batch.run_identify(self.root, self.job, self.memory, second)
        self.assertEqual([u for u in second.answered if u in second.thumbnails()], [])


if __name__ == "__main__":
    unittest.main()
