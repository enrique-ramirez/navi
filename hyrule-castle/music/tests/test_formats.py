"""One definition of a track, in every format the library holds.

A track is an audio file in the album folder or in a direct subfolder of it:
`.mp3`, `.flac`, `.ogg`, `.m4a`, `.mp4` or `.wma`, whatever the case of the
extension, and never a `._` sidecar. `units` finds an album's tracks, `check`
judges them and `plan` moves and retags them. When the three disagree, a plan
comes out clean and then every write of it fails, or a file `check` reports
is one the plan never touches.

An `.mp4` is audio or a video. Audio is handled exactly like `.m4a`. A video
goes to extras (docs *What an album folder may contain*), and only its video
track says so: a music video carries an audio track too, and reads as a good
MP4 audio file. A `.wma` is tagged under Picard's ASF names and carries one
`WM/Picture` front cover.

The planning half (fake MusicBrainz, fake Cover Art Archive, `_rip`) is
`test_check`'s, as `test_plan` uses it.
"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path, PurePosixPath

from mutagen.mp4 import MP4

from musiclib import check
from tests import builders
from tests.test_check import _Planning, _release, _rip, _write_album

#: Where every album here is planned to: The Cure's *Disintegration*, the
#: 2010 edition `_release` stands for.
DESTINATION = "C/Cure, The/(2010) Disintegration"


def rip(root: Path, ext: str, titles: list[str], where: str = "C/The Cure/Disintegration [rip]") -> Path:
    """`test_check._rip` for the kinds it has no sample for: one medium of `ext` files.

    Loose names, lower-case titles, dated 1989, tagged under Picard's names
    for the format, and a `cover.jpg`. Returns the album folder.
    """
    base = root / where
    base.mkdir(parents=True)
    for number, title in enumerate(titles, start=1):
        path = builders.copy_fixture(base, ext, f"{number:02d} {title.lower()}")
        fields = {"title": [title.lower()], "artist": ["The Cure"], "album": ["Disintegration"],
                  "date": ["1989"]}
        builders.write_tags(path, builders.picard_tags(ext, fields, track=(number, len(titles)),
                                                       disc=(1, 1)))
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


def put(album: Path, rel: str, source: Path) -> Path:
    """`source` copied to `album/rel`, folders and all."""
    path = album / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, path)
    return path


class WhichFilesAreTracks(_Planning):
    def test_units_check_and_plan_take_the_same_files_as_tracks(self):
        # One of each way a file can be a track and one of each way it can
        # look like one and not be.
        root = self.library()
        album = root / "C/The Cure/Disintegration [rip]"
        tracks = {
            "01 plainsong.mp3": builders.FIXTURES / "tone.mp3",
            "02 pictures of you.flac": builders.FIXTURES / "tone.flac",
            # A direct subfolder is a disc folder, whatever it is called, and
            # the extension counts whatever its case.
            "Bonus/03 closedown.MP4": builders.FIXTURES / "tone.m4a",
            "04 lovesong.wma": builders.FIXTURES / "tone.wma",
        }
        for rel, source in tracks.items():
            put(album, rel, source)
        # Real, readable audio two folders down: taken at any depth, it would
        # be a track here and another file there.
        put(album, "Scans/extra/05 last dance.flac", builders.FIXTURES / "tone.flac")
        put(album, "Making of.mp4", builders.VIDEO_MP4)
        # A sidecar for one of the two new extensions: read as audio, it is
        # unreadable, which would stop the album being planned at all.
        (album / "._04 lovesong.wma").write_bytes(b"\x00\x05\x16\x07\x00\x02\x00\x00Mac OS X        ")
        shutil.copyfile(builders.FIXTURES / "cover.jpg", album / "cover.jpg")

        unit = self.unit(root, album)
        state = check.read_album(album, root)
        found = {
            "units": {Path(t.path).relative_to(album).as_posix() for t in unit.tracks},
            "check": {f"{t.disc_dir}/{t.filename}" if t.disc_dir else t.filename for t in state.tracks},
        }
        self.assertEqual(found, {"units": set(tracks), "check": set(tracks)})
        self.assertEqual((unit.unreadable, state.unreadable), ([], ()))

        plan = self.plan(unit, _release(["Plainsong", "Pictures of You", "Closedown", "Lovesong"]))

        planned = {PurePosixPath(f.source).relative_to(plan.source).as_posix() for f in plan.files}
        self.assertEqual(planned, set(tracks))
        # The deep file is not a track, and it is not lost either: the plan
        # says what happens to it.
        others = {PurePosixPath(rel).relative_to(plan.source).as_posix()
                  for rel in [*plan.deletions, *plan.extras, *plan.kept]}
        self.assertIn("Scans/extra/05 last dance.flac", others)


class AnMp4Video(_Planning):
    def test_is_an_extra_to_units_check_and_plan_though_it_carries_audio(self):
        # The video is named like a track and sits beside the tracks. Taken
        # as one, it is a third file for a two-track release.
        for name in ("Making of.mp4", "PROMO.MP4"):
            with self.subTest(name):
                root = self.library()
                album = _rip(root, ["Plainsong", "Pictures of You"])
                put(album, name, builders.VIDEO_MP4)

                unit = self.unit(root, album)
                self.assertNotIn(name, [Path(t.path).name for t in unit.tracks])
                self.assertIn(name, unit.others)

                rules = {v.rule for v in check.check(root) if name in v.detail}
                self.assertEqual(rules, {"extras"})

                plan = self.plan(unit, _release(["Plainsong", "Pictures of You"]), status="auto")
                self.assertEqual(list(plan.problems), [])
                self.assertEqual([PurePosixPath(rel).name for rel in plan.extras], [name])
                self.assertNotIn(name, [PurePosixPath(f.source).name for f in plan.files])


class AnMp4AudioAlbum(_Planning):
    def test_is_planned_and_written_like_m4a_and_its_video_goes_to_extras(self):
        root = self.library()
        album = rip(root, "mp4", ["Plainsong", "Pictures of You"])
        put(album, "Making of.mp4", builders.VIDEO_MP4)
        extras = self.tmp / "extras"

        plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]), status="auto")

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(sorted(f.destination for f in plan.files),
                         [f"{DESTINATION}/01. Plainsong.mp4", f"{DESTINATION}/02. Pictures of You.mp4"])

        _write_album(plan, extras)

        for number, title in ((1, "Plainsong"), (2, "Pictures of You")):
            with self.subTest(title):
                audio = MP4(root / DESTINATION / f"{number:02d}. {title}.mp4")
                self.assertEqual(audio["\xa9nam"], [title])
                self.assertEqual(audio["trkn"], [(number, 2)])
                self.assertEqual([bytes(c) for c in audio["covr"]], [plan.embedded])
        self.assertEqual((extras / DESTINATION / "Making of.mp4").read_bytes(), builders.VIDEO_MP4.read_bytes())
        self.assertFalse((root / DESTINATION / "Making of.mp4").exists())
        self.assertEqual(check.check_album(check.read_album(root / DESTINATION, root)), [])


class AWmaAlbum(_Planning):
    def test_is_planned_and_written_under_picards_asf_names_with_one_front_cover(self):
        # Which name each field takes is `test_map_tags`'s to
        # prove. This is the whole path: the plan is clean, the write
        # verifies, the names land on disk, and `check` reads them back.
        root = self.library()
        album = rip(root, "wma", ["Plainsong", "Pictures of You"])
        extras = self.tmp / "extras"

        plan = self.plan(self.unit(root, album), _release(["Plainsong", "Pictures of You"]), status="auto")

        self.assertEqual(list(plan.problems), [])
        self.assertEqual(sorted(f.destination for f in plan.files),
                         [f"{DESTINATION}/01. Plainsong.wma", f"{DESTINATION}/02. Pictures of You.wma"])

        _write_album(plan, extras)

        for number, title in ((1, "Plainsong"), (2, "Pictures of You")):
            with self.subTest(title):
                path = root / DESTINATION / f"{number:02d}. {title}.wma"
                tags = builders.read_tags(path)
                on_disk = {key: [str(v) for v in tags.get(key, [])] for key in (
                    "Title", "Author", "WM/AlbumTitle", "WM/AlbumArtist", "WM/Year",
                    "WM/TrackNumber", "WM/PartOfSet", "MusicBrainz/Album Id")}
                self.assertEqual(on_disk, {
                    "Title": [title], "Author": ["The Cure"], "WM/AlbumTitle": ["Disintegration"],
                    "WM/AlbumArtist": ["The Cure"], "WM/Year": ["2010-05-24"],
                    "WM/TrackNumber": [str(number)], "WM/PartOfSet": ["1/1"],
                    "MusicBrainz/Album Id": [builders.RELEASE_ID],
                })
                self.assertEqual(builders.asf_pictures(path), [(3, "image/jpeg", plan.embedded)])
        self.assertEqual(check.check_album(check.read_album(root / DESTINATION, root)), [])


if __name__ == "__main__":
    unittest.main()
