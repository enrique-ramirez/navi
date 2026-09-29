"""Titles in a Latin script for a release that is not in one (criteria 55 and 56).

A release whose `text-representation` script is not `Latn` is planned with
the album and track titles of a Latin pseudo-release it links to by a
`transl-tracklisting` relation, as long as that pseudo-release has the same
media and per-medium track counts. The English one wins over a
transliteration. Everything else stays the real release's. When identifying,
a file title passes against either the real title or the pseudo-release's.

The fixture is shaped like `64708be7-06e6-4c19-b441-65472fb8c3a6`, the
*Final Fantasy VII Advent Children* soundtrack (script `Jpan`). Track 2's
three titles are the real ones; the other titles, the pseudo-release MBIDs
and the counts are made up. Each pseudo-release carries its own date,
label, country, lengths, disc title and IDs, all different from the real
release's, so a plan that took any of them from the pseudo-release shows.

MusicBrainz is a fake server behind the real client. A release's relations
come from their own lookup, `/ws/2/release/{id}?inc=release-rels`, never from
the release lookup, and each pseudo-release from the normal release lookup.
The server records every URL, so "no relations lookup" means no URL asking
for `release-rels`.
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlsplit

from musiclib import caa, mb
from musiclib.cache import Cache
from tests.test_check import _Planning, _plan_album, _release_group, _rip
from tests.test_identify import IdentifyTestCase, search_json, unit, vorbis

REAL_ID = "64708be7-06e6-4c19-b441-65472fb8c3a6"
ENGLISH_ID = "e0e0e0e0-0000-4000-8000-000000000001"
ROMAJI_ID = "e0e0e0e0-0000-4000-8000-000000000002"
HANGUL_ID = "e0e0e0e0-0000-4000-8000-000000000003"
SPLIT_ID = "e0e0e0e0-0000-4000-8000-000000000004"
REMASTER_ID = "e0e0e0e0-0000-4000-8000-000000000005"

UEMATSU_ID = "e1e1e1e1-0000-4000-8000-000000000001"
PSEUDO_ARTIST_ID = "e1e1e1e1-0000-4000-8000-000000000002"

TRANSL_TRACKLISTING = "fc399d47-23a7-4c28-bfcf-0607a562b644"

# The real release: two discs, three tracks and two.
REAL_ALBUM = "ファイナルファンタジーVII アドベントチルドレン オリジナル・サウンドトラック"
REAL_TITLES = [["開幕", "約束の地 〜The Promised Land〜", "北の大空洞"], ["片翼の天使", "ボーナストラック"]]
REAL_DISC_2 = "特典ディスク"

ENGLISH_ALBUM = "Final Fantasy VII Advent Children Original Soundtrack"
ENGLISH_TITLES = [["Opening", "The Promised Land", "Beyond the Wasteland"], ["One-Winged Angel", "Bonus Track"]]

ROMAJI_ALBUM = "Fainaru Fantaji VII Adobento Chirudoren Orijinaru Saundotorakku"
ROMAJI_TITLES = [["Kaimaku", "Yakusoku no Chi ~The Promised Land~", "Kita no Daikuudou"],
                 ["Katayoku no Tenshi", "Bonasu Torakku"]]

HANGUL_ALBUM = "파이널 판타지 VII 어드벤트 칠드런"
HANGUL_TITLES = [["개막", "약속의 땅", "북쪽의 대공동"], ["편익의 천사", "보너스 트랙"]]


def _credit(artist_id: str, name: str, sort_name: str) -> list[dict]:
    return [{"name": name, "joinphrase": "", "artist": {"id": artist_id, "name": name, "sort-name": sort_name}}]


def _media(seed: str, titles: list[list[str]], lengths: list[list[float | None]] | None,
           disc_titles: list[str], credit: list[dict]) -> list[dict]:
    media = []
    for position, medium_titles in enumerate(titles, start=1):
        tracks = []
        for number, title in enumerate(medium_titles, start=1):
            seconds = lengths[position - 1][number - 1] if lengths else 200.0 + position * 10 + number
            ms = None if seconds is None else round(seconds * 1000)
            tracks.append({
                "id": f"{seed}{position}{number:02d}000-0000-4000-8000-00000000000a",
                "position": number, "number": str(number), "title": title, "length": ms,
                "artist-credit": copy.deepcopy(credit),
                "recording": {"id": f"{seed}{position}{number:02d}000-0000-4000-8000-00000000000b",
                              "title": title, "length": ms},
            })
        media.append({"position": position, "format": "CD", "title": disc_titles[position - 1],
                      "track-count": len(tracks), "tracks": tracks})
    return media


def real_release(*, script: str | None = "Jpan", titles=REAL_TITLES, lengths=None,
                 represented: bool = True) -> dict:
    """The real release, as the release lookup returns it.

    `represented=False` leaves `text-representation` out altogether, where
    `script=None` gives it with a null script, as MusicBrainz does for a
    release nobody set one on.
    """
    release = {
        "id": REAL_ID, "title": REAL_ALBUM, "status": "Official", "date": "2005-09-14", "country": "JP",
        "barcode": "4988601460115",
        "label-info": [{"catalog-number": "SQEX-10051", "label": {"id": "f1f1f1f1-0000-4000-8000-000000000001",
                                                                   "name": "SQUARE ENIX"}}],
        "artist-credit": _credit(UEMATSU_ID, "Nobuo Uematsu", "Uematsu, Nobuo"),
        "release-group": {"id": _release_group()["id"], "title": REAL_ALBUM, "primary-type": "Album",
                          "secondary-types": [], "first-release-date": "2005-09-14"},
        "media": _media("aa", titles, lengths, ["", REAL_DISC_2][:len(titles)],
                        _credit(UEMATSU_ID, "Nobuo Uematsu", "Uematsu, Nobuo")),
    }
    if represented:
        release["text-representation"] = {"script": script, "language": "jpn" if script else None}
    return release


def pseudo_release(release_id: str, album: str, titles: list[list[str]], *, script: str = "Latn",
                   language: str = "eng", lengths=None) -> dict:
    """A pseudo-release, as the release lookup returns it, differing from the real release in every field."""
    seed = release_id[-2:]
    return {
        "id": release_id, "title": album, "status": "Pseudo-Release", "date": "2011-04-20", "country": "XW",
        "text-representation": {"script": script, "language": language},
        "label-info": [{"catalog-number": "PSEUDO-1", "label": {"id": "f1f1f1f1-0000-4000-8000-000000000002",
                                                                 "name": "Pseudo Label"}}],
        "artist-credit": _credit(PSEUDO_ARTIST_ID, "Uematsu Nobuo", "Nobuo, Uematsu"),
        "release-group": {"id": "f2f2f2f2-0000-4000-8000-000000000001", "title": album, "primary-type": "Album",
                          "secondary-types": [], "first-release-date": "2011-04-20"},
        "media": _media(seed, titles, lengths, ["", "Pseudo Disc"][:len(titles)],
                        _credit(PSEUDO_ARTIST_ID, "Uematsu Nobuo", "Nobuo, Uematsu")),
    }


def english(titles=ENGLISH_TITLES, **kwargs) -> dict:
    return pseudo_release(ENGLISH_ID, ENGLISH_ALBUM, titles, **kwargs)


def romaji(titles=ROMAJI_TITLES, **kwargs) -> dict:
    return pseudo_release(ROMAJI_ID, ROMAJI_ALBUM, titles, language="jpn", **kwargs)


def link(target: dict, direction: str = "forward", kind: str = "transl-tracklisting") -> dict:
    """One entry of a release's `relations`, as `inc=release-rels` gives it."""
    return {
        "type": kind, "type-id": TRANSL_TRACKLISTING if kind == "transl-tracklisting" else None,
        "direction": direction, "target-type": "release", "attributes": [], "ended": False,
        "release": {"id": target["id"], "title": target["title"], "status": target.get("status")},
    }


class LatinServer:
    """MusicBrainz and a Cover Art Archive with nothing in it, answering by URL and recording every one.

    `relations` is what `inc=release-rels` gives for each release ID, none
    for a release it does not name. Any other release lookup answers from
    `releases`. Artists are answered plainly, so an artist rule elsewhere
    never stops a plan here.
    """

    def __init__(self, releases: list[dict], relations: dict[str, list[dict]] | None = None,
                 search: dict | None = None) -> None:
        self.releases = {r["id"]: r for r in releases}
        self.relations = relations or {}
        self.search = search
        self.urls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.urls.append(url)
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        if parts.netloc != "musicbrainz.org":
            return 404, b"Not Found"
        if path == "/ws/2/release" and self.search is not None:
            return 200, json.dumps(self.search).encode()
        if path.startswith("/ws/2/release-group/"):
            return 200, json.dumps(_release_group()).encode()
        if path.startswith("/ws/2/artist/"):
            artist_id = path.rsplit("/", 1)[1]
            return 200, json.dumps({"id": artist_id, "name": "Nobuo Uematsu", "sort-name": "Uematsu, Nobuo",
                                    "aliases": [], "genres": []}).encode()
        if path.startswith("/ws/2/release/"):
            release = self.releases.get(path.rsplit("/", 1)[1])
            if release is None:
                return 404, b'{"error": "Not Found"}'
            if self.asks_for_relations(url):
                # A relations lookup gives the release's own fields and its
                # relations, never its media.
                head = {k: v for k, v in release.items() if k not in ("media", "artist-credit", "label-info")}
                return 200, json.dumps({**head, "relations": self.relations.get(release["id"], [])}).encode()
            return 200, json.dumps(release).encode()
        return 404, b'{"error": "Not Found"}'

    @staticmethod
    def asks_for_relations(url: str) -> bool:
        inc = parse_qs(urlsplit(url).query).get("inc", [""])[0]
        return "release-rels" in inc.split("+")

    def relation_lookups(self) -> list[str]:
        return [urlsplit(u).path.rsplit("/", 1)[1] for u in self.urls if self.asks_for_relations(u)]


def everything(release: dict, *pseudo: dict, relations: list[dict] | None = None) -> LatinServer:
    """A server knowing `release` and `pseudo`, the real release linking to each pseudo-release in order."""
    links = relations if relations is not None else [link(p) for p in pseudo]
    return LatinServer([release, *pseudo], {release["id"]: links})


# --- criterion 55: planning ---------------------------------------------------


class Planning(_Planning):
    def planned(self, release: dict, server: LatinServer):
        root = self.library()
        discs = [[f"track {n}" for n in range(1, len(medium["tracks"]) + 1)] for medium in release["media"]]
        album = _rip(root, *discs, where="U/Uematsu/Advent Children [rip]", album="Advent Children")
        cache = Cache(Path(tempfile.mkdtemp(prefix="cache-", dir=self.tmp)))
        client = mb.MusicBrainz(cache, transport=server, clock=lambda: 0.0, sleep=lambda s: None)
        art = caa.CoverArt(cache, transport=server)
        return _plan_album(self.unit(root, album), release, client, art, status="auto")

    def assertTitled(self, plan, album: str, titles: list[list[str]]) -> None:
        """Every file's ALBUM is `album`, its TITLE the one at its place in `titles`, and so are the names."""
        self.assertEqual([f.target["album"] for f in plan.files], [[album]] * sum(map(len, titles)))
        self.assertEqual([f.target["title"][0] for f in plan.files], [t for medium in titles for t in medium])
        self.assertTrue(PurePosixPath(plan.destination).name.endswith(f") {album}"), plan.destination)
        self.assertEqual(
            [PurePosixPath(f.destination).relative_to(plan.destination).as_posix() for f in plan.files],
            [f"CD{disc}/{number:02d}. {title}.flac"
             for disc, medium in enumerate(titles, start=1) for number, title in enumerate(medium, start=1)],
        )


class TakesTheLatinTitles(Planning):
    def test_a_jpan_release_takes_the_english_pseudo_releases_album_and_track_titles(self):
        # The transliteration is listed before the English one, so a plan
        # that takes the first Latin pseudo-release it finds gets `Yakusoku
        # no Chi`. The English one is linked `backward`, which MusicBrainz
        # also gives, and a remaster link to a Latin release with the same
        # counts is not a translation of anything.
        remaster = pseudo_release(REMASTER_ID, "Advent Children Remastered",
                                  [["A", "B", "C"], ["D", "E"]], language="eng")
        release = real_release()
        server = everything(release, romaji(), english(), remaster, relations=[
            link(remaster, "backward", kind="remaster"), link(romaji()), link(english(), "backward")])

        plan = self.planned(release, server)

        self.assertTitled(plan, ENGLISH_ALBUM, ENGLISH_TITLES)
        self.assertIn("02. The Promised Land.flac", [PurePosixPath(f.destination).name for f in plan.files])

    def test_everything_but_the_titles_stays_the_real_releases(self):
        release = real_release()
        plan = self.planned(release, everything(release, english()))

        self.assertEqual(plan.release_id, REAL_ID)
        self.assertTrue(PurePosixPath(plan.destination).name.startswith("(2005) "), plan.destination)
        real_tracks = [t for medium in release["media"] for t in medium["tracks"]]
        for file_plan, mb_track in zip(plan.files, real_tracks, strict=True):
            target = file_plan.target
            self.assertEqual(target["musicbrainz_albumid"], [REAL_ID])
            self.assertEqual(target["musicbrainz_releasegroupid"], [release["release-group"]["id"]])
            self.assertEqual(target["musicbrainz_releasetrackid"], [mb_track["id"]])
            self.assertEqual(target["musicbrainz_trackid"], [mb_track["recording"]["id"]])
            self.assertEqual(target["musicbrainz_artistid"], [UEMATSU_ID])
            self.assertEqual(target["musicbrainz_albumartistid"], [UEMATSU_ID])
            self.assertEqual(target["artist"], ["Nobuo Uematsu"])
            self.assertEqual(target["date"], ["2005-09-14"])
            self.assertEqual(target["label"], ["SQUARE ENIX"])
            self.assertEqual(target["catalognumber"], ["SQEX-10051"])
            self.assertEqual(target["releasecountry"], ["JP"])
        self.assertEqual([f.target.get("discsubtitle") for f in plan.files[3:]], [[REAL_DISC_2]] * 2)
        self.assertEqual(plan.files[1].target["title"], ["The Promised Land"])

    def test_with_no_english_pseudo_release_the_transliteration_is_taken(self):
        # The Korean translation comes first and has the same counts, but it
        # is in Hangul: only a Latin pseudo-release gives Latin titles.
        hangul = pseudo_release(HANGUL_ID, HANGUL_ALBUM, HANGUL_TITLES, script="Hang", language="kor")
        release = real_release()
        plan = self.planned(release, everything(release, hangul, romaji()))

        self.assertTitled(plan, ROMAJI_ALBUM, ROMAJI_TITLES)

    def test_a_pseudo_release_with_other_per_medium_counts_is_passed_over(self):
        # Same five tracks, split two and three instead of three and two: a
        # check on the total alone takes it and tags every track after the
        # second with another track's title.
        split = pseudo_release(SPLIT_ID, ENGLISH_ALBUM, [["Opening", "The Promised Land"],
                                                         ["Beyond the Wasteland", "One-Winged Angel", "Bonus Track"]])
        release = real_release()
        with self.subTest("a transliteration with the same counts is taken instead"):
            self.assertTitled(self.planned(release, everything(release, split, romaji())),
                              ROMAJI_ALBUM, ROMAJI_TITLES)
        with self.subTest("with nothing else, the release is planned as it is"):
            self.assertTitled(self.planned(release, everything(release, split)), REAL_ALBUM, REAL_TITLES)


class PlannedAsItIs(Planning):
    def test_a_release_with_no_script_keeps_its_own_titles_though_it_links_an_english_pseudo_release(self):
        # The control comes first: the same release marked `Jpan` does take
        # the English titles. Without it, the cases below would pass on an
        # engine that never looks for pseudo-releases at all.
        with self.subTest("control: Jpan with an English pseudo-release"):
            release = real_release()
            self.assertTitled(self.planned(release, everything(release, english())), ENGLISH_ALBUM, ENGLISH_TITLES)
        for case, release in (("no text-representation", real_release(represented=False)),
                              ("a null script", real_release(script=None))):
            with self.subTest(case):
                self.assertTitled(self.planned(release, everything(release, english())), REAL_ALBUM, REAL_TITLES)

    def test_a_latn_release_is_planned_as_it_is_without_a_relations_lookup(self):
        # The control shows the fake records the lookup when there is one,
        # so the empty list for the Latin release is not an absence the fake
        # could never have seen.
        release = real_release()
        control = everything(release, english())
        self.planned(release, control)
        self.assertEqual(control.relation_lookups(), [REAL_ID])

        latin = real_release(script="Latn")
        server = everything(latin, english())
        plan = self.planned(latin, server)

        self.assertTitled(plan, REAL_ALBUM, REAL_TITLES)
        self.assertEqual(server.relation_lookups(), [])


# --- criterion 56: identifying -------------------------------------------------

#: One disc, cut down from the real one. Track 2's real title is only the
#: Japanese: MusicBrainz's `約束の地 〜The Promised Land〜` already contains the
#: English and agrees with it by criterion 3, pseudo-release or not.
ONE_DISC = [["開幕", "約束の地", "北の大空洞"]]
LENGTHS = [[95.0, 301.0, 183.0]]
# The pseudo-release's own lengths are far from the files', so a pair that
# took them instead of the real release's fails on length.
PSEUDO_LENGTHS = [[500.0, 600.0, 700.0]]


class Identifying(IdentifyTestCase):
    def files(self, titles: list[str]):
        tracks = [vorbis(self.album, f"{n:02d}. {title}.flac", seconds, tracknumber=str(n), title=title,
                         album="Final Fantasy VII Advent Children", albumartist="Nobuo Uematsu",
                         artist="Nobuo Uematsu")
                  for n, (title, seconds) in enumerate(zip(titles, LENGTHS[0]), start=1)]
        return unit(self.album, tracks)

    def searched(self, files, release: dict, *pseudo: dict, relate: bool = True):
        server = LatinServer([release, *pseudo], {release["id"]: [link(p) for p in pseudo] if relate else []},
                             search=search_json(release))
        self.forget()
        return self.identify(files, server), server

    def test_a_file_titled_in_english_passes_against_the_japanese_title_through_the_english_pseudo_release(self):
        # Tracks 1 and 3 keep the Japanese titles and track 2 has the
        # English: each pair passes on whichever of the two titles it agrees
        # with.
        files = self.files(["開幕", "The Promised Land", "北の大空洞"])
        pseudo = english(ENGLISH_TITLES[:1], lengths=PSEUDO_LENGTHS)
        release = real_release(titles=ONE_DISC, lengths=LENGTHS)

        without, _ = self.searched(files, release, pseudo, relate=False)
        self.assertEqual(without.status, "review", "track 2 passed with no pseudo-release to agree with")

        result, _ = self.searched(files, release, pseudo)
        self.assertEqual((result.status, result.reason), ("auto", None))
        self.assertEqual(result.candidates[0].release_id, REAL_ID)

    def test_a_file_titled_in_the_transliteration_passes_when_that_is_the_only_latin_pseudo_release(self):
        files = self.files(["開幕", "Yakusoku no Chi", "北の大空洞"])
        pseudo = romaji([["Kaimaku", "Yakusoku no Chi", "Kita no Daikuudou"]], lengths=PSEUDO_LENGTHS)
        release = real_release(titles=ONE_DISC, lengths=LENGTHS)

        without, _ = self.searched(files, release, pseudo, relate=False)
        self.assertEqual(without.status, "review", "track 2 passed with no pseudo-release to agree with")

        result, _ = self.searched(files, release, pseudo)
        self.assertEqual((result.status, result.reason), ("auto", None))

    def test_a_latn_candidate_is_never_asked_for_its_relations(self):
        files = self.files(["開幕", "The Promised Land", "北の大空洞"])
        pseudo = english(ENGLISH_TITLES[:1], lengths=PSEUDO_LENGTHS)

        # The control: the same candidate marked `Jpan` is asked, so the
        # empty list below is an absence the fake would have recorded.
        _, control = self.searched(files, real_release(titles=ONE_DISC, lengths=LENGTHS), pseudo)
        self.assertEqual(control.relation_lookups(), [REAL_ID])

        result, server = self.searched(files, real_release(script="Latn", titles=ONE_DISC, lengths=LENGTHS), pseudo)
        self.assertEqual(server.relation_lookups(), [])
        self.assertEqual(result.status, "review")
