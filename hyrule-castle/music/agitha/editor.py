"""A hand edit, planned: `POST /api/library/preview`.

`plan` turns a draft into one `AlbumPlan` per album it names (`albumplan`):
each track's tags before and after, where each file and the album folder
would sit (`planpaths`), the rules the draft newly breaks (`planrules`), and
the keys it may not touch. It reads the library and writes nothing, so the
save runs the same function and then writes what the plan says.

A draft is a list of edits applied in order, each to the tracks it names. A
key is a readable name (`Genre`) or a format's own key (`TCON`, `genre`,
`TXXX:MOOD`). A draft that says it is a batch (`batch`) is planned album by
album with the rules of `batch`, whatever the number of albums.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from musiclib import check, files, genres, mapping, names, tagwrite

from . import batch, covers, drops, library, planpaths, planrules
from .albumplan import AlbumPlan, TrackPlan
from .refusal import ALBUM_CHANGED, SKIP_CHANGED, SKIP_OPEN, Refusal

if TYPE_CHECKING:
    from .server import Config, Handler

ONE_FORMAT = "is one format's own key; edit one format at a time"

_KINDS = ("set", "add", "remove")

Changes = dict[str, dict[str, list[str] | None]]


class Edit(NamedTuple):
    """One edit of a draft: the tracks it names by album, and `{set|add|remove: {key: values}}`."""

    paths: dict[str, set[str]]
    changes: Changes
    #: Whether the tracks it names, in every album, are of more than one format.
    mixed: bool


class Stamp(NamedTuple):
    """What the page showed of one track: its file's size and mtime, and the values of the keys the draft names."""

    #: `{size, mtime}`, or `None` where the draft sent none.
    loaded: dict[str, Any] | None
    seen: dict[str, list[str] | None]


class Draft(NamedTuple):
    #: `(album, path)` of each track the draft lists.
    tracks: list[tuple[str, str]]
    edits: list[Edit]
    stamps: dict[tuple[str, str], Stamp]
    #: Album-relative pairs of tracks that trade places; they belong to the draft's one album.
    swaps: list[tuple[str, str]]
    #: The cover token as the draft sent it, not yet checked.
    cover: Any
    #: Whether the draft is a batch: each album planned or left out, and the tags of `batch.PAGE_TAGS` refused.
    batch: bool


class AlbumEdit(NamedTuple):
    """An edit as it reaches one album: the album-relative paths it names there."""

    paths: set[str]
    changes: Changes
    mixed: bool


class AlbumDraft(NamedTuple):
    """The part of a draft that is one album's."""

    path: str
    folder: Path
    paths: set[str]
    edits: list[AlbumEdit]
    #: Album-relative pairs of tracks that trade places, after the edits.
    swaps: list[tuple[str, str]]
    cover: str | None
    batch: bool


def _malformed(what: str) -> Refusal:
    return Refusal(400, f"The draft is malformed: {what}.")


def _track_ref(entry: Any) -> tuple[str, str]:
    if not (isinstance(entry, dict) and isinstance(entry.get("album"), str) and isinstance(entry.get("path"), str)):
        raise _malformed("a track names no album and path")
    return entry["album"], entry["path"]


def _stamp(entry: dict[str, Any]) -> Stamp:
    loaded, seen = entry.get("loaded"), entry.get("seen", {})
    if not (loaded is None or isinstance(loaded, dict)) or not isinstance(seen, dict):
        raise _malformed("a track's loaded must be an object and its seen an object")
    return Stamp(loaded, {key: _values(values, key, nullable=True) for key, values in seen.items()})


def _swaps(found: Any) -> list[tuple[str, str]]:
    """The pairs of `swaps`: each two different paths, no path in two pairs."""
    if not isinstance(found, list):
        raise _malformed("swaps must be a list")
    pairs = []
    for pair in found:
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(path, str) for path in pair)):
            raise _malformed("a swap must name two tracks")
        if pair[0] == pair[1]:
            raise _malformed("a swap must name two different tracks")
        pairs.append((pair[0], pair[1]))
    paths = [path for pair in pairs for path in pair]
    if len(set(paths)) != len(paths):
        raise _malformed("a track may be in one swap only")
    return pairs


def _values(value: Any, key: str, nullable: bool) -> list[str] | None:
    if value is None and nullable:
        return None
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise _malformed(f"{key} must hold a list of text values" + (" or null" if nullable else ""))


def _edit(raw: Any) -> Edit:
    if not (isinstance(raw, dict) and isinstance(raw.get("tracks"), list)):
        raise _malformed("an edit names no tracks")
    refs = [_track_ref(entry) for entry in raw["tracks"]]
    paths: dict[str, set[str]] = {}
    for album, path in refs:
        paths.setdefault(album, set()).add(path)
    changes: Changes = {}
    for kind in _KINDS:
        found = raw.get(kind, {})
        if not isinstance(found, dict):
            raise _malformed(f"{kind} must be an object")
        changes[kind] = {key: _values(values, key, nullable=kind == "set") for key, values in found.items()}
    formats = {files.FAMILY_BY_EXTENSION.get(Path(path).suffix.lower()) for _album, path in refs}
    return Edit(paths, changes, len(formats) > 1)


def _check_listed(tracks: list[tuple[str, str]], edits: list[Edit], swaps: list[tuple[str, str]], cover: Any,
                  batch_flag: bool) -> None:
    """Refuses a draft that contradicts itself: no track, more albums than a draft that is not a batch takes, or an edit or swap over a track it does not list."""
    if not tracks:
        raise _malformed("the draft lists no track")
    if not batch_flag and len({album for album, _path in tracks}) > 1:
        raise _malformed("a draft that is not a batch names one album")
    if batch_flag and (swaps or cover is not None):
        raise _malformed("swaps and a cover are for a draft that is not a batch")
    listed = set(tracks)
    if any((album, path) not in listed for edit in edits for album, paths in edit.paths.items() for path in paths):
        raise _malformed("an edit names a track the draft does not list")
    if any(path not in {track for _album, track in tracks} for pair in swaps for path in pair):
        raise _malformed("a swap names a track the draft does not list")


def parse(body: Any) -> Draft:
    """The draft `body` says, or a 400 where it is malformed in itself; nothing is read from the library."""
    if not (isinstance(body, dict) and isinstance(body.get("tracks"), list) and isinstance(body.get("edits"), list)):
        raise _malformed("tracks and edits must be lists")
    batch_flag = body.get("batch")
    if not isinstance(batch_flag, bool):
        raise _malformed("batch must be true or false")
    edits = [_edit(raw) for raw in body["edits"]]
    tracks = [_track_ref(entry) for entry in body["tracks"]]
    swaps, cover = _swaps(body.get("swaps", [])), body.get("cover")
    _check_listed(tracks, edits, swaps, cover, batch_flag)
    return Draft(tracks, edits, {ref: _stamp(entry) for ref, entry in zip(tracks, body["tracks"])},
                 swaps, cover, batch_flag)


def _named_tag(key: str) -> tuple[str, dict[str, str]] | None:
    """The readable name `key` stands for and the keys it means, by format, or `None` where it has no name.

    A readable name means each format's own key for it. A format's own key
    means itself, in the formats that call the tag that.
    """
    if key in mapping.READABLE:
        return key, {family: own for family, own in mapping.READABLE[key].items() if own is not None}
    for name, row in mapping.READABLE.items():
        own = {family: held for family, held in row.items()
               if held is not None and (held == key or (family == "vorbis" and held.casefold() == key.casefold()))}
        if own:
            return name, own
    return None


def _readable_name(key: str) -> str:
    found = _named_tag(key)
    return found[0] if found else key


def _resolve(key: str, family: str) -> tuple[str | None, str | None]:
    """`(the file's own key, None)`, `(None, why the key is refused)`, or `(None, None)` where the key is not for this format."""
    found = _named_tag(key)
    if found is None:
        # A Vorbis field name has no case; files read as lower case.
        real = key.lower() if family == "vorbis" else key
    else:
        real = found[1].get(family)
        if real is None:
            # A readable name a format does not hold is refused; a format's own key is only for its own files.
            return None, "is not held by this format" if key in mapping.READABLE else None
    offence = library.key_offence(family, real)
    return (None, offence) if offence else (real, None)


def _off_the_list(values: list[str]) -> str | None:
    unknown = [value for value in values if value not in genres.OFFICIAL and value not in library.CUSTOM_GENRES]
    return f"has names that are not on MusicBrainz's genre list: {', '.join(unknown)}" if unknown else None


def _lay(track: TrackPlan, shown: str, real: str, new: list[str] | None) -> None:
    """Sets the file's own key `real` on `track` to `new`, and names it `shown` among the tags the draft touches."""
    if all(real != other for _, other in track.named):
        track.named.append((shown, real))
    track.after = tagwrite.merge(files.Track(path=track.path, family=track.family, tags=track.after,
                                             length=track.length), {real: new})


def _edit_track(track: TrackPlan, kind: str, key: str, values: list[str] | None) -> str | None:
    """Lays one change of `key` on `track`; answers why the key is refused for it, or `None`."""
    real, why = _resolve(key, track.family)
    if real is not None and kind != "remove" and values and real == mapping.PICARD["genre"][track.family]:
        why = _off_the_list(values)
    if why or real is None:
        return why
    held = track.after.get(real) or []
    if kind == "set":
        new = list(values) if values else None
    elif kind == "add":
        new = held + [value for value in dict.fromkeys(values or []) if value not in held] or None
    else:
        new = [value for value in held if value not in (values or [])] or None
    _lay(track, _readable_name(key), real, new)
    return None


def apply_edits(tracks: list[TrackPlan], edits: list[AlbumEdit], refused_names: frozenset[str]) -> list[dict[str, str]]:
    """Lays each edit over the tracks it names, in order; answers the keys refused, once each, in draft order.

    A key whose readable name is in `refused_names`, by whatever name or
    format's own key it comes, is refused with `batch.ON_ITS_PAGE`; a key no
    format's table names, in an edit over more than one format, is refused
    with `ONE_FORMAT`. Nothing is laid for either.
    """
    refused: dict[str, str] = {}
    rank: dict[str, int] = {}
    for edit in edits:
        for kind in _KINDS:
            for key, values in edit.changes[kind].items():
                if _readable_name(key) in refused_names:
                    refused.setdefault(key, batch.ON_ITS_PAGE)
                    continue
                if edit.mixed and _named_tag(key) is None:
                    refused.setdefault(key, ONE_FORMAT)
                    continue
                rank.setdefault(_readable_name(key), len(rank))
                for track in tracks:
                    if track.path in edit.paths and (why := _edit_track(track, kind, key, values)):
                        refused.setdefault(key, why)
    for track in tracks:
        track.named.sort(key=lambda pair: rank[pair[0]])
    return [{"key": key, "reason": reason} for key, reason in refused.items()]


#: What a swap moves with the position, by readable name, besides the two numbers: the title and credits, the
#: lyrics, the MusicBrainz ids, and the twins of those tags (the composer's sort order, the disc's subtitle).
_POSITION = ("Title", "Artist", "Artist sort order", "Composer", "Composer sort order", "Lyrics",
             "MusicBrainz recording id", "MusicBrainz track id", "MusicBrainz artist id", "Disc subtitle")
_NUMBERS = ("Track number", "Disc number")


def _renumbered(held: list[str] | None, own: str | None, taken: str | None) -> list[str] | None:
    """`held` with `taken` in place of its leading number `own`, so an `n/total` keeps its total; `[taken]` where it has none, `None` where `taken` is none."""
    if taken and own and held:
        return [library.LEADING_NUMBER.sub(taken, held[0], count=1)]
    return [taken] if taken else None


def _trade(one: TrackPlan, other: TrackPlan) -> None:
    """Each of the two tracks takes the other's place: its numbers, its title and credits, its MusicBrainz ids.

    The audio, the rating, ReplayGain and the play history stay in the file
    they are in. A tag moves on to the other format's own key, a tag the
    other lacks moves as an absence, and a number replaces only the number
    of the `n/total` the file holds, so each file keeps its own total.
    """
    mine, theirs = dict(one.after), dict(other.after)
    for name in (*_NUMBERS, *_POSITION):
        key_one, key_other = mapping.READABLE[name].get(one.family), mapping.READABLE[name].get(other.family)
        if key_one is None or key_other is None:
            continue
        got_one, got_other = mine.get(key_one), theirs.get(key_other)
        if name in _NUMBERS:
            number_one, number_other = library.leading_digits(got_one), library.leading_digits(got_other)
            new_one = _renumbered(got_one, number_one, number_other)
            new_other = _renumbered(got_other, number_other, number_one)
        else:
            new_one, new_other = got_other, got_one
        if new_one != got_one:
            _lay(one, name, key_one, new_one)
        if new_other != got_other:
            _lay(other, name, key_other, new_other)


def apply_swaps(tracks: list[TrackPlan], swaps: list[tuple[str, str]]) -> None:
    by_path = {track.path: track for track in tracks}
    for first, second in swaps:
        if first not in by_path or second not in by_path:
            raise _malformed("a swap names a track the album does not hold")
        _trade(by_path[first], by_path[second])


class Plan(NamedTuple):
    #: One plan for each album the draft's tracks name, in the order it names them.
    albums: list[AlbumPlan]
    #: The albums with a listed track that is gone, or whose file differs from what the page loaded in a tag the draft names.
    stale: set[str]


class _Stale(Exception):
    """An album no longer holds a track the draft lists."""


def _plan_album(config: Config, album: AlbumDraft) -> AlbumPlan:
    root = library.library_root(config)
    found, _unreadable = library.read_tracks(config, album.path, album.folder)
    if not album.paths <= {track["path"] for track in found}:
        raise _Stale
    state = check.read_album(album.folder, root)
    read = {Path(track.track.path).relative_to(album.folder).as_posix(): track for track in state.tracks}
    tracks = []
    for track in found:
        # The view shows a picture by its size; the rules and the writer need the file's own value.
        engine = read.get(track["path"])
        tags = engine.track.tags if engine else track["tags"]
        tracks.append(TrackPlan(path=track["path"], new_path=track["path"], family=track["family"], before=tags,
                                after=dict(tags), named=[], length=track["length"], state=engine))
    refused = apply_edits(tracks, album.edits, batch.PAGE_TAGS if album.batch else frozenset())
    apply_swaps(tracks, album.swaps)
    plan = AlbumPlan(album.path, album.path, tracks, [], refused)
    if album.cover is not None:
        plan.cover, plan.cover_token = covers.describe(covers.read(config, album.cover)), album.cover
    if album.batch:
        # A batch moves nothing, so only the engine's rules are judged.
        plan.problems = planrules.engine_rules(root, album.folder, state, plan) if tracks else []
    elif tracks:
        plan.new_path, plan.edition = planpaths.album_path(tracks, album.path)
        planpaths.name_files(tracks, any(names.DISC_DIR_RE.match(track.path.split("/")[0])
                                         for track in tracks if "/" in track.path))
        plan.problems = [*planpaths.folder_taken(root, album.folder, plan),
                         *planpaths.file_collisions(album.folder, plan),
                         *planrules.shared_numbers(plan),
                         *planrules.engine_rules(root, album.folder, state, plan)]
    return plan


def _album_draft(draft: Draft, album: str, folder: Path) -> AlbumDraft:
    return AlbumDraft(
        path=album, folder=folder, paths={path for named, path in draft.tracks if named == album},
        edits=[AlbumEdit(edit.paths[album], edit.changes, edit.mixed) for edit in draft.edits if album in edit.paths],
        swaps=draft.swaps, cover=draft.cover, batch=draft.batch)


def _open_albums(config: Config, draft: Draft) -> tuple[dict[str, Path], set[str]]:
    """The folder of each album the draft names, and the albums with a listed track that is not there.

    A path that leaves the library, wherever the draft names it, is a 404.
    """
    root = library.library_root(config)
    folders = {album: library.open_album(config, album) for album in dict.fromkeys(a for a, _path in draft.tracks)}
    gone = {album for album, path in draft.tracks if library.find_file(folders[album], root, path) is None}
    return folders, gone


def plan(config: Config, draft: Draft) -> Plan:
    """The plan of `draft`: one for each album it names, with which albums are stale. Reads; never writes."""
    folders, gone = _open_albums(config, draft)
    albums = list(dict.fromkeys(album for album, _path in draft.tracks))
    if draft.batch:
        return _plan_batch(config, draft, albums, folders, gone)
    return _plan_single(config, draft, albums[0], folders, gone)


def _plan_single(config: Config, draft: Draft, album: str, folders: dict[str, Path], gone: set[str]) -> Plan:
    """The album page's draft: refused as a whole where a track is gone. Whether the page is out of date is for the save to act on."""
    if gone:
        raise Refusal(409, ALBUM_CHANGED)
    try:
        plans = [_plan_album(config, _album_draft(draft, album, folders[album]))]
    except _Stale:
        raise Refusal(409, ALBUM_CHANGED) from None
    return Plan(plans, _stale_albums(config, draft, plans, folders))


def _plan_batch(config: Config, draft: Draft, albums: list[str], folders: dict[str, Path], gone: set[str]) -> Plan:
    """Each album planned or, with the reason in `skip`, left out so the others go on. Only a stale album is left out for being stale."""
    in_review = drops.open_matches(config)
    plans = []
    for album in albums:
        if album in in_review:
            plans.append(AlbumPlan(album, album, [], [], [], skip=SKIP_OPEN))
        elif album in gone:
            plans.append(AlbumPlan(album, album, [], [], [], skip=SKIP_CHANGED))
        else:
            try:
                plans.append(_plan_album(config, _album_draft(draft, album, folders[album])))
            except _Stale:
                plans.append(AlbumPlan(album, album, [], [], [], skip=SKIP_CHANGED))
    stale = _stale_albums(config, draft, plans, folders)
    for one in plans:
        if one.skip is None:
            one.skip = batch.skip_reason(one, one.path in stale)
    return Plan(plans, stale)


def _stale_albums(config: Config, draft: Draft, plans: list[AlbumPlan], folders: dict[str, Path]) -> set[str]:
    """The albums with a listed track whose file differs from what the page loaded in a tag the draft names, or is gone.

    A file whose size and mtime are as loaded is not read again. A changed
    size or mtime alone is no change: a rating written meanwhile moves both.
    """
    root = library.library_root(config)
    tracks = {(one.path, track.path): track for one in plans for track in one.tracks}
    planned = {one.path for one in plans if one.tracks}
    found: set[str] = set()
    for (album, path), stamp in draft.stamps.items():
        if album in found or album not in planned:
            continue
        track = tracks.get((album, path))
        file = library.find_file(folders[album], root, path)
        stat = file.stat() if file else None
        if track is None or stat is None:
            found.add(album)
        elif stamp.loaded is not None and stamp.loaded == {"size": stat.st_size, "mtime": stat.st_mtime}:
            continue
        else:
            for key, shown in stamp.seen.items():
                real, _why = _resolve(key, track.family)
                if real is not None and (track.before.get(real) or None) != (shown or None):
                    found.add(album)
    return found


def preview(request: Handler, match: re.Match[str], config: Config) -> None:
    draft = parse(request.read_json())
    request.send_json(200, {"albums": [album.answer() for album in plan(config, draft).albums]})
