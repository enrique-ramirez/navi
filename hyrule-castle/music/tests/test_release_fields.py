"""Release-specific fields: what belongs to one edition and nowhere else.

A file tagged for release X and matched to
release Y must end up with Y's label, catalogue number, barcode, ASIN,
country, media and release-level IDs, and with none of X's where Y has no
value, because X's barcode on a Y file is wrong rather than merely stale.
Everything outside that set is left alone, however release-like it looks.

As in `test_map_tags`, every expected value is read back from a real file
tagged the way Picard does, so these tests do not depend on how `Track.tags`
renders an MP4 freeform atom.
"""

from __future__ import annotations

import itertools
import tempfile
import unittest

from musiclib import files, mapping
from tests import builders

FORMATS = ("mp3", "flac", "ogg", "m4a")

#: Release X, the edition the file was tagged for. Every value differs from
#: `builders.mb_release()`, which plays release Y.
X = {
    "label": ["Elektra"],
    "catalognumber": ["9 60855-2"],
    "barcode": ["075596085525"],
    "asin": ["B000002H9Q"],
    "releasecountry": ["US"],
    "media": ["Cassette"],
    "release id": ["5e0f1011-0000-4000-8000-0000000000c1"],
    "release group id": ["5e0f1011-0000-4000-8000-0000000000c2"],
    "album artist id": ["5e0f1011-0000-4000-8000-0000000000c3"],
}

#: Y's values for disc 1 track 1.
Y = {
    "label": ["Fiction Records"],
    "catalognumber": ["FIXH 14"],
    "asin": ["B003FMTHVS"],
    "releasecountry": ["GB"],
    "media": ["CD"],
    "release id": [builders.RELEASE_ID],
    "release group id": [builders.RELEASE_GROUP_ID],
    "album artist id": [builders.CURE_ID],
}

#: The "not release-specific" list, plus the release-level names
#: Picard does not use, which the spec's *Not doing* keeps as they are. The
#: Vorbis `upc` holds X's barcode on purpose: a plan that removes whatever
#: carries the old barcode shows here.
OUTSIDE = {
    "mp3": {
        "TXXX:MusicBrainz Album Status": "official",
        "TXXX:MusicBrainz Album Type": "album",
        "TXXX:SCRIPT": "Latn",
        "TLAN": "eng",
        "TXXX:MusicBrainz Disc Id": "Wn8eRBtfLDfM0qjYPdxrz.Zjs_U-",
        "TSRC": "USEE10001992",
        "TXXX:Acoustid Id": "6f0a1112-0000-4000-8000-0000000000d1",
        "TXXX:UPC": "075596085525",
        "TXXX:DISCOGS_RELEASE_ID": "1234567",
    },
    "vorbis": {
        "RELEASESTATUS": "official",
        "RELEASETYPE": "album",
        "SCRIPT": "Latn",
        "LANGUAGE": "eng",
        "MUSICBRAINZ_DISCID": "Wn8eRBtfLDfM0qjYPdxrz.Zjs_U-",
        "ISRC": "USEE10001992",
        "ACOUSTID_ID": "6f0a1112-0000-4000-8000-0000000000d1",
        "ORGANIZATION": "Elektra",
        "UPC": "075596085525",
        "LABELNO": "9 60855-2",
        "CATALOG #": "9 60855-2",
        "DISCOGS_RELEASE_ID": "1234567",
    },
    "m4a": {
        "----:com.apple.iTunes:MusicBrainz Album Status": "official",
        "----:com.apple.iTunes:MusicBrainz Album Type": "album",
        "----:com.apple.iTunes:SCRIPT": "Latn",
        "----:com.apple.iTunes:LANGUAGE": "eng",
        "----:com.apple.iTunes:MusicBrainz Disc Id": "Wn8eRBtfLDfM0qjYPdxrz.Zjs_U-",
        "----:com.apple.iTunes:ISRC": "USEE10001992",
        "----:com.apple.iTunes:Acoustid Id": "6f0a1112-0000-4000-8000-0000000000d1",
        "----:com.apple.iTunes:UPC": "075596085525",
    },
}
OUTSIDE["flac"] = OUTSIDE["ogg"] = OUTSIDE["vorbis"]

_TMP: tempfile.TemporaryDirectory | None = None
_NAMES = itertools.count()


def setUpModule():
    global _TMP
    _TMP = tempfile.TemporaryDirectory()


def tearDownModule():
    _TMP.cleanup()


def on_file(ext: str, tags: dict | None = None) -> files.Track:
    """A fresh copy of the `ext` fixture carrying `tags` (real keys), as the engine reads it."""
    path = builders.copy_fixture(_TMP.name, ext, f"t{next(_NAMES)}")
    if tags:
        builders.write_tags(path, tags, v2_version=4)
    return files.read(path)


def tagged_for_x(ext: str, extra: dict | None = None) -> files.Track:
    return on_file(ext, {**builders.picard_tags(ext, X, track=(1, 3), disc=(1, 3)), **(extra or {})})


def key(ext: str, field: str) -> str:
    return builders.picard_key(ext, field)


def plan(track, release):
    return mapping.plan_tags(track, release, 1, 1, ["post-punk"], disc_folder=None)


def without_medium_format(release: dict) -> dict:
    release["media"][0]["format"] = None
    return release


class ReleaseSpecific(unittest.TestCase):
    def assertRemoved(self, ext, track, result, fields):
        """Exactly `fields` left the file, each with a removal that names a rule."""
        keys = {key(ext, f) for f in fields}
        self.assertEqual(set(track.tags) - set(result.target), keys)
        for k in keys:
            records = [r for r in result.removals if r.key == k]
            self.assertEqual(len(records), 1, f"removal records for {k}")
            self.assertIsInstance(records[0].rule, str)
            self.assertTrue(records[0].rule.strip())

    def test_matched_to_a_release_without_a_barcode_the_file_loses_xs_and_takes_ys_other_values(self):
        for ext in FORMATS:
            with self.subTest(ext):
                track = tagged_for_x(ext)
                result = plan(track, builders.mb_release(barcode=""))
                self.assertRemoved(ext, track, result, ["barcode"])
                expected = on_file(ext, builders.picard_tags(ext, Y)).tags
                for field in Y:
                    self.assertEqual(result.target[key(ext, field)], expected[key(ext, field)], field)

    def test_every_release_specific_field_the_release_lacks_is_removed_and_recorded(self):
        # MusicBrainz gives a missing value as "" or null, and a release with
        # no label as an empty label-info list. A label with no catalogue
        # number is its own shape: the label stays and only the number goes.
        fiction = builders.mb_release()["label-info"][0]["label"]
        cases = [
            ("no barcode", lambda r: {**r, "barcode": None}, ["barcode"]),
            ("no ASIN", lambda r: {**r, "asin": None}, ["asin"]),
            ("empty ASIN", lambda r: {**r, "asin": ""}, ["asin"]),
            ("no country", lambda r: {**r, "country": None}, ["releasecountry"]),
            ("empty country", lambda r: {**r, "country": ""}, ["releasecountry"]),
            ("no label", lambda r: {**r, "label-info": []}, ["label", "catalognumber"]),
            ("label without a number",
             lambda r: {**r, "label-info": [{"catalog-number": None, "label": fiction}]},
             ["catalognumber"]),
            ("no medium format", without_medium_format, ["media"]),
        ]
        for name, change, gone in cases:
            for ext in FORMATS:
                with self.subTest(case=name, ext=ext):
                    track = tagged_for_x(ext)
                    result = plan(track, change(builders.mb_release()))
                    self.assertRemoved(ext, track, result, gone)

    def test_fields_outside_the_release_specific_set_stay_as_they_were(self):
        # Y has none of the six, so a plan that clears release-like fields
        # wholesale has every chance to take these with them.
        bare = without_medium_format(builders.mb_release(
            barcode=None, asin=None, country=None, **{"label-info": []}))
        for ext in FORMATS:
            with self.subTest(ext):
                track = tagged_for_x(ext, OUTSIDE[ext])
                result = plan(track, bare)
                outside = {k: v for k, v in track.tags.items()
                           if k.lower() in {x.lower() for x in OUTSIDE[ext]}}
                self.assertEqual(len(outside), len(OUTSIDE[ext]))
                for k, v in outside.items():
                    self.assertEqual(result.target.get(k), v, k)
                self.assertEqual([r.key for r in result.removals if r.key in outside], [])


if __name__ == "__main__":
    unittest.main()
