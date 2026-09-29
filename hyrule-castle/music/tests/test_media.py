"""Which files go on which medium, when the files and MusicBrainz count media differently.

A pregap (hidden) track is the first track of its medium, numbered 0 and
named `00. Title.ext`, while the medium's track total stays MusicBrainz's.
Files with nothing about media on them are cut across the release's media
in order when the totals match. A video track does not count, and a medium
left with none does not count as a medium, so a CD plus DVD release is a
one-disc album.

The identify cases run against the fake MusicBrainz server of
`tests.test_identify`, with releases built here so every track has a title
of its own: a file paired with the wrong track fails on its title. The plan
cases write real files and plan them through `test_check`'s fake services,
so what they read back is the destination and tags a write would give.

MusicBrainz shapes, as a release lookup gives them: a pregap is
`media[i]["pregap"]`, a track object at position 0 beside `media[i]["tracks"]`,
and a video track has `recording["video"]` true.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path, PurePosixPath

from musiclib import files
from tests import builders
from tests.test_check import CURE, _Planning, _release
from tests.test_identify import IdentifyTestCase, Server, mbid, search_json, unit, vorbis

TAGGED = "3f1b0c0e-5a4d-4c1e-9d2a-7b6f0e1a2c3d"

# Twenty titles no two of which agree by criterion 3, so a file paired one
# track off fails on its title whatever its length.
WORDS = ["Amber", "Birch", "Cobalt", "Dune", "Ember", "Fjord", "Glacier", "Heron", "Indigo", "Juniper",
         "Kestrel", "Lagoon", "Meadow", "Nettle", "Orchid", "Pebble", "Quartz", "Raven", "Sorrel", "Thistle"]
DVD = ["Making Of", "Promo Clip", "Live at Wembley"]
HIDDEN = "Wayfarer"


def audio(title: str, seconds: float) -> dict:
    return {"title": title, "seconds": seconds, "video": False}


def video(title: str, seconds: float) -> dict:
    return {"title": title, "seconds": seconds, "video": True}


def _mb_track(number: int, spec: dict, medium: int) -> dict:
    ms = round(spec["seconds"] * 1000)
    recording = {"id": mbid(f"{medium}{number:02d}"), "title": spec["title"], "length": ms}
    if spec["video"]:
        recording["video"] = True
    return {"id": mbid(f"t{medium}{number:02d}"), "position": number, "number": str(number),
            "title": spec["title"], "length": ms, "recording": recording}


def media_release(release_id: str, media: list[list[dict]], *, pregap: dict | None = None,
                  formats: list[str] | None = None) -> dict:
    """A release as `mb.release` returns it, one list of `audio`/`video` tracks per medium.

    `pregap` puts a hidden track ahead of medium 1. MusicBrainz counts it in
    the medium's `track-count` but not in `tracks`, so a total read off
    `track-count` shows up as 11 where it should be 10.
    """
    out = []
    for position, specs in enumerate(media, start=1):
        tracks = [_mb_track(n, spec, position) for n, spec in enumerate(specs, start=1)]
        medium = {"position": position, "format": formats[position - 1] if formats else "CD",
                  "track-count": len(tracks), "tracks": tracks}
        if pregap is not None and position == 1:
            medium["pregap"] = _mb_track(0, pregap, position)
            medium["track-count"] += 1
        out.append(medium)
    return {
        "id": release_id, "title": "The Downward Spiral", "status": "Official", "date": "1994-03-08",
        "release-group": {"id": mbid("9"), "title": "The Downward Spiral", "primary-type": "Album"},
        "artist-credit": [{"name": "Nine Inch Nails", "joinphrase": "",
                           "artist": {"id": mbid("8"), "name": "Nine Inch Nails"}}],
        "media": out,
    }


def answering(release: dict) -> Server:
    """A server that knows `release` and lists it in any search.

    A tagged release whose counts do not fit falls through to a search, and
    a search the fake cannot answer raises rather than giving a status.
    """
    return Server(releases=(release,), search=search_json(release))


def lengths(n: int, start: float = 200.0) -> list[float]:
    """`n` lengths 7 s apart, so no two tracks are the same length."""
    return [start + 7 * i for i in range(n)]


class MediaIdentifyCase(IdentifyTestCase):
    def identify(self, the_unit, server, **kwargs):
        # No AcoustID key and no fpcalc, so a machine that has both reaches
        # the same status as one that has neither.
        return super().identify(the_unit, server, **{"env": {}, "which": lambda _: None, **kwargs})

    def flac_files(self, specs: list[tuple[str, str, float]], release_id: str | None = None,
              numbered: bool = True, **extra: str) -> list[files.Track]:
        """FLAC tracks from `(filename, title, seconds)`, with track numbers 1, 2, 3 in the order given when `numbered`."""
        out = []
        for number, (name, title, seconds) in enumerate(specs, start=1):
            tags = {"title": title, "album": "The Downward Spiral", "albumartist": "Nine Inch Nails",
                    "artist": "Nine Inch Nails", **extra}
            if numbered:
                tags["tracknumber"] = str(number)
            if release_id:
                tags["musicbrainz_albumid"] = release_id
            out.append(vorbis(self.album, name, seconds, **tags))
        return out

    def assertCountsDoNotFit(self, result) -> None:
        self.assertNotIn(result.status, ("certain", "auto"))
        self.assertEqual([c.matches_counts for c in result.candidates], [False] * len(result.candidates))

    def assertPairedByTitle(self, result, expected_titles: list[str]) -> None:
        """Every file of the top candidate is paired with the track of its own title, and only those."""
        pairs = [(p.file.tags["title"][0], p.mb_track["title"]) for p in result.candidates[0].pairs]
        self.assertEqual(sorted(pairs), sorted((t, t) for t in expected_titles))


# --- criterion 12: a pregap is track 0 ----------------------------------------


class PregapIdentify(MediaIdentifyCase):
    def setUp(self) -> None:
        super().setUp()
        seconds = lengths(10)
        self.release = media_release(TAGGED, [[audio(t, s) for t, s in zip(WORDS[:10], seconds)]],
                                     pregap=audio(HIDDEN, 95))
        self.titles = [HIDDEN, *WORDS[:10]]
        self.seconds = [95.0, *seconds]

    def identified(self, tracks: list[files.Track]):
        return self.identify(unit(self.album, tracks), answering(self.release))

    def test_eleven_files_whose_first_is_tagged_track_0_are_certain_against_a_pregap_and_10_tracks(self) -> None:
        tracks = [vorbis(self.album, f"{n:02d}. {t}.flac", s + 0.4, title=t, tracknumber=str(n),
                         musicbrainz_albumid=TAGGED)
                  for n, (t, s) in enumerate(zip(self.titles, self.seconds))]
        result = self.identified(tracks)
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, self.titles)

    def test_with_no_track_number_tags_the_file_whose_name_leads_with_00_is_the_pregap(self) -> None:
        # Listed out of order, so the pairing has to come from the names.
        tracks = [vorbis(self.album, f"{n:02d} {t}.flac", s, title=t, musicbrainz_albumid=TAGGED)
                  for n, (t, s) in enumerate(zip(self.titles, self.seconds))]
        tracks = tracks[1:] + tracks[:1]
        result = self.identified(tracks)
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, self.titles)

    def test_a_rip_that_numbered_the_pregap_1_to_11_pairs_its_first_file_with_the_pregap(self) -> None:
        # A ripper that saw 11 tracks numbered them 1 to 11. One file more
        # than the medium's tracks makes the first one the pregap.
        tracks = [vorbis(self.album, f"{n:02d}. {t}.flac", s, title=t, tracknumber=str(n),
                         musicbrainz_albumid=TAGGED)
                  for n, (t, s) in enumerate(zip(self.titles, self.seconds), start=1)]
        result = self.identified(tracks)
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, self.titles)

    def test_ten_files_against_a_pregap_and_10_tracks_are_certain_with_the_pregap_left_out(self) -> None:
        # The hidden track is usually not ripped. The pregap counts only
        # when the files number one more than the medium's tracks.
        tracks = [vorbis(self.album, f"{n:02d}. {t}.flac", s, title=t, tracknumber=str(n),
                         musicbrainz_albumid=TAGGED)
                  for n, (t, s) in enumerate(zip(WORDS[:10], self.seconds[1:]), start=1)]
        result = self.identified(tracks)
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, WORDS[:10])

    def test_eleven_files_against_10_tracks_and_no_pregap_still_do_not_fit(self) -> None:
        # Only a pregap makes room for the eleventh file. The first file's
        # title already fails against Amber, so the status alone would not
        # show an engine that takes any one extra file for a hidden track:
        # the counts have to be what fails.
        release = copy.deepcopy(self.release)
        del release["media"][0]["pregap"]
        release["media"][0]["track-count"] = 10
        tracks = [vorbis(self.album, f"{n:02d}. {t}.flac", s, title=t, tracknumber=str(n),
                         musicbrainz_albumid=TAGGED)
                  for n, (t, s) in enumerate(zip(self.titles, self.seconds))]
        result = self.identify(unit(self.album, tracks), answering(release))
        self.assertCountsDoNotFit(result)


# --- criterion 13: files with nothing about media, cut across the release -----


class UnlabelledMediaIdentify(MediaIdentifyCase):
    def two_media(self, first: int, release_id: str = TAGGED) -> dict:
        seconds = lengths(20)
        specs = [audio(t, s) for t, s in zip(WORDS, seconds)]
        return media_release(release_id, [specs[:first], specs[first:]])

    def twenty(self, release_id: str | None = TAGGED, numbered: bool = True, **extra: str) -> list[files.Track]:
        # Numbered filenames with a single space, so `10` would sort before
        # `2` if they were read as text.
        return self.flac_files([(f"{n} {t}.flac", t, s + 0.3) for n, (t, s) in enumerate(zip(WORDS, lengths(20)), start=1)],
                          release_id=release_id, numbered=numbered, **extra)

    def test_twenty_tagged_files_in_one_folder_are_certain_against_two_media_of_10(self) -> None:
        release = self.two_media(10)
        result = self.identify(unit(self.album, self.twenty()), answering(release))
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, WORDS)

    def test_the_cut_follows_the_releases_own_medium_counts_not_halves(self) -> None:
        release = self.two_media(12)
        result = self.identify(unit(self.album, self.twenty()), answering(release))
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, WORDS)

    def test_twenty_searched_files_with_no_track_number_tags_are_auto_in_filename_order(self) -> None:
        release = self.two_media(10, mbid("a1"))
        server = Server(search=search_json(release), releases=(release,))
        result = self.identify(unit(self.album, self.twenty(release_id=None, numbered=False)), server)
        self.assertEqual((result.status, result.reason), ("auto", None))
        self.assertEqual(result.candidates[0].release_id, mbid("a1"))
        self.assertPairedByTitle(result, WORDS)

    def test_nineteen_files_do_not_fit_two_media_of_10(self) -> None:
        release = self.two_media(10)
        tracks = self.twenty()[:19]
        result = self.identify(unit(self.album, tracks), answering(release))
        self.assertCountsDoNotFit(result)

    def test_files_that_all_say_disc_1_are_not_spread_across_two_media(self) -> None:
        # A disc number tag is something about media, so the files are one
        # medium of 20 and the release is two of 10.
        release = self.two_media(10)
        tracks = self.twenty(discnumber="1")
        result = self.identify(unit(self.album, tracks), answering(release))
        self.assertCountsDoNotFit(result)


# --- criterion 14: video tracks and the media they empty ---------------------


class VideoIdentify(MediaIdentifyCase):
    def setUp(self) -> None:
        super().setUp()
        self.seconds = lengths(10)
        self.cd = [audio(t, s) for t, s in zip(WORDS[:10], self.seconds)]
        self.dvd = [video(t, 240) for t in DVD]

    def cd_files(self, release_id: str | None = TAGGED) -> list[files.Track]:
        return self.flac_files([(f"{n:02d}. {t}.flac", t, s) for n, (t, s) in enumerate(zip(WORDS, self.seconds), start=1)],
                          release_id=release_id)

    def test_a_cd_plus_dvd_release_is_certain_for_the_cds_ten_files(self) -> None:
        release = media_release(TAGGED, [self.cd, self.dvd], formats=["CD", "DVD-Video"])
        result = self.identify(unit(self.album, self.cd_files()), answering(release))
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, WORDS[:10])

    def test_a_dvd_listed_before_the_cd_is_certain_all_the_same(self) -> None:
        release = media_release(TAGGED, [self.dvd, self.cd], formats=["DVD-Video", "CD"])
        result = self.identify(unit(self.album, self.cd_files()), answering(release))
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, WORDS[:10])

    def test_a_searched_cd_plus_dvd_release_is_auto_for_the_cds_ten_files(self) -> None:
        # The search lists both media, 10 and 3, against the files' one.
        release = media_release(mbid("a1"), [self.cd, self.dvd], formats=["CD", "DVD-Video"])
        server = Server(search=search_json(release), releases=(release,))
        result = self.identify(unit(self.album, self.cd_files(release_id=None)), server)
        self.assertEqual((result.status, result.reason), ("auto", None))
        self.assertEqual(result.candidates[0].release_id, mbid("a1"))
        self.assertPairedByTitle(result, WORDS[:10])

    def test_a_video_track_inside_a_medium_is_skipped_and_the_audio_either_side_pairs_in_order(self) -> None:
        mixed = [*self.cd[:4], video("Music Video", 240), *self.cd[4:9]]
        release = media_release(TAGGED, [mixed])
        tracks = self.flac_files([(f"{n:02d}. {t}.flac", t, s) for n, (t, s) in
                             enumerate(zip(WORDS[:9], self.seconds[:9]), start=1)], release_id=TAGGED)
        result = self.identify(unit(self.album, tracks), answering(release))
        self.assertEqual((result.status, result.reason), ("certain", None))
        self.assertPairedByTitle(result, WORDS[:9])

    def test_a_dvd_whose_tracks_are_audio_still_counts_as_a_medium(self) -> None:
        # Only the video mark drops a track. A DVD-Audio disc is music, so
        # dropping media by format would wrongly fit these ten files.
        audio_dvd = [audio(t, 240) for t in DVD]
        release = media_release(TAGGED, [self.cd, audio_dvd], formats=["CD", "DVD-Audio"])
        server = answering(release)
        result = self.identify(unit(self.album, self.cd_files()), server)
        self.assertCountsDoNotFit(result)


# --- the plans: where each file goes and what number it carries --------------

RIP = "C/The Cure/Disintegration [rip]"
DESTINATION = PurePosixPath("C/Cure, The/(2010) Disintegration")


def rip(root: Path, tracks: list[tuple[str, str, tuple[int, int] | None, tuple[int, int] | None]],
        ext: str = "flac") -> Path:
    """Real files in one folder, from `(file stem, title, (track, total), (disc, total))`.

    `None` for the track or disc pair leaves that tag off. Returns the album folder.
    """
    album = root / RIP
    album.mkdir(parents=True)
    for stem, title, track, disc in tracks:
        path = builders.copy_fixture(album, ext, stem)
        fields = {"title": [title], "artist": ["The Cure"], "album": ["Disintegration"], "date": ["1989"]}
        builders.write_tags(path, builders.picard_tags(ext, fields, track=track, disc=disc), v2_version=4)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", album / "cover.jpg")
    return album


def mark_video(medium: dict, positions: list[int] | None = None) -> None:
    for track in medium["tracks"]:
        if positions is None or track["position"] in positions:
            track["recording"]["video"] = True


class MediaPlanCase(_Planning):
    def planned(self, album_tracks, release: dict, ext: str = "flac") -> dict[str, tuple[str, dict]]:
        """`{source file name: (destination under the album folder, target tags)}`, with no problems."""
        root = self.library()
        album = rip(root, album_tracks, ext)
        plan = self.plan(self.unit(root, album), release, status="certain")
        self.assertEqual(list(plan.problems), [])
        self.assertEqual(PurePosixPath(str(plan.destination)), DESTINATION)
        return {PurePosixPath(str(f.source)).name:
                (PurePosixPath(str(f.destination)).relative_to(DESTINATION).as_posix(), f.target)
                for f in plan.files}


class PregapPlan(MediaPlanCase):
    def release(self) -> dict:
        release = _release(WORDS[:10])
        medium = release["media"][0]
        medium["pregap"] = {
            "id": "2b0c0d0e-0000-4000-8000-000100000000", "position": 0, "number": "0", "title": HIDDEN,
            "length": 95000, "artist-credit": copy.deepcopy(CURE),
            "recording": {"id": "3c0d0e0f-0000-4000-8000-000100000000", "length": 95000},
        }
        # MusicBrainz counts the pregap in `track-count`; the total written
        # is the 10 in `tracks`.
        medium["track-count"] = 11
        return release

    def test_the_pregap_file_is_planned_as_00_track_0_of_10_and_the_next_as_01(self) -> None:
        cases = {
            "flac": (("tracknumber", "tracktotal", "discnumber", "disctotal"), (["0"], ["10"], ["1"], ["1"]),
                     (["1"], ["10"])),
            "mp3": (("TRCK", "TPOS"), (["0/10"], ["1/1"]), (["1/10"],)),
        }
        for ext, (keys, pregap_values, next_values) in cases.items():
            with self.subTest(ext=ext):
                tracks = [("00 hidden", HIDDEN.lower(), (0, 10), (1, 1))]
                tracks += [(f"{n:02d} {t.lower()}", t.lower(), (n, 10), (1, 1)) for n, t in enumerate(WORDS[:10], start=1)]
                planned = self.planned(tracks, self.release(), ext)

                destination, target = planned[f"00 hidden.{ext}"]
                self.assertEqual(destination, f"00. {HIDDEN}.{ext}")
                self.assertEqual(tuple(target.get(k) for k in keys), pregap_values)

                destination, target = planned[f"01 amber.{ext}"]
                self.assertEqual(destination, f"01. Amber.{ext}")
                self.assertEqual(tuple(target.get(k) for k in keys[:len(next_values)]), next_values)

                destination, _ = planned[f"10 juniper.{ext}"]
                self.assertEqual(destination, f"10. Juniper.{ext}")


    def test_a_rip_without_the_pregap_is_planned_01_to_10_of_10(self) -> None:
        tracks = [(f"{n:02d} {t.lower()}", t.lower(), (n, 10), (1, 1)) for n, t in enumerate(WORDS[:10], start=1)]
        planned = self.planned(tracks, self.release())

        expected = {f"{n:02d} {t.lower()}.flac": f"{n:02d}. {t}.flac" for n, t in enumerate(WORDS[:10], start=1)}
        self.assertEqual({source: destination for source, (destination, _) in planned.items()}, expected)
        for n, t in enumerate(WORDS[:10], start=1):
            with self.subTest(track=n):
                _, target = planned[f"{n:02d} {t.lower()}.flac"]
                self.assertEqual((target["tracknumber"], target["tracktotal"]), ([str(n)], ["10"]))


class UnlabelledMediaPlan(MediaPlanCase):
    def test_twenty_files_with_no_disc_tags_are_planned_as_cd1_and_cd2_of_10_each(self) -> None:
        tracks = [(f"{n:02d} {t.lower()}", t.lower(), (n, 20), None) for n, t in enumerate(WORDS, start=1)]
        planned = self.planned(tracks, _release(WORDS[:10], WORDS[10:]))

        expected = {f"{n:02d} {t.lower()}.flac": f"CD{1 + (n - 1) // 10}/{(n - 1) % 10 + 1:02d}. {t}.flac"
                    for n, t in enumerate(WORDS, start=1)}
        self.assertEqual({source: destination for source, (destination, _) in planned.items()}, expected)

        _, target = planned["11 kestrel.flac"]
        self.assertEqual((target["tracknumber"], target["tracktotal"], target["discnumber"], target["disctotal"]),
                         (["1"], ["10"], ["2"], ["2"]))
        _, target = planned["10 juniper.flac"]
        self.assertEqual((target["tracknumber"], target["discnumber"]), (["10"], ["1"]))


class VideoPlan(MediaPlanCase):
    def cd_rip(self) -> list:
        return [(f"{n:02d} {t.lower()}", t.lower(), (n, 10), (1, 1)) for n, t in enumerate(WORDS[:10], start=1)]

    def assertOneDisc(self, planned: dict) -> None:
        expected = {f"{n:02d} {t.lower()}.flac": f"{n:02d}. {t}.flac" for n, t in enumerate(WORDS[:10], start=1)}
        self.assertEqual({source: destination for source, (destination, _) in planned.items()}, expected)
        for source, (_, target) in planned.items():
            with self.subTest(source=source):
                self.assertEqual((target["discnumber"], target["disctotal"], target["tracktotal"]),
                                 (["1"], ["1"], ["10"]))

    def test_a_cd_plus_dvd_release_plans_the_cd_as_a_single_disc_with_no_cd_folder(self) -> None:
        release = _release(WORDS[:10], DVD)
        release["media"][1]["format"] = "DVD-Video"
        mark_video(release["media"][1])
        self.assertOneDisc(self.planned(self.cd_rip(), release))

    def test_a_dvd_listed_before_the_cd_plans_the_same_single_disc(self) -> None:
        release = _release(DVD, WORDS[:10])
        release["media"][0]["format"] = "DVD-Video"
        mark_video(release["media"][0])
        planned = self.planned(self.cd_rip(), release)
        self.assertOneDisc(planned)
        # Tagged from the CD, not from the DVD it was listed after.
        _, target = planned["01 amber.flac"]
        self.assertEqual(target["media"], ["CD"])

    def test_a_video_track_inside_a_medium_takes_no_number_and_the_total_is_the_audio_count(self) -> None:
        mixed = [*WORDS[:4], "Music Video", *WORDS[4:9]]
        release = _release(mixed)
        mark_video(release["media"][0], positions=[5])
        tracks = [(f"{n:02d} {t.lower()}", t.lower(), (n, 9), (1, 1)) for n, t in enumerate(WORDS[:9], start=1)]
        planned = self.planned(tracks, release)

        expected = {f"{n:02d} {t.lower()}.flac": f"{n:02d}. {t}.flac" for n, t in enumerate(WORDS[:9], start=1)}
        self.assertEqual({source: destination for source, (destination, _) in planned.items()}, expected)
        _, target = planned["05 ember.flac"]
        self.assertEqual((target["tracknumber"], target["title"]), (["5"], ["Ember"]))
        # The total is the nine audio tracks, not the ten MusicBrainz lists,
        # as the numbering that skips the video already says.
        for source, (_, target) in planned.items():
            with self.subTest(source=source):
                self.assertEqual(target["tracktotal"], ["9"])


if __name__ == "__main__":
    import unittest

    unittest.main()
