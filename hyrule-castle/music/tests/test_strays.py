"""Stray files in an album folder.

`Guessing` holds the pure half: the name agitha guesses for each stray and
the names the owner may give one. Nothing here reads a file. Each worked
example is a table of album-relative path to expected name, and each table
is passed to `strays.guess` in reverse natural order, so an implementation
that numbers in the order it was handed fails.

The classes after it hold settling: what `plan.plan_album` does with each
stray of a real rip folder, planned against a fake MusicBrainz and Cover Art
Archive. Every image is a flat colour of its own, so no two are byte-equal
unless a case means them to be.
"""

from __future__ import annotations

import io
import itertools
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, PngImagePlugin

from musiclib import caa, mb, strays
from musiclib import plan as plan_module
from musiclib.batch import memory
from musiclib.cache import Cache
from musiclib.units import Unit, pair, position_key, units
from tests import builders

#: Each type word and the type it gives.
TYPE_WORDS = {
    "front": "front", "cover": "front", "folder": "front", "fr": "front", "box": "front",
    "back": "back", "rear": "back",
    "cd": "medium", "disc": "medium", "disk": "medium", "dvd": "medium", "onbody": "medium",
    "label": "medium", "vinyl": "medium",
    "tray": "tray", "inlay": "tray",
    "booklet": "booklet", "book": "booklet", "page": "booklet", "inside": "booklet",
    "insert": "booklet", "sleeve": "booklet",
    "obi": "obi", "spine": "spine", "sticker": "sticker", "poster": "poster", "liner": "liner",
}

def _alone(type_: str) -> str:
    """The name of the only image of `type_`: plain, except `booklet`, which is always `-NN`."""
    return "booklet-01.jpg" if type_ == "booklet" else f"{type_}.jpg"


V = {
    "COVERS/maroon_5_v_[deluxe_edition]_2014-front.jpg": "front.jpg",
    "COVERS/maroon_5_v_[deluxe_edition]_2014-back.jpg": "back.jpg",
    "COVERS/maroon_5_v_[deluxe_edition]_2014-cd.jpg": "medium.jpg",
    # Its last type-like word is the plural `COVERS`, and it sits at the root.
    "Maroon 5 - V (Deluxe Version) [2014]MP3@320kbps+COVERS[TeryongNoypi].png": None,
}

HEATHEN = {
    "Scans/booklet.jpg": "booklet-01.jpg",
    "Scans/booklet1.jpg": "booklet-02.jpg",
    "Scans/booklet2.jpg": "booklet-03.jpg",
    "Scans/booklet3.jpg": "booklet-04.jpg",
    "Scans/booklet4.jpg": "booklet-05.jpg",
    "Scans/booklet5.jpg": "booklet-06.jpg",
    "Scans/cd1.jpg": "medium-1.jpg",
    "Scans/cd2.jpg": "medium-2.jpg",
    "Scans/box.jpg": "front.jpg",
    "Scans/box-back.jpg": "back.jpg",
}

BLACK_TIE_2004 = {
    "Scans/booklet1-1.jpg": "booklet-01.jpg",
    "Scans/booklet1-2.jpg": "booklet-02.jpg",
    "Scans/booklet1-3.jpg": "booklet-03.jpg",
    "Scans/booklet2-1.jpg": "booklet-04.jpg",
    "Scans/booklet2-2.jpg": "booklet-05.jpg",
    "Scans/booklet2-3.jpg": "booklet-06.jpg",
    "Scans/back1.jpg": "back-1.jpg",
    "Scans/back2.jpg": "back-2.jpg",
    "Scans/box-back.jpg": "back-3.jpg",
    "Scans/cd1.jpg": "medium-1.jpg",
    "Scans/cd2.jpg": "medium-2.jpg",
    "Scans/dvd.jpg": "medium-3.jpg",
}

ALADDIN_SANE = {
    **{f"Artwork/booklet {n}.jpg": f"booklet-{n:02d}.jpg" for n in range(1, 7)},
    "Artwork/onbody.jpg": "medium.jpg",
    "Artwork/tray.jpg": "tray.jpg",
}

SPACE_ODDITY = {
    "Covers/Cover 1.jpg": None,
    "Covers/Cover 2.jpg": None,
    "Covers/Cover 3.jpg": None,
    "Covers/Cover.jpg": "front.jpg",
}

#: Number-only files in a folder that is not a booklet folder.
NUMBERS_IN_COVERS = {
    "Black Tie White Noise 1993": [f"covers/Bowie0000{n}.jpg" for n in range(1, 7)],
    "Tin Machine II": [f"covers/{n:02d}.JPG" for n in range(1, 9)],
    "Earthling": [f"covers/{n}.jpg" for n in range(1, 6)],
}

BOOKLET_FOLDERS = ("Scans", "Scan", "Booklet", "Book", "сканы")

ARCHIVE_TYPES = ("back", "medium", "booklet", "tray", "obi", "spine", "sticker", "poster", "liner",
                 "track", "matrix-runout", "top", "bottom", "other")


def _natural(path: str) -> list:
    """A test-side sort key, only to hand `guess` its paths in reverse."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", path)]


class Guessing(unittest.TestCase):
    def assertGuesses(self, expected: dict[str, str | None], discs: dict[str, int] | None = None) -> None:
        # Reversed, so numbering by input order instead of by path fails.
        paths = sorted(expected, key=_natural, reverse=True)
        self.assertEqual(strays.guess(paths, discs), expected)

    def test_each_type_word_guesses_its_type_whatever_its_case(self) -> None:
        for word, type_ in TYPE_WORDS.items():
            with self.subTest(word=word):
                self.assertGuesses({f"Artwork/{word}.jpg": _alone(type_)})
                self.assertGuesses({f"Artwork/the {word.upper()}.jpg": _alone(type_)})

    def test_the_rightmost_type_word_in_the_name_wins(self) -> None:
        self.assertGuesses({"Artwork/back cover.jpg": "front.jpg"})
        self.assertGuesses({"Artwork/cover back.jpg": "back.jpg"})
        self.assertGuesses({"Artwork/tray_inlay_obi_x.jpg": "obi.jpg"})

    def test_words_split_on_punctuation_and_between_letters_and_digits(self) -> None:
        self.assertGuesses({"Artwork/p1inlay.jpg": "tray.jpg"})
        self.assertGuesses({"Artwork/x.spine.jpg": "spine.jpg"})
        self.assertGuesses({"Artwork/[poster]scan.jpg": "poster.jpg"})

    def test_the_folder_is_read_when_the_name_has_no_type_word(self) -> None:
        self.assertGuesses({"Tray/IMG_2231.jpg": "tray.jpg"})
        self.assertGuesses({"Obi Strip/photo.jpg": "obi.jpg"})

    def test_a_type_word_in_the_name_beats_the_folder(self) -> None:
        self.assertGuesses({"Back/cd.jpg": "medium.jpg"})

    def test_plural_and_suffixed_forms_are_not_type_words(self) -> None:
        for path in ("Artwork/covers.jpg", "Artwork/scans.jpg", "Artwork/booklets.jpg", "COVERS/IMG_0001.jpg"):
            with self.subTest(path=path):
                self.assertGuesses({path: None})

    def test_v_names_front_back_and_cd_and_leaves_its_png(self) -> None:
        self.assertGuesses(V)

    def test_back_in_black_cover_is_the_front(self) -> None:
        self.assertGuesses({"Back in Black - cover.jpg": "front.jpg"})

    def test_heathen_scans(self) -> None:
        # `booklet.jpg` is page one: its stem sorts before `booklet1`.
        self.assertGuesses(HEATHEN)

    def test_black_tie_white_noise_2004_scans(self) -> None:
        self.assertGuesses(BLACK_TIE_2004)

    def test_aladdin_sane_artwork(self) -> None:
        self.assertGuesses(ALADDIN_SANE)

    def test_numbering_follows_the_natural_order_of_paths(self) -> None:
        # Sorted as text, `booklet 10` would come before `booklet 2`.
        self.assertGuesses({f"Artwork/booklet {n}.jpg": f"booklet-{n:02d}.jpg" for n in range(1, 13)})
        self.assertGuesses({"Artwork/back 2.jpg": "back-1.jpg", "Artwork/back 10.jpg": "back-2.jpg"})

    def test_numbering_runs_across_every_folder_in_the_list(self) -> None:
        self.assertGuesses({"Artwork/back.jpg": "back-1.jpg", "Scans/back.jpg": "back-2.jpg"})

    def test_an_image_in_a_disc_folder_takes_the_disc_number(self) -> None:
        self.assertGuesses({"CD 2/cd.jpg": "medium-2.jpg"}, discs={"CD 2": 2})
        self.assertGuesses({"CD 1/cd.jpg": "medium-1.jpg", "CD 2/cd.jpg": "medium-2.jpg"},
                           discs={"CD 1": 1, "CD 2": 2})
        # The number comes from `discs`, not from digits in the folder's name.
        self.assertGuesses({"Bonus/cd.jpg": "medium-3.jpg"}, discs={"CD 1": 1, "CD 2": 2, "Bonus": 3})

    def test_a_number_only_name_in_a_booklet_folder_is_a_booklet_page(self) -> None:
        for folder in BOOKLET_FOLDERS:
            with self.subTest(folder=folder):
                self.assertGuesses({f"{folder}/01.jpg": "booklet-01.jpg", f"{folder}/02.jpg": "booklet-02.jpg"})

    def test_a_number_only_name_in_any_other_folder_has_no_guess(self) -> None:
        for album, paths in NUMBERS_IN_COVERS.items():
            with self.subTest(album=album):
                self.assertGuesses(dict.fromkeys(paths))

    def test_a_cover_word_with_its_own_number_has_no_guess(self) -> None:
        self.assertGuesses(SPACE_ODDITY)

    def test_hours_image_has_no_guess(self) -> None:
        self.assertGuesses({"david_bowie_hours_a[1].jpg": None})

    def test_the_library_types_are_front_and_every_archive_type(self) -> None:
        self.assertCountEqual(strays.LIBRARY_TYPES, ("front", *ARCHIVE_TYPES))

    def test_a_guessed_image_keeps_its_extension_lowercased_with_jpeg_as_jpg(self) -> None:
        cases = {
            "Artwork/back.JPG": "back.jpg",
            "Artwork/back.jpeg": "back.jpg",
            "Artwork/back.JPEG": "back.jpg",
            "Artwork/back.PNG": "back.png",
            "Artwork/back.webp": "back.webp",
        }
        for path, name in cases.items():
            with self.subTest(path=path):
                self.assertGuesses({path: name})

    def test_a_pdf_whose_words_name_a_booklet_is_booklet_pdf(self) -> None:
        for path in ("Artwork/booklet.pdf", "Artwork/Heathen Book.pdf", "Artwork/scan_hq.pdf"):
            with self.subTest(path=path):
                self.assertGuesses({path: "booklet.pdf"})

    def test_a_pdf_in_a_booklet_folder_is_booklet_pdf(self) -> None:
        for folder in BOOKLET_FOLDERS:
            with self.subTest(folder=folder):
                self.assertGuesses({f"{folder}/Heathen.pdf": "booklet.pdf"})

    def test_several_booklet_pdfs_are_numbered_without_padding(self) -> None:
        self.assertGuesses({"Scans/part 2.pdf": "booklet-1.pdf", "Scans/part 10.pdf": "booklet-2.pdf"})

    def test_a_booklet_pdf_is_numbered_apart_from_booklet_images(self) -> None:
        self.assertGuesses({"Scans/booklet1.jpg": "booklet-01.jpg", "Scans/booklet.pdf": "booklet.pdf"})

    def test_any_other_pdf_keeps_its_own_name_even_with_an_image_type_word(self) -> None:
        self.assertGuesses({"Artwork/Liner Notes.pdf": "Liner Notes.pdf"})
        self.assertGuesses({"Artwork/back.pdf": "back.pdf"})

    def test_text_and_logs_keep_their_own_name(self) -> None:
        self.assertGuesses({
            "Scans/booklet.txt": "booklet.txt",
            "Logs/rip.log": "rip.log",
            "Info.TXT": "Info.TXT",
        })

    def test_the_kind_of_a_stray_follows_its_extension(self) -> None:
        cases = {
            **{f"Scans/x{ext}": "image" for ext in
               (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".JPG", ".PNG")},
            "Scans/x.pdf": "pdf", "Scans/x.PDF": "pdf",
            "Scans/x.txt": "text", "Scans/x.log": "text", "Scans/x.LOG": "text",
        }
        for path, kind in cases.items():
            with self.subTest(path=path):
                self.assertEqual(strays.kind(path), kind)

    def test_every_library_name_is_accepted_for_an_image(self) -> None:
        for type_ in strays.LIBRARY_TYPES:
            with self.subTest(type=type_):
                self.assertIsNone(strays.name_offence("Artwork/x.jpg", _alone(type_)))

    def test_acceptable_names(self) -> None:
        cases = [
            ("Scans/back2.jpg", "back-2.jpg"),
            ("Scans/booklet3.jpg", "booklet-03.jpg"),
            ("Scans/x.jpg", "matrix-runout-2.jpg"),
            ("Artwork/back.JPG", "back.jpg"),
            ("Artwork/back.jpeg", "back.jpg"),
            ("Artwork/back.PNG", "back.png"),
            ("Scans/booklet.pdf", "Aladdin Sane - Liner Notes (1973).pdf"),
            ("rip.log", "EAC.log"),
            ("Extras/notes.txt", "Read me.txt"),
        ]
        for path, name in cases:
            with self.subTest(path=path, name=name):
                self.assertIsNone(strays.name_offence(path, name))

    def test_refused_names_get_one_sentence_naming_the_path(self) -> None:
        cases = [
            # An image name outside the library's.
            ("Scans/booklet1.jpg", "scan-01.jpg"),
            ("Scans/booklet1.jpg", "Heathen booklet.jpg"),
            # `booklet` is always numbered.
            ("Scans/booklet1.jpg", "booklet.jpg"),
            # A changed extension, or `.jpeg` and `.JPG` left as they are.
            ("Artwork/back.png", "back.jpg"),
            ("Artwork/back.jpeg", "back.jpeg"),
            ("Artwork/back.JPG", "back.JPG"),
            ("Scans/notes.pdf", "notes.txt"),
            ("Scans/notes.pdf", "notes"),
            ("rip.log", "rip.txt"),
            # `cover.<ext>` for any kind: it is the front's own name.
            ("Ziggy Stardust.jpg", "cover.jpg"),
            ("Scans/booklet.pdf", "cover.pdf"),
            ("Extras/notes.txt", "cover.txt"),
            # A `/` would put it in a folder.
            ("Scans/back.jpg", "Scans/back.jpg"),
            ("Scans/notes.pdf", "Scans/notes.pdf"),
            ("Extras/notes.txt", "a/notes.txt"),
            # A name `names.sanitize` would change.
            ("Scans/notes.pdf", "Notes: 1973.pdf"),
            ("Scans/notes.pdf", "Why?.pdf"),
            ("Scans/notes.pdf", 'The "Real" Notes.pdf'),
            ("rip.log", "rip\\EAC.log"),
        ]
        for path, name in cases:
            with self.subTest(path=path, name=name):
                offence = strays.name_offence(path, name)
                self.assertIsInstance(offence, str)
                self.assertIn(path, offence)
                self.assertNotIn("\n", offence)


_SHADES = itertools.count(1)


def _picture(width: int, height: int, fmt: str = "JPEG") -> bytes:
    """A flat image of this size whose bytes no other call gives.

    The serial goes in a comment (JPEG) or a text chunk (PNG): two flat
    colours a shade apart can quantise to the same JPEG bytes, which would
    make a meant tie a copy.
    """
    n = next(_SHADES)
    out = io.BytesIO()
    image = Image.new("RGB", (width, height), (n * 53 % 256, n * 97 % 256, 90))
    if fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("serial", str(n))
        image.save(out, fmt, pnginfo=info)
    else:
        image.save(out, fmt, comment=f"serial {n}".encode())
    return out.getvalue()


#: The archive's front: square and 1600 px, so it passes the cover test.
FRONT = _picture(1600, 1600)
_ART = f"https://coverartarchive.org/release/{builders.RELEASE_ID}"
_CURE = builders.mb_credit(builders.CURE_ID, "The Cure", "Cure, The")
_TITLES = ["Plainsong", "Pictures of You"]
#: Where `_rip` puts the album, relative to the library root: `plan.kept`'s and `plan.moved`'s prefix.
REL = "C/The Cure/Disintegration [rip]"


def _release() -> dict:
    return builders.mb_release(title="Disintegration", **{"artist-credit": _CURE},
                               media=[builders.mb_medium(1, _TITLES, credit=_CURE)])


def _release_group() -> dict:
    return {"id": builders.RELEASE_GROUP_ID, "title": "Disintegration", "primary-type": "Album",
            "secondary-types": [], "first-release-date": "1989-05-02", "tags": [],
            "genres": [{"name": "gothic rock", "count": 1}]}


class _Services:
    """MusicBrainz and the Cover Art Archive behind one fake transport, answering by URL.

    `art` is the archive's listing for the release, one `(types, bytes)` per
    image in order; the first `Front` is the release's front. Anything else is a 404.
    """

    def __init__(self, release: dict, release_group: dict, art: list[tuple[list[str], bytes]]) -> None:
        self.release = release
        self.release_group = release_group
        self.bodies = {f"{_ART}/{n}.jpg": data for n, (_types, data) in enumerate(art, 1)}
        self.listing = [{"id": n, "types": types, "front": "Front" in types, "back": "Back" in types,
                         "image": f"{_ART}/{n}.jpg", "thumbnails": {}}
                        for n, (types, _data) in enumerate(art, 1)]

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc == "musicbrainz.org":
            if path == f"/ws/2/release-group/{self.release_group['id']}":
                return 200, json.dumps(self.release_group).encode()
            if path == f"/ws/2/release/{self.release['id']}":
                return 200, json.dumps(self.release).encode()
            return 404, b'{"error": "Not Found"}'
        if parts.netloc == "coverartarchive.org":
            if path == f"/release/{self.release['id']}" and self.listing:
                return 200, json.dumps({"images": self.listing}).encode()
            if url in self.bodies:
                return 200, self.bodies[url]
        return 404, b"Not Found"


def _rip(root: Path) -> Path:
    """A one-disc rip of `_TITLES` at `REL`, loose names, no cover of its own. Returns the album folder."""
    base = root / REL
    base.mkdir(parents=True)
    for number, title in enumerate(_TITLES, start=1):
        path = base / f"{number:02d} {title.lower()}.flac"
        shutil.copyfile(builders.FIXTURES / "tone.flac", path)
        fields = {"title": [title.lower()], "artist": ["The Cure"], "album": ["Disintegration"], "date": ["1989"]}
        builders.write_tags(path, builders.picard_tags("flac", fields, track=(number, len(_TITLES)), disc=(1, 1)),
                            v2_version=4)
    return base


class _Settling(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self._roots = 0

    def album(self, others: dict[str, bytes]) -> Path:
        """A fresh library holding one rip, with `others` (album-relative path to bytes) beside its tracks."""
        self._roots += 1
        root = self.tmp / f"library-{self._roots}"
        album = _rip(root)
        for rel, data in others.items():
            (album / rel).parent.mkdir(parents=True, exist_ok=True)
            (album / rel).write_bytes(data)
        return album

    @staticmethod
    def unit(album: Path) -> Unit:
        return next(u for u in units(album.parents[2]) if u.path == album)

    def plan(self, album: Path, art: list[tuple[list[str], bytes]] | None = None, **kwargs):
        """`plan_album` for the rip at `album`; `art` defaults to the passing `FRONT` alone."""
        services = _Services(_release(), _release_group(), [(["Front"], FRONT)] if art is None else art)
        # A cache of its own per plan: one shared would replay another case's art.
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = mb.MusicBrainz(cache, transport=services, clock=lambda: 0.0, sleep=lambda s: None)
        art_client = caa.CoverArt(cache, transport=services)
        return plan_module.plan_album(self.unit(album), _release(), client, art_client, **kwargs)

    @staticmethod
    def entry(plan, path: str) -> dict:
        """The stray at album-relative `path`, in plan.json's shape."""
        found = [stray.to_json() for stray in plan.strays if stray.path == path]
        if len(found) != 1:
            raise AssertionError(f"{path} is in plan.strays {len(found)} times: {[s.path for s in plan.strays]}")
        return found[0]

    def assertEntry(self, plan, path: str, answer, why: str, against: str | None = None) -> None:
        entry = self.entry(plan, path)
        self.assertEqual((entry["answer"], entry["why"], entry["against"]), (answer, why, against), entry)

    def assertKeptAs(self, plan, path: str, name: str) -> None:
        """`path` moves into the album folder as `name`, and is in neither `kept` nor `deletions`."""
        self.assertEqual(plan.moved.get(f"{REL}/{path}"), name, plan.moved)
        self.assertNotIn(f"{REL}/{path}", plan.kept)
        self.assertNotIn(f"{REL}/{path}", plan.deletions)

    def assertDeleted(self, plan, path: str) -> None:
        self.assertIn(f"{REL}/{path}", plan.deletions)
        self.assertNotIn(f"{REL}/{path}", plan.kept)
        self.assertNotIn(f"{REL}/{path}", plan.moved)

    def assertCover(self, plan, data: bytes, what: str) -> None:
        cover = plan.images.get("cover.jpg")
        size = None if cover is None else Image.open(io.BytesIO(cover)).size
        self.assertTrue(cover == data, f"cover.jpg is not {what}: it is {size}")

    def assertLeft(self, plan, path: str) -> None:
        """`path` stays where it is: in `kept` at its old path, and neither moved nor deleted."""
        self.assertIn(f"{REL}/{path}", plan.kept)
        self.assertNotIn(f"{REL}/{path}", plan.deletions)
        self.assertNotIn(f"{REL}/{path}", plan.moved)


V_FRONT = "COVERS/maroon_5_v_[deluxe_edition]_2014-front.jpg"
V_BACK = "COVERS/maroon_5_v_[deluxe_edition]_2014-back.jpg"
V_CD = "COVERS/maroon_5_v_[deluxe_edition]_2014-cd.jpg"


class TheStrayList(_Settling):
    def test_each_stray_is_listed_in_natural_order_with_its_path_kind_answer_reason_and_size(self) -> None:
        # `part 10` sorts before `part 2` as plain text; natural order puts it after.
        album = self.album({
            "Ziggy Stardust.jpg": _picture(1200, 1200),
            "Scans/part 10.pdf": b"%PDF-1.4 ten",
            "Scans/part 2.pdf": b"%PDF-1.4 two",
            "Extras/info.txt": b"ripped by me",
            "COVERS/v-back.jpg": _picture(1688, 1476),
        })
        plan = self.plan(album)
        self.assertEqual([stray.to_json() for stray in plan.strays], [
            {"path": "COVERS/v-back.jpg", "kind": "image", "answer": {"keep": "back.jpg"},
             "why": "guessed", "against": None, "size": [1688, 1476]},
            {"path": "Extras/info.txt", "kind": "text", "answer": {"keep": "info.txt"},
             "why": "guessed", "against": None, "size": None},
            {"path": "Scans/part 2.pdf", "kind": "pdf", "answer": {"keep": "booklet-1.pdf"},
             "why": "guessed", "against": None, "size": None},
            {"path": "Scans/part 10.pdf", "kind": "pdf", "answer": {"keep": "booklet-2.pdf"},
             "why": "guessed", "against": None, "size": None},
            {"path": "Ziggy Stardust.jpg", "kind": "image", "answer": None,
             "why": "no guess", "against": None, "size": [1200, 1200]},
        ])

    def test_files_that_are_not_strays_are_not_listed(self) -> None:
        # At the root: a local cover's name, a library name, a `.txt` and a `.log`. Only the subfolder's image is a stray.
        album = self.album({
            "front.png": _picture(900, 900),
            "back.jpg": _picture(800, 800),
            "notes.txt": b"notes",
            "rip.log": b"log",
            "COVERS/v-back.jpg": _picture(700, 700),
        })
        plan = self.plan(album)
        self.assertEqual([stray.path for stray in plan.strays], ["COVERS/v-back.jpg"])

    def test_the_plan_json_carries_the_strays_and_the_moves_so_the_digest_follows_the_owners_answer(self) -> None:
        album = self.album({"COVERS/IMG_0001.jpg": _picture(700, 700)})
        as_back = self.plan(album, strays={"COVERS/IMG_0001.jpg": "back.jpg"})
        as_tray = self.plan(album, strays={"COVERS/IMG_0001.jpg": "tray.jpg"})
        self.assertNotEqual(as_back.to_json(), as_tray.to_json())
        doc = json.loads(as_tray.to_json())
        self.assertEqual(doc["moved"], {f"{REL}/COVERS/IMG_0001.jpg": "tray.jpg"})
        self.assertEqual(doc["strays"], [
            {"path": "COVERS/IMG_0001.jpg", "kind": "image", "answer": {"keep": "tray.jpg"},
             "why": "owner", "against": None, "size": [700, 700]},
        ])


class Copies(_Settling):
    # Each copy has no guess of its own, so only the copy rule deletes it.

    def test_a_stray_equal_to_the_planned_cover_is_deleted_as_its_copy(self) -> None:
        album = self.album({"Artwork/IMG_0001.jpg": FRONT})
        plan = self.plan(album)
        self.assertEntry(plan, "Artwork/IMG_0001.jpg", {"delete": True}, "copy", "cover.jpg")
        self.assertDeleted(plan, "Artwork/IMG_0001.jpg")

    def test_a_stray_equal_to_an_archive_image_the_plan_saves_is_deleted_and_the_archive_image_kept(self) -> None:
        back = _picture(1000, 1000)
        album = self.album({"Artwork/IMG_0001.jpg": back})
        plan = self.plan(album, art=[(["Front"], FRONT), (["Back"], back)])
        self.assertEntry(plan, "Artwork/IMG_0001.jpg", {"delete": True}, "copy", "back.jpg")
        self.assertDeleted(plan, "Artwork/IMG_0001.jpg")
        self.assertEqual(plan.images.get("back.jpg"), back)

    def test_a_stray_equal_to_a_file_already_in_the_album_folder_is_deleted_as_its_copy(self) -> None:
        tray = _picture(900, 700)
        album = self.album({"tray.jpg": tray, "Artwork/IMG_0001.jpg": tray})
        plan = self.plan(album)
        self.assertEntry(plan, "Artwork/IMG_0001.jpg", {"delete": True}, "copy", "tray.jpg")
        self.assertDeleted(plan, "Artwork/IMG_0001.jpg")
        self.assertIn(f"{REL}/tray.jpg", plan.kept)

    def test_the_later_of_two_equal_strays_is_deleted_and_the_earlier_left(self) -> None:
        # Natural order: `IMG 2` comes before `IMG 10`, though not as plain text.
        scan = _picture(900, 700)
        album = self.album({"Artwork/IMG 10.jpg": scan, "Artwork/IMG 2.jpg": scan})
        plan = self.plan(album)
        entry = self.entry(plan, "Artwork/IMG 10.jpg")
        self.assertEqual((entry["answer"], entry["why"]), ({"delete": True}, "copy"))
        self.assertDeleted(plan, "Artwork/IMG 10.jpg")
        self.assertEntry(plan, "Artwork/IMG 2.jpg", None, "no guess")
        self.assertLeft(plan, "Artwork/IMG 2.jpg")

    # Numbering counts only the strays that are kept.

    def test_a_back_whose_only_other_back_is_its_copy_is_plain_back(self) -> None:
        back = _picture(1200, 1200)
        album = self.album({"COVERS/x-back.jpg": back, "Scans/back copy.jpg": back})
        plan = self.plan(album)
        entry = self.entry(plan, "Scans/back copy.jpg")
        self.assertEqual((entry["answer"], entry["why"]), ({"delete": True}, "copy"))
        self.assertDeleted(plan, "Scans/back copy.jpg")
        self.assertEntry(plan, "COVERS/x-back.jpg", {"keep": "back.jpg"}, "guessed")
        self.assertKeptAs(plan, "COVERS/x-back.jpg", "back.jpg")

    def test_a_copy_takes_no_number_from_the_backs_that_are_kept(self) -> None:
        # The copy sorts between the two kept backs, so numbering over every
        # stray would give the second `back-3.jpg`.
        first = _picture(1200, 1200)
        album = self.album({"COVERS/x-back.jpg": first, "Scans/back copy.jpg": first,
                            "Scans/z-back.jpg": _picture(1300, 1300)})
        plan = self.plan(album)
        self.assertDeleted(plan, "Scans/back copy.jpg")
        self.assertEqual(self.entry(plan, "Scans/back copy.jpg")["why"], "copy")
        self.assertEntry(plan, "COVERS/x-back.jpg", {"keep": "back-1.jpg"}, "guessed")
        self.assertEntry(plan, "Scans/z-back.jpg", {"keep": "back-2.jpg"}, "guessed")
        self.assertKeptAs(plan, "COVERS/x-back.jpg", "back-1.jpg")
        self.assertKeptAs(plan, "Scans/z-back.jpg", "back-2.jpg")


class AgainstTheArchive(_Settling):
    def test_the_worked_example_a_1688_by_1476_back_beats_1000_by_1000_and_loses_to_1600_by_1500(self) -> None:
        for size, wins in (((1000, 1000), True), ((1600, 1500), False)):
            with self.subTest(archive=size):
                archive_back = _picture(*size)
                album = self.album({V_BACK: _picture(1688, 1476)})
                plan = self.plan(album, art=[(["Front"], FRONT), (["Back"], archive_back)])
                if wins:
                    self.assertEntry(plan, V_BACK, {"keep": "back.jpg"}, "won", "back.jpg")
                    self.assertKeptAs(plan, V_BACK, "back.jpg")
                    self.assertNotIn("back.jpg", plan.images)
                else:
                    self.assertEntry(plan, V_BACK, {"delete": True}, "lost", "back.jpg")
                    self.assertDeleted(plan, V_BACK)
                    self.assertEqual(plan.images.get("back.jpg"), archive_back)

    def test_a_stray_needs_at_least_ten_percent_more_pixels_to_win(self) -> None:
        # 1,100,000 against 1,000,000 is exactly 10 % more; 1,099,000 is not.
        for size, wins in (((1100, 1000), True), ((1099, 1000), False)):
            with self.subTest(stray=size):
                album = self.album({"Scans/back.jpg": _picture(*size)})
                plan = self.plan(album, art=[(["Front"], FRONT), (["Back"], _picture(1000, 1000))])
                self.assertEqual(self.entry(plan, "Scans/back.jpg")["why"], "won" if wins else "lost")
                self.assertEqual("back.jpg" in plan.images, not wins)

    def test_format_does_not_count_and_names_meet_by_stem(self) -> None:
        # A PNG `back.png` meets the archive's `back.jpg`, and being PNG neither helps nor hurts it.
        album = self.album({"Scans/BACK.png": _picture(1688, 1476, "PNG")})
        plan = self.plan(album, art=[(["Front"], FRONT), (["Back"], _picture(1000, 1000))])
        self.assertEntry(plan, "Scans/BACK.png", {"keep": "back.png"}, "won", "back.jpg")
        self.assertKeptAs(plan, "Scans/BACK.png", "back.png")
        self.assertNotIn("back.jpg", plan.images)

    def test_a_stray_that_is_not_an_image_loses_to_the_archive(self) -> None:
        archive_back = _picture(1000, 1000)
        album = self.album({"Scans/back.jpg": b"not an image at all"})
        plan = self.plan(album, art=[(["Front"], FRONT), (["Back"], archive_back)])
        self.assertEqual(self.entry(plan, "Scans/back.jpg"), {
            "path": "Scans/back.jpg", "kind": "image", "answer": {"delete": True},
            "why": "lost", "against": "back.jpg", "size": None})
        self.assertDeleted(plan, "Scans/back.jpg")
        self.assertEqual(plan.images.get("back.jpg"), archive_back)


class OneName(_Settling):
    def test_two_strays_of_one_name_whose_quality_cannot_be_told_are_both_left_for_the_owner(self) -> None:
        # PDFs keep their own name, so these two meet; neither is an image, so neither is better.
        album = self.album({"Liner/notes.pdf": b"%PDF-1.4 liner", "Press/notes.pdf": b"%PDF-1.4 press"})
        plan = self.plan(album)
        for path in ("Liner/notes.pdf", "Press/notes.pdf"):
            with self.subTest(path=path):
                self.assertIsNone(self.entry(plan, path)["answer"])
                self.assertLeft(plan, path)

    def test_a_stray_takes_a_root_files_name_only_by_the_margin(self) -> None:
        for size, wins in (((1688, 1476), True), ((1000, 1000), False)):
            with self.subTest(stray=size):
                album = self.album({"back.jpg": _picture(1000, 1000), "Scans/back.jpg": _picture(*size)})
                plan = self.plan(album)
                if wins:
                    self.assertEntry(plan, "Scans/back.jpg", {"keep": "back.jpg"}, "won", "back.jpg")
                    self.assertKeptAs(plan, "Scans/back.jpg", "back.jpg")
                    self.assertIn(f"{REL}/back.jpg", plan.deletions)
                    self.assertNotIn(f"{REL}/back.jpg", plan.kept)
                else:
                    # Quality cannot be told: the root file wins.
                    self.assertEntry(plan, "Scans/back.jpg", {"delete": True}, "lost", "back.jpg")
                    self.assertDeleted(plan, "Scans/back.jpg")
                    self.assertIn(f"{REL}/back.jpg", plan.kept)


class WithoutTheOwner(_Settling):
    def test_an_album_whose_strays_all_have_a_guess_lands_them_renamed_and_is_not_held(self) -> None:
        album = self.album({V_FRONT: _picture(1500, 1500), V_BACK: _picture(1688, 1476), V_CD: _picture(1000, 1000)})
        plan = self.plan(album)
        self.assertEqual(plan.moved, {f"{REL}/{V_FRONT}": "front.jpg", f"{REL}/{V_BACK}": "back.jpg",
                                      f"{REL}/{V_CD}": "medium.jpg"})
        for path in (V_FRONT, V_BACK, V_CD):
            with self.subTest(path=path):
                self.assertEqual(self.entry(plan, path)["why"], "guessed")
                self.assertKeptAs(plan, path, plan.moved[f"{REL}/{path}"])
        self.assertEqual(plan.problems, [])

    def test_an_undecided_stray_in_a_subfolder_stays_there_and_holds_the_album(self) -> None:
        album = self.album({"COVERS/IMG_0001.jpg": _picture(700, 700), V_BACK: _picture(1688, 1476)})
        plan = self.plan(album)
        self.assertEntry(plan, "COVERS/IMG_0001.jpg", None, "no guess")
        self.assertLeft(plan, "COVERS/IMG_0001.jpg")
        self.assertKeptAs(plan, V_BACK, "back.jpg")
        self.assertIn("subfolder: COVERS", plan.problems)

    def test_an_undecided_root_image_stays_under_its_own_name_and_holds_nothing(self) -> None:
        album = self.album({"Ziggy Stardust.jpg": _picture(1200, 1200)})
        plan = self.plan(album)
        self.assertEntry(plan, "Ziggy Stardust.jpg", None, "no guess")
        self.assertLeft(plan, "Ziggy Stardust.jpg")
        self.assertEqual(plan.problems, [])


class TheOwnersAnswers(_Settling):
    def test_the_owners_name_and_delete_replace_agithas_and_a_path_left_out_keeps_agithas(self) -> None:
        album = self.album({"COVERS/IMG_0001.jpg": _picture(700, 700), V_BACK: _picture(1688, 1476),
                            V_CD: _picture(1000, 1000)})
        plan = self.plan(album, strays={"COVERS/IMG_0001.jpg": "booklet-01.jpg", V_BACK: None})
        self.assertEntry(plan, "COVERS/IMG_0001.jpg", {"keep": "booklet-01.jpg"}, "owner")
        self.assertKeptAs(plan, "COVERS/IMG_0001.jpg", "booklet-01.jpg")
        self.assertEntry(plan, V_BACK, {"delete": True}, "owner")
        self.assertDeleted(plan, V_BACK)
        self.assertEntry(plan, V_CD, {"keep": "medium.jpg"}, "guessed")
        self.assertKeptAs(plan, V_CD, "medium.jpg")
        self.assertEqual(plan.problems, [])

    def test_a_named_stray_shows_in_changes_as_a_move_into_the_album_folder(self) -> None:
        album = self.album({"COVERS/IMG_0001.jpg": _picture(700, 700)})
        plan = self.plan(album, strays={"COVERS/IMG_0001.jpg": "booklet-01.jpg"})
        self.assertIn(f"move: {REL}/COVERS/IMG_0001.jpg -> {plan.destination}/booklet-01.jpg",
                      plan_module.changes(plan))

    def test_the_owners_name_beats_the_archive_image_of_that_name_without_the_quality_test(self) -> None:
        # Far smaller than the archive's back: the quality test alone would delete it.
        album = self.album({"COVERS/IMG_0001.jpg": _picture(300, 300)})
        plan = self.plan(album, art=[(["Front"], FRONT), (["Back"], _picture(1600, 1500))],
                         strays={"COVERS/IMG_0001.jpg": "back.jpg"})
        self.assertEqual(self.entry(plan, "COVERS/IMG_0001.jpg")["answer"], {"keep": "back.jpg"})
        self.assertEqual(self.entry(plan, "COVERS/IMG_0001.jpg")["why"], "owner")
        self.assertKeptAs(plan, "COVERS/IMG_0001.jpg", "back.jpg")
        self.assertNotIn("back.jpg", plan.images)


class TheFront(_Settling):
    def test_a_stray_kept_as_front_becomes_the_cover_when_the_archive_front_fails_and_stays_as_front(self) -> None:
        stray_front = _picture(1400, 1400)
        album = self.album({V_FRONT: stray_front})
        # Its shorter side is under 500 px, so it fails the cover test.
        plan = self.plan(album, art=[(["Front"], _picture(400, 400))])
        self.assertCover(plan, stray_front, "the stray front")
        # Copied, never moved: not deleted as a copy of the cover it became.
        self.assertEntry(plan, V_FRONT, {"keep": "front.jpg"}, "guessed")
        self.assertKeptAs(plan, V_FRONT, "front.jpg")

    def test_a_passing_archive_front_stays_the_cover_beside_a_stray_front(self) -> None:
        album = self.album({V_FRONT: _picture(1400, 1400)})
        plan = self.plan(album)
        self.assertCover(plan, FRONT, "the archive's front")
        self.assertKeptAs(plan, V_FRONT, "front.jpg")

    def test_the_owners_cover_upload_is_the_cover_and_a_stray_front_stays_beside_it(self) -> None:
        upload = _picture(1500, 1500)
        album = self.album({V_FRONT: _picture(1400, 1400)})
        plan = self.plan(album, owner_cover=upload)
        self.assertCover(plan, upload, "the owner's upload")
        self.assertEntry(plan, V_FRONT, {"keep": "front.jpg"}, "guessed")
        self.assertKeptAs(plan, V_FRONT, "front.jpg")


class AnEditThatMovesTheAlbum(_Settling):
    # `lay_edits` sorts the files again when an edit moves the album.

    def test_lay_edits_settles_every_stray_as_plan_album_did(self) -> None:
        answers = {"COVERS/IMG_0001.jpg": "booklet-01.jpg", V_CD: None}
        album = self.album({
            V_BACK: _picture(1688, 1476),                # beats the archive's back
            V_CD: _picture(1000, 1000),                  # the owner deletes it
            "COVERS/IMG_0001.jpg": _picture(700, 700),   # the owner names it
            "Ziggy Stardust.jpg": _picture(1200, 1200),  # undecided at the root
        })
        plan = self.plan(album, art=[(["Front"], FRONT), (["Back"], _picture(1000, 1000))], strays=answers)
        before = {
            "destination": plan.destination,
            "strays": [stray.to_json() for stray in plan.strays],
            "moved": dict(plan.moved),
            "deletions": sorted(plan.deletions),
            "kept": sorted(plan.kept),
            "images": sorted(plan.images),
        }
        self.assertEqual(plan.problems, [], "the plan before the edit is not clean")

        unit = self.unit(album)
        root = album.parents[2]
        pairs = pair(unit, _release())
        families = {Path(t.path).relative_to(root).as_posix(): t.family for t in unit.tracks}
        edits = {position_key(p): {"album": ["Disintegration (Remastered)"]} for p in pairs}
        plan = memory.lay_edits(plan, edits, _release(), _release_group(), pairs, families, unit, None,
                                "The Cure", strays=answers)

        self.assertNotEqual(plan.destination, before["destination"], "the edit did not move the album")
        self.assertEqual([stray.to_json() for stray in plan.strays], before["strays"])
        self.assertEqual(plan.moved, before["moved"])
        self.assertEqual(sorted(plan.deletions), before["deletions"])
        self.assertEqual(sorted(plan.kept), before["kept"])
        self.assertEqual(sorted(plan.images), before["images"])
        self.assertEqual(plan.problems, [])


if __name__ == "__main__":
    unittest.main()
