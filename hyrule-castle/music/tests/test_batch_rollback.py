"""`musiclib batch rollback --job DIR`: a job's writes taken back out of the library.

Criterion 15 in spec 002. Rollback reads `applied.jsonl` and puts every tag
value and every path its `applied` lines record back, newest line first. A
`failed` line was already put back by 001's write, so it is left alone. What
cannot come back is listed: the embedded pictures the write added or
replaced, the `cover.jpg` it wrote (`created`) and the files it removed
(`deleted`). Listing anything makes the exit code 1. A rollback that stops
partway through an album is finished by running it again.

Every job here is built the real way, as `tests.test_batch_apply` builds
them: rips on disk, `batch identify` over them with
`tests.test_batch_identify`'s fake MusicBrainz, `batch apply` with a stub
`systemctl` that says foobar2000 is stopped and a transport that refuses
every request, then rollback. So the log rollback reads is the one apply
really writes, and a change to either side of that shape shows up here.

A rip here has no embedded picture and carries a `cover.jpg`. The archive
has no art for it, so apply embeds the rip's cover in every track, writes
`cover.jpg` at the destination and deletes the one at the source. That is
one of each thing rollback owes a list for.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from musiclib import files, tagwrite
from musiclib.__main__ import main
from tests import builders
from tests.test_batch_apply import Library
from tests.test_batch_identify import no_throttle, release

#: One album per format rollback has to write tags back into. The keys sort
#: in this order, which is the order apply writes them and the order the
#: log holds them.
FLAC = "F/Flac Band/Record 1 [rip]"
M4A = "M/M4A Band/Record 3 [rip]"
MP3 = "M/Mp3 Band/Record 2 [rip]"
OGG = "O/Ogg Band/Record 4 [rip]"
FORMATS = {FLAC: "flac", MP3: "mp3", M4A: "m4a", OGG: "ogg"}

#: A release four minutes off its files, so identify holds it and apply never
#: writes it. Rollback has no line for it either.
HELD = "H/Held/Untouched [rip]"

#: The two residue files the flac album carries: one the write deletes, and
#: one it sends to the extras folder.
RESIDUE = "Thumbs.db"
VIDEO = "video.mp4"


class Rips(Library):
    """`tests.test_batch_apply.Library`, with rips in any format and under any file names."""

    def rip(self, key: str, number: int, ext: str, titles: list[str], *, artist: str | None = None,
            title: str | None = None, names: list[str] | None = None, exact: bool = True) -> Path:
        """An album at `key` in `ext`, tagged with release `number` of `artist` and `title`.

        `artist` and `title` default to the ones the key spells, and `names`
        to `01 one.<ext>` and so on, the loose names a rip arrives with.
        """
        artist = artist or key.split("/")[1]
        title = title or key.split("/")[2].split(" [")[0]
        found, group = release(number, artist, title, titles, exact=exact)
        self.catalogue.append((found, group))
        base = self.root / key
        base.mkdir(parents=True)
        for position, name in enumerate(titles, start=1):
            path = base / (names[position - 1] if names else f"{position:02d} {name.lower()}.{ext}")
            shutil.copyfile(builders.FIXTURES / f"tone.{ext}", path)
            fields = {"title": [name.lower()], "artist": [artist], "album": [title], "date": ["1989"],
                      "release id": [found["id"]]}
            builders.write_tags(path, builders.picard_tags(ext, fields, track=(position, len(titles)),
                                                           disc=(1, 1)), v2_version=4)
        shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
        return base

    def rollback(self) -> tuple[int, str, str]:
        """`batch.rollback.run` on this job: its exit code, stdout and stderr.

        Imported here rather than at the top, so this file loads while the
        module does not exist yet and each case fails on its own.
        """
        from musiclib.batch.job import Job
        from musiclib.batch.rollback import run

        out, err = io.StringIO(), io.StringIO()
        # Apply's own extras folder and live root, and a stub that says
        # foobar2000 is stopped, so nothing here reaches /srv.
        code = run(Job(self.job), extras_root=self.extras, live_root=self.root,
                   systemctl=str(self.systemctl(running=False)), out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def rewrite_log(self, lines: list[dict]) -> None:
        (self.job / "applied.jsonl").write_text(
            "".join(json.dumps(line, sort_keys=True, ensure_ascii=False) + "\n" for line in lines),
            encoding="utf-8")


def new_rips(case) -> Rips:
    tmp = tempfile.TemporaryDirectory()
    cleanup = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    cleanup(tmp.cleanup)
    no_throttle(case)
    return Rips(Path(tmp.name))


def tracks(root: Path) -> dict[str, dict[str, list[str]]]:
    """Every track under `root` by its path relative to `root`, with its tags less any picture.

    A picture is left out because rollback does not owe it back: apply
    embeds the cover, and the cover stays.
    """
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lstrip(".") in ("flac", "mp3", "m4a", "ogg"):
            track = files.read(path)
            found[path.relative_to(root).as_posix()] = {
                key: values for key, values in track.tags.items()
                if not tagwrite.is_picture_key(track.family, key)}
    return found


def empty_folders(root: Path) -> list[str]:
    if not root.exists():
        return []
    return [path.relative_to(root).as_posix() for path in sorted(root.rglob("*"))
            if path.is_dir() and not any(path.iterdir())]


class RollingBack(unittest.TestCase):
    """Four albums, one per format, applied and rolled back once. The cases only read.

    The flac album also carries a residue file apply deletes and a video it
    sends to the extras folder. HELD is never written, so rollback has no
    line for it.
    """

    @classmethod
    def setUpClass(cls):
        lib = cls.lib = new_rips(cls)
        # Made out of path order, the same as apply's own fixture.
        for number, key in enumerate((OGG, M4A, MP3, FLAC), start=1):
            lib.rip(key, number, FORMATS[key], ["One", "Two"])
        lib.rip(HELD, 9, "flac", ["One", "Two"], exact=False)
        (lib.root / FLAC / RESIDUE).write_bytes(b"thumbnail cache")
        shutil.copyfile(builders.VIDEO_MP4, lib.root / FLAC / VIDEO)
        lib.identify()
        states = lib.states()
        expected = {**{key: "auto" for key in FORMATS}, HELD: "held"}
        if states != expected:
            raise AssertionError(f"the fixture did not plan as these cases assume: {states}")
        cls.entries = lib.entries()
        if cls.entries[FLAC]["deletions"] != [f"{FLAC}/{RESIDUE}", f"{FLAC}/cover.jpg"] \
                or cls.entries[FLAC]["extras"] != [f"{FLAC}/{VIDEO}"]:
            raise AssertionError(f"the flac album did not plan its residue as these cases assume: "
                                 f"{cls.entries[FLAC]['deletions']}, {cls.entries[FLAC]['extras']}")
        cls.before = tracks(lib.root)
        cls.held_before = builders.tree(lib.root / HELD)
        cls.video = (lib.root / FLAC / VIDEO).read_bytes()

        code, _out, err = lib.apply()
        if code != 0 or [line["source"] for line in lib.log()] != sorted(FORMATS):
            raise AssertionError(f"apply did not write the four albums: {code}, {err}, {lib.log()}")
        cls.log = lib.log()
        cls.applied = tracks(lib.root)
        # Rollback that finds everything already where it started passes
        # every case below without doing a thing.
        if set(cls.applied) & set(k for k in cls.before if not k.startswith(HELD + "/")):
            raise AssertionError("apply left a track where it was")

        cls.code, out, err = lib.rollback()
        cls.said = out + err

    def test_every_track_is_back_at_its_original_path_with_its_original_tag_values(self):
        after = tracks(self.lib.root)
        for key, ext in FORMATS.items():
            with self.subTest(album=key, format=ext):
                mine = {rel: tags for rel, tags in self.before.items() if rel.startswith(key + "/")}
                self.assertTrue(mine, f"{key}: the fixture has no tracks")
                self.assertEqual({rel: tags for rel, tags in after.items() if rel.startswith(key + "/")},
                                 mine)
        # No copy of a track left at its destination, and none anywhere else.
        self.assertEqual(sorted(after), sorted(self.before))

    def test_no_folder_the_apply_created_is_left_empty_in_the_library(self):
        # Apply made each destination folder. Whether rollback removes the
        # `cover.jpg` apply wrote there is not settled, so the folder may
        # stay with the cover in it. What may not stay is a folder with
        # nothing in it, which foobar2000 shows as an empty album.
        self.assertEqual(empty_folders(self.lib.root), [])

    def test_the_video_apply_sent_to_extras_is_back_in_the_album_and_extras_is_left_with_no_empty_folder(self):
        # The log records the video's destination relative to the extras
        # folder, so rollback is given the same one apply was.
        back = self.lib.root / FLAC / VIDEO
        self.assertTrue(back.is_file(), f"the video is not back: {self.said}")
        self.assertEqual(back.read_bytes(), self.video)
        self.assertEqual([p for p, data in builders.tree(self.lib.extras).items() if data is not None],
                         [], "the video is back and still in extras")
        self.assertEqual(empty_folders(self.lib.extras), [])

    def test_the_covers_and_residue_apply_wrote_or_deleted_are_listed_and_the_run_exits_1(self):
        # Rollback cannot put back a file apply deleted: the log keeps its
        # path, never its bytes. The owner has to be told which ones.
        for line in self.log:
            record = line["record"]
            with self.subTest(album=line["source"]):
                self.assertTrue(record["created"] and record["deleted"],
                                f"the fixture wrote or deleted nothing: {record}")
                for path in record["created"] + record["deleted"]:
                    self.assertIn(path, self.said)
        self.assertIn(f"{FLAC}/{RESIDUE}", self.said)
        self.assertEqual(self.code, 1)

    def test_every_track_whose_embedded_picture_stayed_is_named(self):
        # The rip had no picture. Apply embedded the cover, and rollback
        # leaves it. The track is named by where it was or where it went;
        # either is an acceptable way to tell the owner which file it is.
        for line in self.log:
            for planned in self.entries[line["source"]]["files"]:
                with self.subTest(track=planned["source"]):
                    self.assertTrue(planned["source"] in self.said or planned["destination"] in self.said,
                                    f"{planned['source']} is not named in: {self.said}")

    def test_an_album_the_log_does_not_name_is_byte_identical_afterwards(self):
        self.assertEqual(builders.tree(self.lib.root / HELD), self.held_before)


class NewestFirst(unittest.TestCase):
    def test_a_track_moved_onto_a_path_an_earlier_line_emptied_is_moved_off_it_before_that_line_is_undone(self):
        # Two lines of one job that share a path. OLD sits where NEW is
        # going and moves out of the way; NEW then moves in, under the same
        # file names. Undone oldest first, OLD's tracks land on NEW's and one
        # album is lost. Only newest first gives both back.
        old, new = "A/Alpha/(2010) First", "B/Beta/Second [rip]"
        lib = new_rips(self)
        lib.rip(old, 1, "flac", ["Uno", "Dos"], title="Renamed", names=["01. One.flac", "02. Two.flac"])
        lib.rip(new, 2, "flac", ["One", "Two"], artist="Alpha", title="First")
        before = tracks(lib.root)

        # The first round: NEW would land on OLD's files, so it is held.
        lib.identify()
        self.assertEqual(lib.states(), {old: "auto", new: "held"})
        self.assertEqual([f["destination"] for f in lib.entries()[new]["files"]],
                         [f"{old}/01. One.flac", f"{old}/02. Two.flac"])
        self.assertEqual(lib.apply()[0], 0)
        # The second round: OLD has gone, so NEW is written.
        lib.identify()
        self.assertEqual(lib.states()[new], "auto")
        self.assertEqual(lib.apply()[0], 0)
        self.assertEqual([line["source"] for line in lib.log()], [old, new])
        self.assertEqual(sorted(tracks(lib.root)),
                         ["A/Alpha/(2010) First/01. One.flac", "A/Alpha/(2010) First/02. Two.flac",
                          "A/Alpha/(2010) Renamed/01. Uno.flac", "A/Alpha/(2010) Renamed/02. Dos.flac"])

        _code, out, err = lib.rollback()

        self.assertEqual(tracks(lib.root), before, out + err)


class FailedLines(unittest.TestCase):
    def test_a_failed_line_is_left_alone_and_the_applied_lines_are_still_undone(self):
        first, last = "A/Alpha/First [rip]", "Z/Zeta/Last [rip]"
        lib = new_rips(self)
        lib.rip(first, 1, "flac", ["One", "Two"])
        lib.rip(last, 2, "mp3", ["One", "Two"])
        before = tracks(lib.root)
        lib.identify()
        self.assertEqual(lib.apply()[0], 0)
        log = lib.log()
        self.assertEqual([line["source"] for line in log], [first, last])
        # A real `failed` line's album is back where it started already, so
        # undoing it again would show nothing. This one keeps the full
        # record of a write that did happen: a rollback that replays it puts
        # LAST back, and that shows.
        log[1].update(outcome="failed", error="write did not verify")
        lib.rewrite_log(log)
        written = builders.tree(lib.root / log[1]["destination"])
        self.assertTrue(written, "LAST was not written")

        _code, out, err = lib.rollback()

        self.assertEqual(builders.tree(lib.root / log[1]["destination"]), written, out + err)
        self.assertEqual({rel: tags for rel, tags in tracks(lib.root).items() if rel.startswith(first + "/")},
                         {rel: tags for rel, tags in before.items() if rel.startswith(first + "/")})


class MovesWithinAnAlbum(unittest.TestCase):
    """An album whose tracks move onto each other's names, undone as one batch of moves.

    Both albums are already in their destination folder, with the tracks
    under the wrong names, so apply only renames them. Every track is the
    same tone, and rollback writes tags by path, so neither says which file
    ended where. Each file gets its own bytes at the end, after the audio,
    and that is what follows the file.
    """

    def roll_back(self, key: str, titles: list[str], names: list[str], chain: list[str]) -> None:
        """Rip `key` with track n of `titles` in the file `names[n]`, apply it, roll it back.

        `chain` is the renames apply is expected to make, each name moving
        onto the next.
        """
        lib = new_rips(self)
        lib.rip(key, 1, "flac", titles, title=key.rsplit(") ", 1)[1], names=names)
        own = {}
        for name in names:
            rel = f"{key}/{name}"
            own[rel] = f"\nthe file first at {rel}\n".encode()
            with open(lib.root / rel, "ab") as handle:
                handle.write(own[rel])
        before = tracks(lib.root)
        lib.identify()
        self.assertEqual(lib.states(), {key: "auto"})
        self.assertEqual(lib.apply()[0], 0)
        moves = [(source, destination) for source, destination, _kind in lib.log()[0]["record"]["moves"]]
        # The record has to hold the shape this case is about, or it tests
        # an ordinary rename.
        self.assertCountEqual(moves, [(f"{key}/{a}", f"{key}/{b}") for a, b in zip(chain, chain[1:])])

        _code, out, err = lib.rollback()

        for rel, data in own.items():
            with self.subTest(file=rel):
                path = lib.root / rel
                self.assertTrue(path.is_file(), f"{rel} is not back: {out + err}")
                self.assertTrue(path.read_bytes().endswith(data), f"another file is at {rel}: {out + err}")
        self.assertEqual(tracks(lib.root), before, out + err)

    def test_a_chain_of_renames_each_onto_the_name_the_last_one_left_is_undone_to_the_original_files(self):
        # zz.flac becomes 01, 01 becomes 02, 02 becomes 03. After apply, 01
        # and 02 both exist again, so a rollback that undoes only moves whose
        # source is free skips two of the three.
        self.roll_back("A/Alpha/(2010) Chain", ["One", "Two", "Three"],
                       names=["zz.flac", "01. One.flac", "02. Two.flac"],
                       chain=["zz.flac", "01. One.flac", "02. Two.flac", "03. Three.flac"])

    def test_two_tracks_that_swapped_names_are_swapped_back_with_their_own_tags(self):
        # Both names exist before and after, so every move looks already
        # undone to a rollback that checks each one against the disk.
        self.roll_back("A/Alpha/(2010) Swap", ["One", "Two"],
                       names=["02. Two.flac", "01. One.flac"],
                       chain=["02. Two.flac", "01. One.flac", "02. Two.flac"])


class MissingExtra(unittest.TestCase):
    def test_a_video_deleted_from_extras_after_apply_is_listed_and_the_album_is_still_rolled_back(self):
        # Somebody clears out the extras folder between apply and rollback.
        # Undone in one batch with the tracks, the missing video fails the
        # batch, the batch puts every track back where apply left it, and
        # the album can never be rolled back.
        key = "A/Alpha/First [rip]"
        lib = new_rips(self)
        lib.rip(key, 1, "flac", ["One", "Two"])
        shutil.copyfile(builders.VIDEO_MP4, lib.root / key / VIDEO)
        before = tracks(lib.root)
        lib.identify()
        self.assertEqual(lib.entries()[key]["extras"], [f"{key}/{VIDEO}"])
        self.assertEqual(lib.apply()[0], 0)
        destination = lib.log()[0]["destination"]
        video = lib.extras / destination / VIDEO
        self.assertTrue(video.is_file(), "apply did not send the video to extras")
        video.unlink()

        code, out, err = lib.rollback()

        said = out + err
        self.assertEqual(tracks(lib.root), before, said)
        self.assertTrue(f"{key}/{VIDEO}" in said or f"{destination}/{VIDEO}" in said,
                        f"the video is not named: {said}")
        self.assertEqual(code, 1, said)
        rolled_back = [line["source"] for line in lib.log() if line["outcome"] == "rolled back"]
        self.assertEqual(rolled_back, [key], said)


class RunAgain(unittest.TestCase):
    def test_a_rollback_that_failed_partway_through_an_album_is_finished_by_running_it_again(self):
        # A read-only track moves back like any other, since a rename needs
        # only its folder to be writable, and then refuses its tags. That
        # leaves the album half undone: its tracks at their old paths, one of
        # them still carrying what apply wrote. The second run has to take
        # each step from where the album is now. Replaying the moves from
        # the log finds their destinations gone and never reaches the tags.
        stuck, done = "A/Alpha/First [rip]", "Z/Zeta/Last [rip]"
        lib = new_rips(self)
        lib.rip(stuck, 1, "flac", ["One", "Two"])
        lib.rip(done, 2, "mp3", ["One", "Two"])
        before = tracks(lib.root)
        lib.identify()
        self.assertEqual(lib.apply()[0], 0)
        entry = lib.entries()[stuck]
        self.assertEqual([line["source"] for line in lib.log()], [stuck, done])

        locked = lib.root / entry["files"][1]["destination"]
        locked.chmod(0o444)
        first_code, out, err = lib.rollback()
        # The fixture has to have left the album half undone, or the second
        # run is only a first run. Checked on the state, not on how the
        # rollback got there.
        back = lib.root / entry["files"][1]["source"]
        self.assertEqual(first_code, 1, out + err)
        self.assertTrue(back.is_file(), f"the read-only track did not move back: {out + err}")
        self.assertNotEqual(tracks(lib.root)[entry["files"][1]["source"]], before[entry["files"][1]["source"]],
                            "the read-only track took its tags back after all, so nothing failed")
        back.chmod(0o644)

        _code, out, err = lib.rollback()

        self.assertEqual(tracks(lib.root), before, out + err)
        rolled_back = [line["source"] for line in lib.log() if line["outcome"] == "rolled back"]
        # One line each: the album finished second time round, and the one
        # finished the first time was not undone again.
        self.assertEqual(sorted(rolled_back), [stuck, done], out + err)
        # The first run got as far as the stuck album's tags, so its moves
        # were marked undone then. The retry goes straight to the tags and
        # marks nothing again.
        undone = [line["source"] for line in lib.log() if line["outcome"] == "moves undone"]
        self.assertEqual(undone.count(stuck), 1, lib.log())


class Cli(unittest.TestCase):
    def test_batch_rollback_on_the_command_line_undoes_the_job_and_exits_1_listing_the_cover(self):
        key = "A/Alpha/First [rip]"
        lib = new_rips(self)
        lib.rip(key, 1, "ogg", ["One", "Two"])
        before = tracks(lib.root)
        lib.identify()
        self.assertEqual(lib.apply()[0], 0)
        self.assertNotEqual(tracks(lib.root), before)

        with contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            try:
                code = main(["batch", "rollback", "--job", str(lib.job)])
            except SystemExit as exc:
                # argparse refusing the subcommand; its message is in `err`.
                code = exc.code

        said = out.getvalue() + err.getvalue()
        self.assertEqual(tracks(lib.root), before, said)
        self.assertIn(f"{key}/cover.jpg", said)
        self.assertEqual(code, 1, said)


if __name__ == "__main__":
    unittest.main()
