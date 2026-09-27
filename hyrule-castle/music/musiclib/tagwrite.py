"""Merging a plan into a file's tags, and writing the result under verify.

A rating is never touched, a field nobody planned is kept apart from the
forbidden duplicates, and an MP3 comes out as ID3v2.4 with no ID3v1.
"""

from __future__ import annotations

import re

from mutagen.id3 import COMM, Frames, POPM, TXXX, UFID, USLT
from mutagen.mp4 import AtomDataType, MP4FreeForm

from musiclib import files

#: Vorbis fields the docs call ratings (*Tags*, *Ratings*). MP4 has none.
_VORBIS_RATING_KEYS = {"rating", "fmps_rating"}

#: The three kept-as-written groups, each named ignoring case wherever a
#: free-form name can be carried (an MP3 TXXX description, a Vorbis field, an
#: MP4 `----` atom's name, or an ASF attribute) - the same reach as
#: `residue._freeform_rule`.
_LYRICS_NAMES = {
    "lyrics", "unsyncedlyrics", "unsynced lyrics",
    "unsynchronised lyrics", "unsynchronized lyrics",
}
_PLAY_HISTORY_NAMES = {
    "first_played", "last_played", "play_count", "play_counter",
    "play_stamp", "added",
}
_MACHINE_WRITTEN_NAMES = {"major_brand", "minor_version", "compatible_brands"}

#: The native, non-freeform lyrics frame/atom/attribute a ripper or player
#: writes itself: ID3 USLT and SYLT, MP4's own lyrics atom, ASF's own.
_MP4_NATIVE_LYRICS = "\xa9lyr"
_ASF_NATIVE_LYRICS = "wm/lyrics"

#: iTunes normalisation and gapless data written into a plain comment:
#: spaces, each followed by a group of 8 to 16 hexadecimal digits, and
#: nothing else. This shape is kept in a comment only, so a copy of the same
#: digits sitting in an unrelated field still breaks `whitespace`.
_ITUNES_BLOB = re.compile(r"^(?: [0-9A-Fa-f]{8,16})+$")


class VerifyError(Exception):
    """A write did not read back as the target it was given."""


def is_rating_key(family: str, key: str) -> bool:
    if family == "id3":
        if key.startswith("POPM:"):
            return True
        return key.startswith("TXXX:") and key[len("TXXX:"):].lower() == "fmps_rating"
    if family == "vorbis":
        return key in _VORBIS_RATING_KEYS
    return False


def is_picture_key(family: str, key: str) -> bool:
    """Whether `key` holds an embedded picture rather than a plannable tag.

    A rollback must never touch a picture: `files.snapshot` digests one
    rather than keeping its bytes (`files.py`, `snapshot`), so a prior value
    here is not something a rollback could write back even if it tried. FLAC
    keeps no picture in its Vorbis comments at all (`mutagen` holds it on the
    file object's own `.pictures`), so it never reaches here.
    """
    if family == "id3":
        return key.startswith("APIC:")
    if family == "mp4":
        return key == "covr"
    if family == "vorbis":
        return key == "metadata_block_picture"
    if family == "asf":
        return key == "WM/Picture"
    return False


def is_forbidden_duplicate(family: str, key: str) -> bool:
    """The exception to keeping unplanned fields, and *No duplicate fields* in the docs.

    Vorbis keeps its own totals in `TRACKTOTAL`/`DISCTOTAL`, so only the
    `TXXX` totals on MP3 are the forbidden kind; a Vorbis or MP4 total field
    is the proper one and stays.
    """
    if family == "id3":
        if not key.startswith("TXXX:"):
            return False
        desc = key[len("TXXX:"):].lower()
        return desc in ("year", "album artist", "tracktotal", "totaltracks",
                        "disctotal", "totaldiscs")
    if family == "vorbis":
        return key in ("year", "album artist")
    if family == "mp4":
        if not key.startswith("----:"):
            return False
        name = key.rsplit(":", 1)[-1].lower()
        return name in ("year", "album artist")
    # ASF falls through to False too: no duplicate of this shape has turned
    # up in a WMA file yet, so there is nothing yet to name here.
    return False


def _freeform_name(family: str, key: str) -> str | None:
    """The lower-cased free-form name `key` carries, or `None` if `key` is
    not shaped like one in `family` (an MP3 TXXX description, a Vorbis
    field, an MP4 `----` atom's name, or an ASF attribute)."""
    if family == "id3":
        if key.startswith("TXXX:"):
            return key[len("TXXX:"):].lower()
        return None
    if family == "vorbis":
        return key.lower()
    if family == "mp4":
        if key.startswith("----:"):
            return key.rsplit(":", 1)[-1].lower()
        return None
    if family == "asf":
        return key.lower()
    return None


def _is_named(family: str, key: str, names: set[str]) -> bool:
    return _freeform_name(family, key) in names


def is_lyrics_field(family: str, key: str) -> bool:
    """The lyrics fields: the one list `residue` and `tagwrite` both read."""
    if family == "id3":
        if key.startswith("USLT:") or key.startswith("SYLT:"):
            return True
    elif family == "mp4":
        if key == _MP4_NATIVE_LYRICS:
            return True
    elif family == "asf":
        if key.lower() == _ASF_NATIVE_LYRICS:
            return True
    return _is_named(family, key, _LYRICS_NAMES)


def _is_comment_field(family: str, key: str) -> bool:
    """A field the docs call a comment, where iTunes also writes its
    normalisation and gapless data as plain text, alongside the exact frames
    the residue denylist strips whole."""
    if family == "id3":
        return key.startswith("COMM:") or (
            key.startswith("TXXX:") and key[len("TXXX:"):].lower() == "comment")
    if family == "vorbis":
        return key == "comment"
    if family == "mp4":
        return key == "\xa9cmt"
    return False


def keeps_whitespace(family: str, key: str, value: str) -> bool:
    """`value` in `key` is kept exactly as written: `check` and `mapping`'s
    one shared answer to what the whitespace rules never touch.

    A rating is never changed at all. Lyrics, play history and
    machine-written values are exempt from the whitespace cleaning and from
    `check`'s `whitespace` rule, because collapsing spaces inside a sung
    line, a timestamp or an iTunes blob would corrupt it rather than tidy
    it. The comment case is the one exemption that reads the value: only
    the exact iTunes blob shape is kept, so a comment that merely starts
    with a space still breaks `whitespace`.
    """
    if is_rating_key(family, key):
        return True
    if is_lyrics_field(family, key):
        return True
    if _is_named(family, key, _PLAY_HISTORY_NAMES):
        return True
    if _is_named(family, key, _MACHINE_WRITTEN_NAMES):
        return True
    return _is_comment_field(family, key) and bool(_ITUNES_BLOB.match(value))


def has_line_break(value: str) -> bool:
    """A value holding a line break is kept as it is."""
    return "\n" in value or "\r" in value


def is_non_text_key(family: str, key: str) -> bool:
    """`check` and `mapping`'s one shared answer to whether `key` even holds
    text: a digest, an MP4 pair, or an embedded picture, none of which the
    whitespace rules can read as a string."""
    if family == "id3":
        frame_id = key.split(":", 1)[0]
        if frame_id in ("APIC", "PRIV", "GEOB", "USER", "UFID", "POPM"):
            return True
        return len(frame_id) == 4 and frame_id[0] == "W"
    if family == "mp4":
        return key in ("trkn", "disk", "covr")
    if family == "vorbis":
        return key == "metadata_block_picture"
    if family == "asf":
        return key == "WM/Picture"
    return False


def merge(track: files.Track, planned: dict) -> dict:
    """The file's tags with `planned` applied.

    `planned` names real keys to set (a list of values) or remove (`None`).
    Anything it does not name is kept as-is. A rating key is never changed,
    whether `planned` tries to set, remove or add one: this is the only place
    left to enforce it, where every caller's plan passes through. The
    forbidden duplicates are dropped whether or not the plan mentions them,
    since a well-formed plan never should.
    """
    result = dict(track.tags)
    for key, value in planned.items():
        if is_rating_key(track.family, key):
            continue
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    for key in list(result):
        if is_forbidden_duplicate(track.family, key):
            del result[key]
    return result


def _split_hashkey(key: str) -> tuple[str, str, str]:
    """`"COMM:desc:lang"` -> `("COMM", "desc", "lang")`, tolerating a `:` in `desc`."""
    frame_id, _, rest = key.partition(":")
    desc, _, lang = rest.rpartition(":")
    return frame_id, desc, lang


def _build_id3_frame(key: str, values: list[str]):
    """The frame `key: values` in `Track.tags` becomes, to write it back.

    Only reached for a key whose value actually changed, so this never has
    to reconstruct a digested frame (`APIC`, `PRIV`, ...) from its digest:
    those are always either kept untouched or deleted, never rewritten.
    `UFID` is the one keyed, non-text frame this does rebuild, since its
    value is decoded text (the recording MBID) rather than a digest.
    """
    if key.startswith("POPM:"):
        email = key[len("POPM:"):]
        rating = count = 0
        for part in values[0].split(","):
            name, _, val = part.partition("=")
            if name == "rating":
                rating = int(val)
            elif name == "count":
                count = int(val)
        return POPM(email=email, rating=rating, count=count)
    if key.startswith("TXXX:"):
        return TXXX(encoding=3, desc=key[len("TXXX:"):], text=list(values))
    if key.startswith("UFID:"):
        return UFID(owner=key[len("UFID:"):], data=values[0].encode("utf-8"))
    if key.startswith("COMM:"):
        _, desc, lang = _split_hashkey(key)
        return COMM(encoding=3, lang=lang or "XXX", desc=desc, text=list(values))
    if key.startswith("USLT:"):
        _, desc, lang = _split_hashkey(key)
        return USLT(encoding=3, lang=lang or "XXX", desc=desc, text=values[0] if values else "")
    if key in Frames:
        return Frames[key](encoding=3, text=list(values))
    raise ValueError(f"cannot write an ID3 frame for {key!r}")


def _mp4_value(key: str, values: list[str]):
    """The native mp4 shape for `Track.tags`' text form of `key`'s values.

    A freeform atom is written explicitly as UTF-8, so it survives even if
    mutagen's own default ever changes. `trkn`/`disk` come back from
    `files.mp4_pair_text` and go through its inverse.
    """
    if key in ("trkn", "disk"):
        return [files.mp4_pair_value(v) for v in values]
    if key.startswith("----:"):
        return [MP4FreeForm(v.encode("utf-8"), AtomDataType.UTF8) for v in values]
    return list(values)


def _identity_value(key: str, values: list[str]) -> list[str]:
    return list(values)


def _apply(path: str, family: str, target: dict) -> None:
    """Open `path` fresh and save it with its tags equal to `target`.

    Always saves, even when nothing changed: an MP3 written this way is
    always ID3v2.4 with no ID3v1, whatever version or trailer it had before.
    Exactly one call reaches mutagen's own save, so a caller that patches it
    to inject a fault sees it exactly once here. ID3 keeps its own branch,
    since a frame has to be rebuilt rather than assigned; Vorbis, MP4 and ASF
    all behave like a plain mapping, and differ only in how MP4 turns a
    `trkn`/`disk` pair or a freeform atom back into its native shape.
    """
    audio = files.load(path)
    live = files.snapshot(audio, family)
    # Two plans of the same rip must write byte-identical files regardless of
    # the interpreter's hash seed.
    to_delete = sorted(set(live) - set(target))
    to_set = {k: v for k, v in target.items() if live.get(k) != v}

    # A backstop against a hash-randomized key order creeping in upstream:
    # writing `to_set` in a fixed order keeps two runs of the same plan
    # byte-identical even if some future `target` were built in an order
    # that is not.
    if family == "id3":
        tags = audio.tags
        for key in to_delete:
            tags.delall(key)
        for key, values in sorted(to_set.items()):
            tags.delall(key)
            tags.add(_build_id3_frame(key, values))
        audio.save(v1=0, v2_version=4)
        return

    tags = audio.tags
    value_of = _mp4_value if family == "mp4" else _identity_value
    for key in to_delete:
        if key in tags:
            del tags[key]
    for key, values in sorted(to_set.items()):
        tags[key] = value_of(key, values)
    audio.save()


def _expected(family: str, target: dict) -> dict:
    """`target`, adjusted for what mutagen actually keeps on disk.

    Mutagen never writes an ID3 text frame whose text is empty, so a file
    that already carries one loses it on the very next save, whether or not
    that frame was touched. Comparing the plan as-is against what comes back
    would then read as a verify failure for a save that did exactly what it
    should.
    """
    if family != "id3":
        return dict(target)
    return {k: v for k, v in target.items()
            if not (v and all(x == "" for x in v) and k[:1] == "T")}


def write(track: files.Track, target: dict) -> files.Track:
    """Make the file at `track.path` carry exactly `target`, verified.

    Every tag is read back and compared against `target` (adjusted for what
    mutagen drops on save), and the audio fingerprint must not have moved.
    On any mismatch the file's tags are set back to `track.tags` - not a
    byte backup, a second verified write of the values already known to be
    right - and `VerifyError` is raised.
    """
    live = track.tags
    rating_keys = {k for k in live if is_rating_key(track.family, k)}
    rating_keys |= {k for k in target if is_rating_key(track.family, k)}
    if any(live.get(k) != target.get(k) for k in rating_keys):
        raise ValueError("a plan may not set, change or remove a rating")

    before_fingerprint = files.audio_fingerprint(track)
    _apply(track.path, track.family, target)

    after = files.read(track.path)
    expected = _expected(track.family, target)
    if after.tags != expected or files.audio_fingerprint(after) != before_fingerprint:
        _apply(track.path, track.family, track.tags)
        raise VerifyError(f"{track.path}: write did not verify")
    return after
