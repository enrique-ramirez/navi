"""The review page: what the owner reads, edits and exports for a job.

`review.render` takes `plan.json` and returns the page. The page is read
here as HTML, never run: everything the page promises is rendered in
Python, and the script only adds editing and the export. The click on the
export button is checked by hand.

The page is found through a few data attributes rather than its markup, so a
redesign keeps these tests:

- `data-album="<key>"` and `data-state="held"|"auto"` on each album's section
- `data-artist="<folder>"` on the group holding a folder's held albums
- `data-file="<source rel>"` on each track, holding its `data-tag="<real key>"`
  rows and a `data-path` row
- `data-residue` on each residue item
- `data-deletion`, `data-extra` and `data-kept`, each set to the file's source
  rel, on the row for a file deleted, sent to extras or moved with the
  album; `data-image="<name>"` on each image the plan writes
- `data-field` and `data-position` on each input
- the decision radios by value: `accept`, `repoint`, `skip`, a candidate's
  MBID, and `video game music` / `soundtrack` / `neither`
- `data-repoint` on the box a release URL or MBID is pasted into
- `id="plan"`, `id="decisions-skeleton"` and `id="export"`
"""

from __future__ import annotations

import copy
import importlib
import json
import re
import unittest
from html.parser import HTMLParser

JOB = "2b-7"

AUTO = "A/Aphex Twin/Selected Ambient Works 85-92 [rip]"
DISINTEGRATION = "C/The Cure/Disintegration [rip]"
OCARINA = "K/Koji Kondo/Ocarina of Time [rip]"
MEZZANINE = "M/Massive Attack/Mezzanine"
# The Cure filed under T as well as C. Grouped by artist folder, the two sit
# together; in source order, Ocarina falls between them.
WISH = "T/The Cure/Wish [rip]"
WISH_ID = "7b6a5f4e-3d2c-4b1a-8f9e-0d1c2b3a4f5e"

AUTO_ID = "5a1b4a8e-4d1f-4b5e-9c2a-1f0e8b3c7d21"
DIS_ID = "0f6d2c1e-8b7a-4e3c-9d5f-2a1b3c4d5e6f"
DIS_OTHER_ID = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b"
OCARINA_ID = "3c2b1a0f-9e8d-4c7b-a6f5-4e3d2c1b0a9f"

KONDO_ID = "b4f0f6a7-2c3d-4e5f-8a9b-0c1d2e3f4a5b"


def thumbnail(mbid: str) -> str:
    return f"https://coverartarchive.org/release/{mbid}/front-250"


def candidate(mbid: str, title: str, artist: str, date: str) -> dict:
    return {
        "release_id": mbid, "title": title, "artist": artist, "date": date,
        "country": "GB", "format": "CD", "track_counts": [2], "matches_counts": True,
        "duration_diff": 1.5, "thumbnail": thumbnail(mbid),
    }


def entry(source: str, state: str, status: str, **rest) -> dict:
    doc = {
        "source": source, "state": state, "status": status, "holds": [],
        "decision": None, "release_id": None, "destination": None, "composer": None,
        "game_choice": False, "candidates": [], "files": [], "fields": {}, "images": {},
        "residue": [], "deletions": [], "extras": [], "kept": [], "changes": [],
        "inputs": None, "plan_digest": None, "game": None, "owner_edits": {},
    }
    doc.update(rest)
    return doc


def plan_doc() -> dict:
    """A fresh plan each call, so no test reads another's changes."""
    dis_file_1 = f"{DISINTEGRATION}/01 plainsong.flac"
    dis_file_2 = f"{DISINTEGRATION}/02 pictures of you.flac"
    ocarina_file = f"{OCARINA}/01 Title Theme.mp3"
    auto_file = f"{AUTO}/01 Xtal.flac"
    return {
        "job": JOB,
        "root": "/srv/music/library",
        "albums": [
            entry(
                AUTO, "auto", "certain",
                release_id=AUTO_ID,
                destination="A/Aphex Twin/(1992) Selected Ambient Works 85-92",
                candidates=[candidate(AUTO_ID, "Selected Ambient Works 85-92", "Aphex Twin", "1992")],
                files=[{
                    "source": auto_file,
                    "destination": "A/Aphex Twin/(1992) Selected Ambient Works 85-92/01 Xtal.flac",
                    "position": "1-1",
                    "before": {"title": ["xtal"]},
                    "after": {"title": ["Xtal"], "musicbrainz_albumid": [AUTO_ID]},
                }],
                fields={"1-1": {"title": ["Xtal"], "album": ["Selected Ambient Works 85-92"],
                                "date": ["1992-11-09"]}},
                images={"cover.jpg": {"sha256": "a" * 64, "length": 51234}},
                deletions=[f"{AUTO}/Thumbs.db"],
                kept=[f"{AUTO}/rip.log"],
                changes=["title: xtal -> Xtal"],
            ),
            entry(
                DISINTEGRATION, "held", "review",
                # Two reasons: the page lists every one, never only the first.
                holds=[
                    {"kind": "status", "detail": "review: two releases match equally"},
                    {"kind": "validation", "detail": "1-2: date is before the original date"},
                ],
                release_id=DIS_ID,
                destination="C/Cure, The/(1989) Disintegration",
                candidates=[
                    candidate(DIS_ID, "Disintegration", "The Cure", "1989-05-02"),
                    candidate(DIS_OTHER_ID, "Disintegration", "The Cure", "2010-05-24"),
                ],
                files=[
                    {
                        "source": dis_file_1,
                        "destination": "C/Cure, The/(1989) Disintegration/01 Plainsong.flac",
                        "position": "1-1",
                        # artist is the same both sides; title, date and comment
                        # change, and musicbrainz_albumid is new.
                        "before": {"title": ["plainsong"], "artist": ["The Cure"],
                                   "date": ["1989"], "comment": ["ripped by EAC"]},
                        "after": {"title": ["Plainsong"], "artist": ["The Cure"],
                                  "date": ["1989-05-02"], "musicbrainz_albumid": [DIS_ID]},
                    },
                    {
                        "source": dis_file_2,
                        "destination": "C/Cure, The/(1989) Disintegration/02 Pictures of You.flac",
                        "position": "1-2",
                        "before": {"title": ["pictures of you"], "encodedby": ["LAME"]},
                        "after": {"title": ["Pictures of You"], "musicbrainz_albumid": [DIS_ID]},
                    },
                ],
                fields={
                    "1-1": {"title": ["Plainsong"], "artist": ["The Cure"],
                            "album": ["Disintegration"], "date": ["1989-05-02"]},
                    # Two values in one field. How the page shows a list is
                    # open (see the input test); that both values are there is not.
                    "1-2": {"title": ["Pictures of You"], "artist": ["The Cure", "Robert Smith"],
                            "album": ["Disintegration"], "date": ["1989-05-02"]},
                },
                residue=[
                    {"file": dis_file_1, "key": "comment", "value": "ripped by EAC", "rule": "ripper comment"},
                    {"file": dis_file_2, "key": "encodedby", "value": None, "rule": "encoder"},
                ],
                # The rip's cover.jpg is deleted because the album moves, and
                # cover.jpg under images is what the destination gets.
                images={"cover.jpg": {"sha256": "b" * 64, "length": 88123},
                        "back.jpg": {"sha256": "c" * 64, "length": 70211}},
                deletions=[f"{DISINTEGRATION}/.DS_Store", f"{DISINTEGRATION}/cover.jpg"],
                extras=[f"{DISINTEGRATION}/Making of.mkv"],
                # One in a subfolder: only the part above the album changes.
                kept=[f"{DISINTEGRATION}/rip.log", f"{DISINTEGRATION}/scans/booklet 01.png"],
                changes=["title: plainsong -> Plainsong"],
                # An edit from the memory, laid over the plan: what an
                # accept of this album carries back.
                inputs={"release_id": DIS_ID, "chosen": False, "status": "review",
                        "owner_input": {"composers": {}},
                        "edits": {"1-1": {"date": ["1989-05-02"]}}},
                owner_edits={"1-1": {"date": ["1989-05-02"]}},
            ),
            entry(
                OCARINA, "held", "review",
                holds=[{"kind": "status", "detail": "review: soundtrack choice"}],
                release_id=OCARINA_ID,
                # Planned where it already is: no path changes.
                destination=OCARINA,
                composer=KONDO_ID,
                game_choice=True,
                candidates=[candidate(OCARINA_ID, "Zelda no Densetsu: Toki no Ocarina", "Koji Kondo", "1998-12-18")],
                files=[{
                    "source": ocarina_file,
                    "destination": ocarina_file,
                    "position": "1-1",
                    "before": {"TIT2": ["時のオカリナ"], "TCON": ["Soundtrack"]},
                    "after": {"TIT2": ["Toki no Ocarina"], "TCON": ["video game music"]},
                }],
                fields={"1-1": {"title": ["Toki no Ocarina"], "genre": ["video game music"]}},
                images={"cover.jpg": {"sha256": "d" * 64, "length": 40960}},
                # Kept where it is: the album does not move.
                kept=[f"{OCARINA}/notes.txt"],
            ),
            entry(MEZZANINE, "unchanged", "certain", release_id="1d2c3b4a-5f6e-4d8c-9b0a-e1f2a3b4c5d6",
                  destination=MEZZANINE),
            entry(
                WISH, "held", "unidentified",
                # A reopened hold has no detail: only its kind says why.
                holds=[{"kind": "status", "detail": "unidentified"}, {"kind": "reopened", "detail": ""}],
            ),
        ],
    }


HELD = (DISINTEGRATION, OCARINA, WISH)


# --- reading the page ---------------------------------------------------------

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}


class Node:
    def __init__(self, tag: str, attrs: dict, parent: "Node | None") -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list["Node | str"] = []

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def walk(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.walk()

    def all(self, **attrs) -> list["Node"]:
        """Descendants carrying each attribute; a value of True means any value."""
        found = []
        for n in self.walk():
            if all(k in n.attrs and (v is True or n.attrs[k] == v) for k, v in attrs.items()):
                found.append(n)
        return found

    def tags(self, *names: str) -> list["Node"]:
        return [n for n in self.walk() if n.tag in names]

    def ancestors(self):
        n = self.parent
        while n is not None:
            yield n
            n = n.parent


class Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: ("" if v is None else v) for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        # Close back to the matching element; an end tag with none open is
        # ignored, the way a browser would.
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def render(doc: dict) -> str:
    # Imported here, so each class fails on the missing module by itself.
    review = importlib.import_module("musiclib.batch.review")
    # A copy, so a render that changes its argument cannot reach the fixture.
    return review.render(copy.deepcopy(doc)).decode("utf-8")


def parse(page: str) -> Node:
    tree = Tree()
    tree.feed(page)
    tree.close()
    return tree.root


def by_id(root: Node, id_: str) -> Node:
    found = root.all(id=id_)
    if len(found) != 1:
        raise AssertionError(f"expected one element with id {id_!r}, found {len(found)}")
    return found[0]


def albums(root: Node) -> dict[str, Node]:
    return {n.attrs["data-album"]: n for n in root.all(**{"data-album": True})}


def artist_folder(key: str) -> str:
    return key.split("/")[1]


def collapsed(node: Node) -> bool:
    return any(a.tag == "details" and "open" not in a.attrs for a in [node, *node.ancestors()])


class _Rendered(unittest.TestCase):
    doc: dict
    page: str
    root: Node

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = plan_doc()
        cls.page = render(cls.doc)
        cls.root = parse(cls.page)

    def album(self, key: str) -> Node:
        found = albums(self.root)
        self.assertIn(key, found, f"no section for {key}")
        return found[key]


# --- images and links ---------------------------------------------------------

CAA = re.compile(r"https://coverartarchive\.org/release/[0-9a-f-]{36}/front-250")
URL_ATTRS = {"src", "href", "srcset", "action", "formaction", "poster", "data", "background", "xlink:href"}


def inline(url: str) -> bool:
    url = url.strip()
    return url.startswith("#") or url.startswith("data:")


class SelfContained(_Rendered):
    def test_the_page_loads_no_script_or_stylesheet_from_anywhere(self) -> None:
        self.assertEqual([n.attrs for n in self.root.tags("script") if "src" in n.attrs], [])
        self.assertEqual([n.attrs for n in self.root.tags("link")
                          if "stylesheet" in n.attrs.get("rel", "").lower().split()], [])
        styles = " ".join(n.text() for n in self.root.tags("style"))
        self.assertNotIn("@import", styles)

    def test_cover_art_archive_thumbnails_are_the_only_urls_the_page_requests(self) -> None:
        offences = []
        for n in self.root.walk():
            for name, value in n.attrs.items():
                if name in URL_ATTRS and not (inline(value) or CAA.fullmatch(value.strip())):
                    offences.append(f"<{n.tag} {name}={value!r}>")
        css = " ".join([n.text() for n in self.root.tags("style")]
                       + [n.attrs["style"] for n in self.root.walk() if "style" in n.attrs])
        for url in re.findall(r"url\(\s*['\"]?([^'\")]*)", css):
            if not (inline(url) or CAA.fullmatch(url.strip())):
                offences.append(f"url({url})")
        self.assertEqual(offences, [])
        # Zero images would pass the loop above on nothing.
        self.assertTrue(any(CAA.fullmatch(n.attrs.get("src", "")) for n in self.root.tags("img")))

    def test_the_script_that_edits_and_exports_is_inline(self) -> None:
        # The page is opened from disk with nothing next to it, so the only
        # script it has is the one it carries.
        code = [n.text() for n in self.root.tags("script")
                if n.attrs.get("type", "text/javascript").lower() in ("", "text/javascript", "module")]
        self.assertTrue(any(c.strip() for c in code))

    def test_the_page_declares_utf8_so_tags_opened_from_disk_are_not_garbled(self) -> None:
        # A file:// page with no declared charset is decoded by the browser's
        # guess, and 時のオカリナ comes out as mojibake.
        charsets = [n.attrs.get("charset", "").lower() for n in self.root.tags("meta")]
        charsets += [m.group(1).lower() for n in self.root.tags("meta")
                     for m in [re.search(r"charset=([\w-]+)", n.attrs.get("content", ""))] if m]
        self.assertIn("utf-8", charsets)
        self.assertIn("時のオカリナ", self.album(OCARINA).text())


class Order(_Rendered):
    def test_held_albums_come_first_and_auto_albums_after_them(self) -> None:
        # The auto album sorts first by source, so plan order puts it at the top.
        listed = [(n.attrs["data-album"], n.attrs.get("data-state")) for n in self.root.all(**{"data-album": True})]
        self.assertEqual(sorted(k for k, s in listed if s == "held"), sorted(HELD))
        self.assertEqual([k for k, s in listed if s == "auto"], [AUTO])
        states = [s for _, s in listed]
        self.assertEqual(states, sorted(states, key=lambda s: s != "held"))

    def test_an_unchanged_album_is_not_listed(self) -> None:
        self.assertNotIn(MEZZANINE, albums(self.root))

    def test_held_albums_are_grouped_under_their_current_artist_folder(self) -> None:
        groups = self.root.all(**{"data-artist": True})
        names = [g.attrs["data-artist"] for g in groups]
        self.assertEqual(sorted(names), ["Koji Kondo", "The Cure"], "one group per folder")
        for key in HELD:
            owner = [a for a in self.album(key).ancestors() if "data-artist" in a.attrs]
            self.assertEqual([a.attrs["data-artist"] for a in owner], [artist_folder(key)], key)
        for g in groups:
            # The owner reads the folder name, not an attribute.
            self.assertIn(g.attrs["data-artist"], g.text())

    def test_held_albums_are_open_and_auto_albums_collapsed_and_marked(self) -> None:
        for key in HELD:
            self.assertFalse(collapsed(self.album(key)), f"{key} is held and hidden")
        section = self.album(AUTO)
        self.assertTrue(collapsed(section), "the auto album is not collapsed")
        details = next(a for a in [section, *section.ancestors()] if a.tag == "details")
        summary = [c for c in details.children if isinstance(c, Node) and c.tag == "summary"]
        self.assertEqual(len(summary), 1)
        # Seen before it is opened: the summary says nobody decides it.
        self.assertIn("without a decision", summary[0].text().lower())


class HeldAlbum(_Rendered):
    def test_every_hold_reason_is_shown(self) -> None:
        for album in plan_doc()["albums"]:
            for hold in album["holds"]:
                self.assertIn(hold["detail"], self.album(album["source"]).text(), album["source"])

    def test_every_hold_shows_its_kind_beside_its_detail(self) -> None:
        """One line per hold, naming its kind, so a `reopened` hold with no detail is never a blank line."""
        seen = 0
        for album in plan_doc()["albums"]:
            section = self.album(album["source"]) if album["state"] == "held" else None
            for hold in album["holds"]:
                room = len(hold["kind"]) + len(hold["detail"]) + 20
                lines = [n for n in section.walk()
                         if hold["kind"] in n.text() and hold["detail"] in n.text()
                         and len(n.text().strip()) <= room]
                self.assertTrue(lines, f"{album['source']}: {hold['kind']}: {hold['detail']!r}")
                seen += 1
        self.assertEqual(seen, 5)

    def test_every_candidate_is_shown_with_its_mbid_and_cover_art_archive_thumbnail(self) -> None:
        for album in plan_doc()["albums"]:
            if album["state"] != "held":
                continue
            section = self.album(album["source"])
            # Text, not a radio's value: the owner compares it with MusicBrainz by eye.
            seen = section.text()
            srcs = [n.attrs.get("src") for n in section.tags("img")]
            for c in album["candidates"]:
                self.assertIn(c["release_id"], seen)
                self.assertIn(thumbnail(c["release_id"]), srcs)

    def test_every_changed_tag_has_its_before_then_after(self) -> None:
        checked = 0
        for album in plan_doc()["albums"]:
            if album["state"] != "held":
                continue
            section = self.album(album["source"])
            for f in album["files"]:
                track = [n for n in section.all(**{"data-file": f["source"]})]
                self.assertEqual(len(track), 1, f["source"])
                for key in sorted(set(f["before"]) | set(f["after"])):
                    before, after = f["before"].get(key, []), f["after"].get(key, [])
                    if before == after:
                        continue
                    rows = track[0].all(**{"data-tag": key})
                    self.assertEqual(len(rows), 1, f"{f['source']} {key}")
                    text = rows[0].text()
                    for v in before + after:
                        self.assertIn(v, text, f"{f['source']} {key}")
                    if before and after:
                        self.assertLess(text.index(before[0]), text.index(after[0]), f"{f['source']} {key}")
                    checked += 1
        # title, date, comment and musicbrainz_albumid, then title,
        # encodedby and musicbrainz_albumid, then TIT2 and TCON.
        self.assertEqual(checked, 9)

    def test_every_track_that_moves_has_its_path_before_then_after(self) -> None:
        moved = [f for a in plan_doc()["albums"] if a["state"] == "held"
                 for f in a["files"] if f["source"] != f["destination"]]
        self.assertEqual(len(moved), 2)
        for f in moved:
            track = self.album(DISINTEGRATION).all(**{"data-file": f["source"]})
            self.assertEqual(len(track), 1)
            rows = track[0].all(**{"data-path": True})
            self.assertEqual(len(rows), 1, f["source"])
            text = rows[0].text()
            self.assertIn(f["source"], text)
            self.assertIn(f["destination"], text)
            self.assertLess(text.index(f["source"]), text.index(f["destination"]))

    def test_every_residue_item_being_removed_is_listed(self) -> None:
        items = [n.text() for n in self.album(DISINTEGRATION).all(**{"data-residue": True})]
        self.assertEqual(len(items), 2)
        for r in plan_doc()["albums"][1]["residue"]:
            wanted = [r["key"]] + ([r["value"]] if r["value"] is not None else [])
            self.assertTrue(any(all(w in t for w in wanted) for t in items), r)

    def test_a_soundtrack_type_album_offers_three_game_radios_and_no_other_album_does(self) -> None:
        # 003 criterion 58. `not game music` is looked for too, so a page
        # still offering the old pair fails here.
        def offered(section: Node) -> list[tuple[str, str]]:
            return sorted((n.attrs.get("name", ""), n.attrs["value"]) for n in section.tags("input")
                          if n.attrs.get("type", "").lower() == "radio"
                          and n.attrs.get("value") in GAME | {"not game music"})

        radios = offered(self.album(OCARINA))
        self.assertEqual(sorted(value for _name, value in radios), sorted(GAME))
        # One group, so the browser lets the owner pick one of the three.
        self.assertEqual(len({name for name, _value in radios}), 1, radios)
        for key in (DISINTEGRATION, WISH, AUTO):
            self.assertEqual(offered(self.album(key)), [], key)


def field_values(control: Node) -> list[str]:
    if control.tag == "textarea":
        return [control.text()]
    return [control.attrs.get("value", "")]


class Inputs(_Rendered):
    def test_every_field_the_engine_would_write_has_an_editable_input_holding_its_value(self) -> None:
        """Held and auto alike: auto albums are collapsed, not read-only.

        One input per field per position, or one album-wide input (no
        `data-position`) for a field that is the same on every track: the
        contract lets an album-level edit be made once and written to every
        position, and which of the two the page offers is the builder's call.
        """
        checked = 0
        for album in plan_doc()["albums"]:
            if album["state"] not in ("held", "auto"):
                continue
            controls = [n for n in self.album(album["source"]).tags("input", "textarea")
                        if "data-field" in n.attrs]
            for c in controls:
                self.assertNotIn("disabled", c.attrs, album["source"])
                self.assertNotIn("readonly", c.attrs, album["source"])
            for position, fields in album["fields"].items():
                for field, values in fields.items():
                    mine = [c for c in controls if c.attrs["data-field"] == field
                            and c.attrs.get("data-position") == position]
                    wide = [c for c in controls if c.attrs["data-field"] == field
                            and "data-position" not in c.attrs]
                    found = mine or wide
                    self.assertTrue(found, f"{album['source']} {position} {field}")
                    shown = [v for c in found for v in field_values(c)]
                    if len(values) == 1:
                        self.assertIn(values[0], shown, f"{album['source']} {position} {field}")
                    else:
                        # One input per value, or one input with the values
                        # joined: the spec does not say which.
                        for v in values:
                            self.assertTrue(any(v in s for s in shown), f"{album['source']} {position} {field} {v}")
                    checked += 1
        self.assertEqual(checked, 3 + 8 + 2)


class Escaping(unittest.TestCase):
    """A tag value is whatever a ripper left: markup in it stays text.

    `</script>` in a value ends the embedded JSON early, and `<!--` inside a
    script puts a browser into a state where the next `</script>` no longer
    closes it. Neither breaks a page built from polite fixtures.
    """

    NASTY = 'Plainsong <!--<script> </script><script>pwned()</script> & "x" <b>'

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = plan_doc()
        dis = cls.doc["albums"][1]
        dis["fields"]["1-1"]["title"] = [cls.NASTY]
        dis["files"][0]["after"]["title"] = [cls.NASTY]
        cls.page = render(cls.doc)
        cls.root = parse(cls.page)

    def test_markup_in_a_tag_value_is_shown_as_text_and_runs_nothing(self) -> None:
        self.assertEqual([s.text() for s in self.root.tags("script") if "pwned" in s.text()
                          and 'application/json' not in s.attrs.get("type", "")], [])
        section = albums(self.root)[DISINTEGRATION]
        titles = [c for c in section.tags("input", "textarea") if c.attrs.get("data-field") == "title"]
        self.assertIn(self.NASTY, [v for c in titles for v in field_values(c)])
        self.assertIn(self.NASTY, section.all(**{"data-file": True})[0].text())

    def test_the_embedded_json_survives_markup_in_a_tag_value(self) -> None:
        for id_ in ("plan", "decisions-skeleton"):
            raw = by_id(self.root, id_).text()
            self.assertNotIn("</script", raw.lower(), id_)
            self.assertNotIn("<!--", raw, id_)
            json.loads(raw)
        carried = {a["source"]: a for a in json.loads(by_id(self.root, "plan").text())["albums"]}
        self.assertEqual(carried[DISINTEGRATION]["fields"]["1-1"]["title"], [self.NASTY])


# --- every path that changes ---------------------------------------------------

def relocated(album: dict, rel: str) -> str:
    """Where a file under the album's source lands: `plan.relocated`'s rule."""
    return album["destination"] + rel[len(album["source"]):]


def tail(album: dict, rel: str) -> str:
    return rel[len(album["source"]) + 1:]


class PathChanges(_Rendered):
    """Every file the write deletes, moves or sends out of the library, and every image it writes.

    Tracks are `HeldAlbum`'s. These are the album's other files, which the
    page once left out entirely: the owner approved a write that deleted a
    `.DS_Store` and moved a video to extras without being shown either.
    Auto albums are included, since they are written with nobody deciding.
    """

    def listed(self) -> list[dict]:
        return [a for a in plan_doc()["albums"] if a["state"] in ("held", "auto")]

    def row(self, album: dict, hook: str, value: str) -> str:
        rows = self.album(album["source"]).all(**{hook: value})
        self.assertEqual(len(rows), 1, f"{hook}={value!r}")
        return rows[0].text()

    def assert_moves(self, album: dict, hook: str, rel: str) -> None:
        text = self.row(album, hook, rel)
        where = relocated(album, rel)
        self.assertIn(tail(album, rel), text)
        self.assertIn(where, text)
        # The file's own name also ends the destination, so a row showing
        # only where it goes, or showing it backwards, fails here.
        self.assertLess(text.index(tail(album, rel)), text.index(where), text)

    def test_every_file_the_write_deletes_is_listed(self) -> None:
        seen = 0
        for album in self.listed():
            for rel in album["deletions"]:
                self.assertIn(tail(album, rel), self.row(album, "data-deletion", rel))
                seen += 1
        self.assertEqual(seen, 3)

    def test_every_extra_is_listed_with_where_it_goes_outside_the_library(self) -> None:
        seen = 0
        for album in self.listed():
            for rel in album["extras"]:
                self.assert_moves(album, "data-extra", rel)
                seen += 1
        self.assertEqual(seen, 1)

    def test_every_kept_file_that_moves_with_the_album_is_listed_with_where_it_goes(self) -> None:
        seen = 0
        for album in self.listed():
            if album["source"] == album["destination"]:
                continue
            for rel in album["kept"]:
                self.assert_moves(album, "data-kept", rel)
                seen += 1
        self.assertEqual(seen, 3)

    def test_every_image_the_write_puts_in_the_album_is_listed(self) -> None:
        seen = 0
        for album in self.listed():
            for name in album["images"]:
                self.assertIn(name, self.row(album, "data-image", name))
                seen += 1
        self.assertEqual(seen, 4)


# --- a decision already folded in ----------------------------------------------

ACTIONS = {"accept", "repoint", "skip"}
GAME = {"video game music", "soundtrack", "neither"}


def checked_radios(section: Node, values: set[str]) -> list[str]:
    return [n.attrs["value"] for n in section.tags("input")
            if n.attrs.get("type", "").lower() == "radio" and n.attrs.get("value") in values
            and "checked" in n.attrs]


def folded_doc() -> dict:
    """The fixture after identify folded a `decisions.json` in.

    Disintegration accepted against its second candidate, with the owner's
    title edit on top of the memory's; Ocarina accepted as neither;
    Wish repointed; the auto album accepted with a date edit.
    """
    doc = plan_doc()
    auto, dis, ocarina, _mezzanine, wish = doc["albums"]
    dis.update(decision="accept", release_id=DIS_OTHER_ID)
    dis["inputs"] = dict(dis["inputs"], release_id=DIS_OTHER_ID, chosen=True,
                         edits={"1-1": {"date": ["1989-05-02"]}, "1-2": {"title": ["Pictures Of You"]}})
    dis["owner_edits"] = copy.deepcopy(dis["inputs"]["edits"])
    ocarina.update(decision="accept", game="neither",
                   inputs={"release_id": OCARINA_ID, "chosen": False, "status": "review",
                           "owner_input": {}, "edits": {}})
    wish.update(decision="repoint", release_id=WISH_ID)
    wish["holds"].append({"kind": "repointed", "detail": WISH_ID})
    auto.update(decision="accept",
                inputs={"release_id": AUTO_ID, "chosen": False, "status": "certain",
                        "owner_input": {"composers": {}}, "edits": {"1-1": {"date": ["1992"]}}},
                owner_edits={"1-1": {"date": ["1992"]}})
    return doc


class FoldedDecision(unittest.TestCase):
    """A page built after identify folded `decisions.json` in starts from that answer, not skip.

    Otherwise the owner's second export silently turns last round's accept
    or repoint back into skip, and drops its edits and game choice.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = parse(render(folded_doc()))

    def section(self, key: str) -> Node:
        return albums(self.root)[key]

    def test_an_accepted_album_opens_with_accept_and_its_release_selected(self) -> None:
        # The second candidate, so a page that selects the first by habit fails.
        section = self.section(DISINTEGRATION)
        self.assertEqual(checked_radios(section, ACTIONS), ["accept"])
        self.assertEqual(checked_radios(section, {DIS_ID, DIS_OTHER_ID}), [DIS_OTHER_ID])

    def test_an_accepted_game_album_opens_with_its_game_choice_selected(self) -> None:
        # `neither` is the last of the three, so a page checking the first
        # fails, and it is the one a check for a truthy game value drops.
        section = self.section(OCARINA)
        self.assertEqual(checked_radios(section, ACTIONS), ["accept"])
        self.assertEqual(checked_radios(section, GAME), ["neither"])

    def test_a_repointed_album_opens_with_repoint_selected_and_its_release_in_the_box(self) -> None:
        section = self.section(WISH)
        self.assertEqual(checked_radios(section, ACTIONS), ["repoint"])
        boxes = section.all(**{"data-repoint": True})
        self.assertEqual([b.attrs.get("value") for b in boxes], [WISH_ID])

    def test_the_skeleton_carries_each_folded_decision_with_its_edits_and_game(self) -> None:
        """Pressing export on this page, untouched, gives back what was decided.

        The accept's `edits` are the entry's `owner_edits`, memory and
        decision together, so nothing decided last round is lost. The auto
        album is in it because its entry says accept.
        """
        doc = folded_doc()
        by_source = {a["source"]: a for a in doc["albums"]}
        self.assertEqual(json.loads(by_id(self.root, "decisions-skeleton").text()), {
            "job": JOB,
            "albums": {
                AUTO: {"action": "accept", "release_id": AUTO_ID,
                       "edits": by_source[AUTO]["owner_edits"], "game": None},
                DISINTEGRATION: {"action": "accept", "release_id": DIS_OTHER_ID,
                                 "edits": by_source[DISINTEGRATION]["owner_edits"], "game": None},
                OCARINA: {"action": "accept", "release_id": OCARINA_ID, "edits": {}, "game": "neither"},
                WISH: {"action": "repoint", "release": WISH_ID},
            },
        })

    def test_an_album_skipped_or_never_decided_opens_with_skip_and_no_game_choice(self) -> None:
        for decision in ("skip", None):
            doc = plan_doc()
            for album in doc["albums"]:
                if album["state"] == "held":
                    album["decision"] = decision
            root = parse(render(doc))
            for key in (DISINTEGRATION, OCARINA):
                section = albums(root)[key]
                self.assertEqual(checked_radios(section, ACTIONS), ["skip"], f"{key} {decision}")
                self.assertEqual(checked_radios(section, GAME), [], f"{key} {decision}")


class NoComposerGameChoice(unittest.TestCase):
    """A game choice on an album with no composer, after a fold, stays the owner's to change.

    `inputs.edits` can hold a genre the batch laid for `video game music`. If
    the page carried that edit forward, flipping the radio to `soundtrack` or
    `neither` would still write the genre, and the owner could never take it
    back. So the page carries `owner_edits`, which never holds it.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = folded_doc()
        ocarina = cls.doc["albums"][2]
        ocarina.update(composer=None, game="video game music",
                       owner_edits={"1-1": {"title": ["Toki no Ocarina (Title Theme)"]}})
        ocarina["inputs"] = dict(ocarina["inputs"], owner_input={"composers": {}},
                                 edits={"1-1": {"title": ["Toki no Ocarina (Title Theme)"],
                                                "genre": ["video game music"]}})
        cls.root = parse(render(cls.doc))

    def test_the_embedded_plan_carries_the_owners_edits_without_the_game_genre(self) -> None:
        carried = {a["source"]: a for a in json.loads(by_id(self.root, "plan").text())["albums"]}
        self.assertEqual(carried[OCARINA]["edits"], {"1-1": {"title": ["Toki no Ocarina (Title Theme)"]}})

    def test_the_skeleton_accept_carries_the_owners_edits_without_the_game_genre(self) -> None:
        skeleton = json.loads(by_id(self.root, "decisions-skeleton").text())
        self.assertEqual(skeleton["albums"][OCARINA], {
            "action": "accept", "release_id": OCARINA_ID,
            "edits": {"1-1": {"title": ["Toki no Ocarina (Title Theme)"]}}, "game": "video game music",
        })


# --- export --------------------------------------------------------------------

class Export(_Rendered):
    def test_the_export_skeleton_is_a_decisions_json_skipping_every_held_album(self) -> None:
        """What the page downloads if the owner decides nothing.

        The job ID, one `skip` per held album, nothing for an auto album the
        owner has not edited or for an unchanged one.
        """
        node = by_id(self.root, "decisions-skeleton")
        self.assertEqual(node.tag, "script")
        self.assertEqual(node.attrs.get("type"), "application/json")
        self.assertEqual(json.loads(node.text()), {
            "job": JOB,
            "albums": {key: {"action": "skip"} for key in HELD},
        })

    def test_a_job_with_nothing_held_exports_no_albums(self) -> None:
        doc = plan_doc()
        doc["job"] = "2b-12"
        doc["albums"] = [a for a in doc["albums"] if a["state"] != "held"]
        root = parse(render(doc))
        self.assertEqual(json.loads(by_id(root, "decisions-skeleton").text()), {"job": "2b-12", "albums": {}})

    def test_the_embedded_plan_carries_only_what_the_export_reads(self) -> None:
        """`#plan` carries, per listed album, exactly what `review.js` reads.

        `source`, `state`, `fields`, `game_choice`, `release_id`,
        `decision`, `game`, and `edits`, which is the entry's `owner_edits`:
        export merges the owner's changes over it. A key added here is a key
        the script started reading.
        """
        node = by_id(self.root, "plan")
        self.assertEqual(node.attrs.get("type"), "application/json")
        carried = json.loads(node.text())
        self.assertLessEqual(set(carried), {"job", "albums"})
        by_source = {a["source"]: a for a in self.doc["albums"]}
        read = {"source", "state", "fields", "game_choice", "release_id", "decision", "game", "edits"}

        def value(original: dict, key: str):
            if key == "edits":
                return original["owner_edits"]
            return original[key]

        listed = set()
        for album in carried["albums"]:
            original = by_source[album["source"]]
            if original["state"] in ("held", "auto"):
                self.assertEqual(set(album), read, album["source"])
                listed.add(album["source"])
            else:
                self.assertLessEqual(set(album), read, album["source"])
            self.assertEqual(album, {k: value(original, k) for k in album}, album["source"])
        self.assertEqual(listed, {*HELD, AUTO})
        # Disintegration's owner_edits hold an edit, so an `edits` of `{}` everywhere fails.
        dis = next(a for a in carried["albums"] if a["source"] == DISINTEGRATION)
        self.assertEqual(dis["edits"], {"1-1": {"date": ["1989-05-02"]}})

    def test_the_page_has_an_export_button(self) -> None:
        self.assertEqual(by_id(self.root, "export").tag, "button")


# --- end to end: the plan identify really writes -----------------------------

class FromIdentify(unittest.TestCase):
    """`review.html` as `batch identify` writes it, from a real library.

    The fixtures above build a `plan.json` by hand; this one comes from a
    real `identify` run instead, so it includes every file that is not a
    track. The album is held (its track lengths are four minutes off),
    moves, and carries one of each: a file deleted, a video sent to extras,
    a log kept, a cover.
    """

    KEY = "R/Rook/Off [rip]"

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile
        from pathlib import Path

        from tests import test_batch_identify as ident

        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        ident.no_throttle(cls)
        base = Path(tmp.name)
        root, job, memory = base / "library", base / ".musiclib" / "jobs" / "j1", base / ".musiclib" / "memory.json"
        root.mkdir()
        job.mkdir(parents=True)
        catalogue = [ident.release(1, "Rook", "Off", ["One", "Two"], exact=False)]
        folder = ident.album(root, cls.KEY, ["One", "Two"], release_id=catalogue[0][0]["id"])
        (folder / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
        # An EBML header, so the file reads as a video by its content.
        (folder / "Making of.mkv").write_bytes(b"\x1aE\xdf\xa3 a video")
        (folder / "rip.log").write_text("Exact Audio Copy V1.6 extraction logfile\n")
        code, _out, err = ident.run_identify(root, job, memory, ident.Services(catalogue))
        if code not in (0, 1):
            raise AssertionError(f"identify exited {code}: {err}")
        doc = json.loads((job / "plan.json").read_text(encoding="utf-8"))
        cls.entry = next(a for a in doc["albums"] if a["source"] == cls.KEY)
        cls.root = parse((job / "review.html").read_text(encoding="utf-8"))

    def test_a_page_from_identify_shows_the_deleted_file_the_extra_the_kept_log_and_the_cover(self) -> None:
        entry = self.entry
        # The library as built, or nothing below means anything.
        self.assertEqual(entry["state"], "held")
        self.assertNotEqual(entry["destination"], self.KEY)
        section = albums(self.root)[self.KEY]

        def one(hook: str, value: str) -> str:
            rows = section.all(**{hook: value})
            self.assertEqual(len(rows), 1, f"{hook}={value!r}")
            return rows[0].text()

        self.assertIn(".DS_Store", one("data-deletion", f"{self.KEY}/.DS_Store"))
        self.assertIn("Making of.mkv", one("data-extra", f"{self.KEY}/Making of.mkv"))
        self.assertIn(f"{entry['destination']}/Making of.mkv", one("data-extra", f"{self.KEY}/Making of.mkv"))
        self.assertIn(f"{entry['destination']}/rip.log", one("data-kept", f"{self.KEY}/rip.log"))
        self.assertIn("cover.jpg", one("data-image", "cover.jpg"))


if __name__ == "__main__":
    unittest.main()
