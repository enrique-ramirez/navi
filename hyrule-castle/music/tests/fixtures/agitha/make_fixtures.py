#!/usr/bin/env python3
"""Rebuild `catalogue.json` and each case's `plan.json` beside this file.

Each case is an album staged the way agitha stages one, identified by
`tests/agitha_stub.py` over the fake MusicBrainz in `catalogue.json`. Run it
from `hyrule-castle/music`:

    ../../_tmp/venv/bin/python tests/fixtures/agitha/make_fixtures.py

The output is the same on every run: ids and names are fixed, and the
temporary root in `plan.json` is rewritten to where the box keeps it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MUSIC = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(MUSIC))

from PIL import Image

from tests import builders  # noqa: E402
from tests.test_batch_identify import TRUNCATED, release  # noqa: E402

HERE = Path(__file__).resolve().parent
STUB = MUSIC / "tests" / "agitha_stub.py"
BOX_ROOT = "/srv/music/inbox/20260929-210000/01"
JOB_NAME = "agitha-20260929-210000-01"

#: case -> (number, artist, album folder, titles)
CASES = {
    "auto-clean": (1, "Clean Band", "Clean Album", ["One", "Two", "Three"]),
    "decision-hold": (2, "Genreless Band", "Bare Album", ["One", "Two", "Three"]),
    "soundtrack-choice": (3, "Score Band", "Score Album", ["One", "Two", "Three"]),
    "raw-edits-owner-cover": (4, "Edited Band", "Edited Album", ["One", "Two", "Three"]),
    "missing-track": (5, "Missing Band", "Missing Album", ["One", "Two", "Three"]),
    "stray-images": (6, "Stray Band", "Stray Album", ["One", "Two", "Three"]),
}

#: The strays of `stray-images`, album-relative, each commented with the answer it gets.
#: Every image has its own pixel size, since two plain JPEGs of one size are the same bytes.
STRAY_BACK = "COVERS/stray_band_stray_album-back.jpg"
STRAYS = {
    STRAY_BACK: builders.jpeg(1688, 1476),  # won: at least 10 % more pixels than the rip's own back.jpg
    "COVERS/stray_band-tray.jpg": builders.jpeg(800, 700),  # lost to the rip's own, bigger tray.jpg
    "COVERS/stray_album-obi.jpg": builders.jpeg(1400, 1300),  # guessed: obi.jpg
    "COVERS/folder.jpg": (builders.FIXTURES / "cover.jpg").read_bytes(),  # copy of cover.jpg
    "COVERS/IMG_0001.jpg": builders.jpeg(1200, 1200),  # no guess, left undecided
    "COVERS/IMG_0002.jpg": builders.jpeg(1100, 900),  # no guess, named by the owner's accept
    # A copy of another stray: `against` is that stray's path, not a library name. It has no guess of its
    # own, since a copy that is guessed still takes a number from its type (the back would be back-1.jpg).
    "Scans/IMG_0001 copy.jpg": builders.jpeg(1200, 1200),
}
#: Images at the album folder's root, the strays' rivals for a name. The stub's
#: Cover Art Archive has no art, so no stray can meet an archive image here.
ROOT_IMAGES = {"back.jpg": builders.jpeg(1000, 1000), "tray.jpg": builders.jpeg(1500, 1500)}
OWNER_STRAYS = {"COVERS/IMG_0002.jpg": "booklet-01.jpg"}

MOOD = "TXXX:MOOD"
OWNER_COVER = "owner/cover.png"


def catalogue() -> list[list[dict]]:
    pairs = {case: release(number, artist, folder, titles) for case, (number, artist, folder, titles)
             in CASES.items()}
    # A release group with no genre at all leaves the plan with a problem to hold on.
    pairs["decision-hold"][1]["genres"] = []
    group = pairs["soundtrack-choice"][1]
    group["secondary-types"] = ["Soundtrack"]
    pairs["soundtrack-choice"][0]["release-group"]["secondary-types"] = ["Soundtrack"]
    return [[found, group] for found, group in pairs.values()]


def stage(tmp: Path, case: str) -> Path:
    """`tmp/<case>/01/drop/album/<folder>/` with tagged MP3s and a cover, as agitha stages it."""
    number, artist, folder, titles = CASES[case]
    found, _group = release(number, artist, folder, titles)
    base = tmp / case / "01" / "drop" / "album" / folder
    base.mkdir(parents=True)
    for n, title in enumerate(titles, start=1):
        path = base / f"{n:02d} {title.lower()}.mp3"
        shutil.copyfile(builders.FIXTURES / "tone.mp3", path)
        fields = {"title": [title.lower()], "artist": [artist], "album": [folder], "date": ["1989"],
                  "release id": [found["id"]]}
        builders.write_tags(path, builders.picard_tags("mp3", fields, track=(n, len(titles)), disc=(1, 1)),
                            v2_version=4)
        if case == "raw-edits-owner-cover":
            builders.write_tags(path, {MOOD: "Calm"}, v2_version=4)
    if case == "missing-track":
        # A truncated track: agitha leaves it out and holds the album on `missing`.
        (base / "02 two.mp3").write_bytes(TRUNCATED)
    if case == "stray-images":
        for rel, data in STRAYS.items():
            (base / rel).parent.mkdir(parents=True, exist_ok=True)
            (base / rel).write_bytes(data)
        for name, data in ROOT_IMAGES.items():
            (base / name).write_bytes(data)
    shutil.copyfile(builders.FIXTURES / "cover.jpg", base / "cover.jpg")
    return base


def identify(tmp: Path, case: str, catalogue_path: Path) -> Path:
    root, job = tmp / case / "01", tmp / case / "jobs" / JOB_NAME
    env = {**os.environ, "AGITHA_STUB_CATALOGUE": str(catalogue_path)}
    # agitha asks for the unreadable files to be left out; without the flag the album is not planned.
    flags = ["--drop-unreadable"] if case == "missing-track" else []
    done = subprocess.run([sys.executable, str(STUB), "batch", "identify", str(root), "--job", str(job), *flags],
                          env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if done.returncode:
        sys.exit(done.stderr)
    return job


def accept(job: Path, folder: str, found: dict, **more) -> None:
    """Write `decisions.json` accepting `found` for the album in `folder`, with `more` in the accept."""
    decisions = {"job": JOB_NAME, "albums": {f"drop/album/{folder}": {
        "action": "accept", "release_id": found["id"], "edits": {}, "game": None, **more}}}
    (job / "decisions.json").write_text(json.dumps(decisions, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    pairs = catalogue()
    catalogue_path = HERE / "catalogue.json"
    catalogue_path.write_text(json.dumps(pairs, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        for case, (number, artist, folder, titles) in CASES.items():
            stage(tmp, case)
            job = identify(tmp, case, catalogue_path)
            if case == "raw-edits-owner-cover":
                # A neutral edit, a raw one and a removal, with the owner's cover: the page's Update preview.
                found = pairs[number - 1][0]
                owner = job / "owner"
                owner.mkdir()
                Image.new("RGB", (600, 600), (200, 40, 40)).save(owner / "cover.png")
                decisions = {"job": JOB_NAME, "albums": {f"drop/album/{folder}": {
                    "action": "accept", "release_id": found["id"], "cover": OWNER_COVER,
                    "edits": {"1-2": {"title": ["Two, Edited"]}, "1-1": {"TCOM": ["Someone"], MOOD: None}}}}}
                (job / "decisions.json").write_text(json.dumps(decisions, indent=2, sort_keys=True) + "\n",
                                                    encoding="utf-8")
                job = identify(tmp, case, catalogue_path)
            if case == "decision-hold":
                # The owner accepts an album whose plan has a problem: identify holds it on `decision`.
                accept(job, folder, pairs[number - 1][0])
                job = identify(tmp, case, catalogue_path)
            if case == "missing-track":
                # Accepting the release names the missing track, and the hold stays: it is never approvable.
                accept(job, folder, pairs[number - 1][0])
                job = identify(tmp, case, catalogue_path)
            if case == "stray-images":
                # The owner names one stray with no guess and leaves the other undecided.
                accept(job, folder, pairs[number - 1][0], strays=OWNER_STRAYS)
                job = identify(tmp, case, catalogue_path)
            out = HERE / case
            out.mkdir(exist_ok=True)
            plan = (job / "plan.json").read_text(encoding="utf-8").replace(str(tmp / case / "01"), BOX_ROOT)
            (out / "plan.json").write_text(plan, encoding="utf-8")
            if (job / "owner").is_dir():
                shutil.copytree(job / "owner", out / "owner", dirs_exist_ok=True)
            if (job / "decisions.json").is_file():
                shutil.copyfile(job / "decisions.json", out / "decisions.json")


if __name__ == "__main__":
    main()
