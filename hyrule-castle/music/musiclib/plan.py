"""The full intended state of one album unit, judged before anything is written.

`plan_album` is pure once the MusicBrainz and Cover Art Archive clients' cache
is warm: it never touches the album's own files, only reads them (through the
`Unit` it is given) and the release it is told to plan against. It builds
every track's tag target (`mapping.plan_tags`), the album's images
(`images.plan_images`), where everything moves to (`names`), and then judges
the whole result the same way `musiclib check` judges a tree already on disk
(`state_from_plan` plus `check.check_album`), so a plan and a finished write
are never held to different rules.

A unit that cannot be planned at all - it needs a person, or a file could not
be read - comes back as a `Plan` holding only that problem and no files.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from musiclib import ascii as ascii_
from musiclib import artists, check, composers, files, genres, images, mapping, names, strays as strays_module
from musiclib.caa import CoverArtError
from musiclib.mb import VARIOUS_ARTISTS, MusicBrainzError, MusicBrainzNotFound, MusicBrainzUnavailable
from musiclib.strays import Stray
from musiclib.units import DISAGREEMENT, NEEDS_A_PERSON, TrackPair, Unit, counted_media, disc_number, group_media, pair

_CAA_UNAVAILABLE = "cover art archive unavailable"

_NO_COVER_ARCHIVE_FAILED = ("no cover: the cover art archive is unavailable and the files carry none; "
                            "upload a cover or identify again")
_NO_COVER_NO_FRONT = "no cover: the cover art archive has no front and the files carry none; upload a cover"

#: A destination name over this many UTF-8 bytes is refused: ext4, the
#: filesystem the box writes to, holds 255 bytes a name regardless of how
#: many characters that is.
_MAX_NAME_BYTES = 255


@dataclass
class FilePlan:
    """One track's move and tag target. `source`/`destination` are relative to `Plan.root`.

    `fingerprint` is the source file's tags and audio fingerprint as they
    were at planning time, so `write_album` can refuse a plan the file has
    moved on from since. `None` for a plan built by hand rather than by
    `plan_album`, which skips the check rather than refuse a plan that never
    had one to compare against.
    """

    source: str
    destination: str
    target: dict[str, list[str]]
    removals: list
    fingerprint: tuple[dict, str] | None = None


@dataclass
class Plan:
    """The full intended state of one album unit.

    `files` covers only the tracks. `deletions`, `extras` and `kept` are
    every other file the unit already has, sorted the way `check` sorts them
    (`check.classify_other`), as paths relative to `root`. `cover.jpg` is in
    none of them: it is never deleted, and lives in `images` instead.
    `problems` stops the album being written; `holds` and `suggestions` do not,
    they only keep it out of `certain`/`auto`.
    """

    root: Path
    source: str
    destination: str
    release_id: str | None
    status: str
    files: list[FilePlan]
    images: dict[str, bytes]
    embedded: bytes | None
    deletions: list[str]
    extras: list[str]
    kept: list[str]
    holds: list[str]
    suggestions: dict[str, str]
    problems: list[str]
    consumed: str | None = None
    #: Each stray and its answer, in natural order of path (`strays.settle`).
    strays: list[Stray] = field(default_factory=list)
    #: A kept stray's path from `root` (the form of `kept`) to the name it takes in the album folder.
    moved: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> bytes:
        """Canonical bytes for comparing two plans, sorted keys and UTF-8 throughout.

        `root` is left out: two copies of the same rip sit at different
        absolute paths, and a plan naming one would never compare equal to a
        plan of the other. Image and embedded bytes are digested rather than
        carried whole, since Pillow and libjpeg differ across machines
        (`plan.md`, *Cannot be verified here*) and a plan is not the place to
        settle that; the digest is still enough to catch a plan that changed
        which bytes it would write. The archive hold is compared without
        the requests it names, see `_comparable`.
        """

        def digest(data: bytes) -> dict:
            return {"sha256": hashlib.sha256(data).hexdigest(), "length": len(data)}

        def removal(item) -> dict:
            return {"key": item.key, "value": item.value, "rule": item.rule}

        doc = {
            "source": self.source,
            "destination": self.destination,
            "release_id": self.release_id,
            "status": self.status,
            "files": [
                {"source": f.source, "destination": f.destination, "target": f.target,
                 "removals": [removal(r) for r in f.removals]}
                for f in self.files
            ],
            "images": {name: digest(data) for name, data in self.images.items()},
            "embedded": digest(self.embedded) if self.embedded is not None else None,
            "deletions": list(self.deletions),
            "extras": list(self.extras),
            "kept": list(self.kept),
            "consumed": self.consumed,
            "holds": [_comparable(hold) for hold in self.holds],
            "suggestions": dict(self.suggestions),
            "problems": list(self.problems),
            "strays": [stray.to_json() for stray in self.strays],
            "moved": dict(self.moved),
        }
        return json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")


def _comparable(hold: str) -> str:
    """`hold` as two plans compare it: the archive hold keeps only the fallback it names.

    Which request the archive failed and with what status is the story of one
    run, not of the plan: a listing that answered 500 at identify and an image
    that answered 503 at apply leave the same cover and the same files, and
    `batch apply` must not refuse that album as changed. The hold itself still
    names every failure, for the owner.
    """
    if hold.startswith(f"{_CAA_UNAVAILABLE}: "):
        return f"{_CAA_UNAVAILABLE}; {hold.rsplit('; ', 1)[1]}"
    return hold


def _dedupe(items) -> list:
    """`items`, first-seen order, duplicates dropped.

    Several tracks can carry the exact same problem (no DATE anywhere, say),
    and the owner reading the plan needs to see it once, not once per track.
    """
    seen: set = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _blocked(unit: Unit, root: Path, status: str | None, reasons: list[str]) -> Plan:
    """A `Plan` for a unit that is never planned: just the problem, no files."""
    source = unit.path.relative_to(root).as_posix()
    return Plan(
        root=root, source=source, destination=source, release_id=None,
        status=status or "review", files=[], images={}, embedded=None,
        deletions=[], extras=[], kept=[], holds=[], suggestions={},
        problems=_dedupe(reasons),
    )


def is_compilation(release: dict) -> bool:
    """Whether MusicBrainz credits the release to Various Artists alone."""
    credit = release.get("artist-credit") or []
    return len(credit) == 1 and credit[0].get("artist", {}).get("id") == VARIOUS_ARTISTS


def _album_date(release: dict, tracks: list[files.Track]) -> str | None:
    """The date for naming the album folder: MusicBrainz's, else the first file's own.

    Mirrors `mapping._kept_or_mb`'s per-field fallback, but once for the
    whole album rather than once per track: the folder is one name, not one
    per file.
    """
    mb_date = mapping.release_date(release)
    if mb_date:
        return mb_date
    for track in tracks:
        key = mapping.PICARD["date"].get(track.family)
        if not key:
            continue
        values = track.tags.get(key)
        if values and values[0]:
            return values[0]
    return None


def _track_disc_folder(unit_path: Path, tracks: list[files.Track]) -> str | None:
    """The one subfolder every track of this medium sits in, or `None`.

    Feeds `mapping.plan_tags`'s `disc_folder`, which only ever suggests a
    `DISCSUBTITLE` from a name every track of the medium agrees on.
    """
    found = {Path(t.path).relative_to(unit_path).parts[0]
             for t in tracks if len(Path(t.path).relative_to(unit_path).parts) > 1}
    return found.pop() if len(found) == 1 else None


def _album_genres(release_group: dict, tracks: list[files.Track], release: dict,
                  owner_input: dict, incoming: str | None, mb) -> list[str]:
    """The album's genres, the same list for every track."""
    file_genres: list[str] = []
    for track in tracks:
        key = mapping.PICARD["genre"].get(track.family)
        if not key:
            continue
        for value in track.tags.get(key, []):
            if value not in file_genres:
                file_genres.append(value)
    composer = genres.composer(release)
    choice = genres.owner_choice(owner_input, release.get("id"))
    if choice is None:
        custom = genres.custom_genre(release_group, file_genres, incoming)
    else:
        custom = None if choice == genres.NEITHER else choice

    def artist_genres() -> list[dict]:
        try:
            return mb.artist(composer).get("genres", [])
        except MusicBrainzUnavailable:
            raise
        except MusicBrainzError:
            # An unusable answer for this one artist only costs the fallback.
            return []

    return genres.compose(custom, release_group.get("genres", []), file_genres,
                          artist_genres if composer is not None else None)


#: A folder file larger than this is not read, so nothing is judged a copy of
#: it and it stays, under its own name. The figure is a memory bound, well above any booklet scan.
_MAX_COMPARED_BYTES = 64 * 1024 * 1024


def _loose_files(unit: Unit) -> dict[str, bytes]:
    """The bytes, by name, of each non-track file directly in the album folder.

    A file too large to read still has its name here, so nothing is planned
    over it. Its value is a placeholder unique to it, so it never compares
    equal to any other file's bytes.
    """
    found = {}
    for rel in unit.others:
        path = unit.path / rel
        try:
            if "/" not in rel:
                found[rel] = (path.read_bytes() if path.stat().st_size <= _MAX_COMPARED_BYTES
                              else f"\0unread:{rel}".encode())
        except OSError:
            continue
    return found


def _disc_folders(unit: Unit) -> set[str]:
    """The first-level folders holding a track, whatever they are called."""
    return {parts[0] for track in unit.tracks
            if len(parts := Path(track.path).relative_to(unit.path).parts) == 2}


def stray_paths(unit: Unit) -> list[str]:
    """The strays among `unit.others`, relative to the album, in natural order of path.

    A file `check` keeps under a folder that is not a disc folder, an image
    inside a disc folder, and an image at the root that no rule already names.
    """
    discs = _disc_folders(unit)
    found = []
    for rel in unit.others:
        if check.classify_other(unit.path / rel, rel) != "keep":
            continue
        parts = PurePosixPath(rel).parts
        image = strays_module.kind(rel) == "image"
        if len(parts) == 1:
            stray = image and strays_module.is_root_stray(rel)
        else:
            stray = parts[0] not in discs or image
        if stray:
            found.append(rel)
    return sorted(found, key=strays_module.path_order)


def _stray_bytes(unit: Unit, rel: str) -> bytes:
    """The bytes of the stray `rel`; a file too large to compare gets a placeholder no other file equals."""
    path = unit.path / rel
    try:
        if path.stat().st_size > _MAX_COMPARED_BYTES:
            return f"\0unread:{rel}".encode()
        return path.read_bytes()
    except OSError:
        return f"\0unreadable:{rel}".encode()


def lay_strays(unit: Unit, settled: Sequence[Stray], deletions: list[str], kept: list[str]
               ) -> tuple[list[str], list[str], dict[str, str]]:
    """`(deletions, kept, moved)` once each stray of `settled` has gone where its answer sends it.

    `deletions` and `kept` are `sort_others`'s, which leave every stray in
    `kept`: a deleted one moves to `deletions`, a kept one to `moved` under
    its new name, an undecided one stays in `kept`. A file at the root that
    a stray won its name from is deleted too. Run by both `plan_album` and
    `batch.memory.lay_edits` from the plan's own strays, so the two agree.
    """
    deletions, kept, moved = list(deletions), list(kept), {}
    decided = {f"{unit.rel}/{stray.path}" for stray in settled if stray.answer is not None}
    undecided = [f"{unit.rel}/{stray.path}" for stray in settled if stray.answer is None]
    kept = [rel for rel in kept if rel not in decided]
    # `sort_others` deletes any file named like a planned image, a stray in a subfolder included;
    # a stray is settled here alone, or it would be moved and then unlinked, or left undecided and deleted.
    deletions = [rel for rel in deletions if rel not in decided and rel not in undecided]
    kept += [rel for rel in undecided if rel not in kept]
    for stray in settled:
        full = f"{unit.rel}/{stray.path}"
        if stray.keeps is not None:
            moved[full] = stray.keeps
        elif stray.answer is not None:
            deletions.append(full)
    beaten = {strays_module.name_key(stray.keeps) for stray in settled if stray.why == "won"}
    stray_rels = {stray.path for stray in settled}
    for rel in unit.others:
        full = f"{unit.rel}/{rel}"
        if "/" not in rel and rel not in stray_rels and strays_module.name_key(rel) in beaten:
            kept = [path for path in kept if path != full]
            if full not in deletions:
                deletions.append(full)
    return deletions, kept, moved


def sort_others(unit: Unit, image_names: set[str], moving: bool, consumed: str | None = None,
                created: Sequence[str] = ()) -> tuple[list[str], list[str], list[str]]:
    """`unit.others`, paths relative to the album, sorted into (deletions, extras, kept).

    An existing file whose name a planned image occupies (`image_names`,
    casefolded: always `cover.jpg`, plus any other image the rules place by a
    fixed name) is never a "kept" file - `images` is where a caller finds
    what replaces it - and it is a deletion only when the album is moving: an
    album that stays gets that name overwritten in place, case and all, by
    `write._write_images`, and marking it deleted as well would remove a file
    the write goes on to replace. `consumed`, a folder file that became
    `cover.jpg` under another name, is always a deletion, and so is an
    archive-named copy of the owner's own file (`images.redundant_archive_names`) and a file `created` (the earlier job's
    images) left behind in the album's folder.

    `batch.memory.lay_edits` sorts again when an edit moves the album: the two
    sorts must delete the same files.
    """
    redundant = {name for name in images.redundant_archive_names(_loose_files(unit))
                 if name.casefold() not in image_names}
    deletions, extras, kept = [], [], []
    for rel in unit.others:
        full = f"{unit.rel}/{rel}"
        if rel == consumed or rel in redundant:
            deletions.append(full)
            continue
        if PurePosixPath(rel).name.casefold() in image_names:
            if moving:
                deletions.append(full)
            continue
        # The real path, still on disk at planning time, so an `.mp4` video
        # is told from `.mp4` audio the same way `read_album` tells them
        # apart: by content, not just by name.
        kind = check.classify_other(unit.path / rel, rel)
        # "unexpected" (a type the doc neither allows, removes nor moves to
        # extras, such as a `.torrent`) is deleted with the junk: nothing
        # of a type the doc does not list comes into the library.
        (deletions if kind in ("delete", "unexpected") else extras if kind == "extra" else kept).append(full)
    left_behind = {PurePosixPath(path).name for path in created if PurePosixPath(path).parent.as_posix() == unit.rel}
    for name in sorted(left_behind):
        full = f"{unit.rel}/{name}"
        if name.casefold() not in image_names and name in unit.others:
            extras[:] = [p for p in extras if p != full]
            kept[:] = [p for p in kept if p != full]
            if full not in deletions:
                deletions.append(full)
    return deletions, extras, kept




def _without_brackets(value: str) -> str:
    """`value` fit for a folder suffix, which holds one pair of brackets of its own.

    A value wholly wrapped in one `[...]` (MusicBrainz names an area
    `[Worldwide]`) loses the wrap, and any other bracket becomes a parenthesis.
    """
    value = value.strip()
    if value.startswith("[") and value.endswith("]") and not re.search(r"[\[\]]", value[1:-1]):
        value = value[1:-1]
    return value.replace("[", "(").replace("]", ")").strip()


def _told_apart(release: dict, release_group: dict, mb) -> dict:
    """`release` titled `Group title (Comment) rest` where its artist has another release group of the same title.

    The comment is the release group's disambiguation, which is how
    MusicBrainz tells Weezer's self-titled albums apart ("Green Album", "Red
    Album"). It goes straight after the group's title, so the Blue Album's
    `Weezer (deluxe edition)` becomes `Weezer (Blue Album) (deluxe edition)`,
    and at the end of a release title that does not start with it. The album
    tag carries it, and the folder with it, so jean and the library show the
    albums apart too. A release group without one, or a compilation, keeps
    its title.
    """
    comment = _without_brackets(release_group.get("disambiguation") or "")
    credit = release.get("artist-credit") or []
    group_title = release_group.get("title") or ""
    if not comment or not credit or not group_title or is_compilation(release):
        return release
    own = release["release-group"]["id"]
    others = mb.artist_release_groups(credit[0]["artist"]["id"])
    if not any(g["id"] != own and g.get("title", "").casefold() == group_title.casefold() for g in others):
        return release
    title = release["title"]
    head = len(group_title) if title.casefold().startswith(group_title.casefold()) else len(title)
    return {**release, "title": f"{title[:head]} ({comment}){title[head:]}"}


def edition_fields(release: dict) -> list[str]:
    """What tells `release` from another edition, in the order a folder suffix prefers it.

    The disambiguation comment, the country's name and the format of the
    media that hold audio; each `""` where the release has none, and free
    of brackets (`_without_brackets`).
    """
    events = [e.get("area") or {} for e in release.get("release-events", [])]
    named = next((a for a in events if release.get("country") in a.get("iso-3166-1-codes", [])), None)
    named = named or (events[0] if events else {})
    country = named.get("name") or ""
    media = release.get("media", [])
    formats: list[str] = []
    for counted in counted_media(release):
        name = media[counted.index - 1].get("format")
        if name and name not in formats:
            formats.append(name)
    return [_without_brackets(value) for value in (release.get("disambiguation") or "", country, " + ".join(formats))]


def folder_artist_name(credit: list[dict], mb) -> str:
    return ascii_.to_ascii(artists.credited_name(credit, mb))


def _archive_hold(failures: Sequence[tuple[str, str]], image_plan: images.ImagePlan) -> str:
    if image_plan.cover_from is None:
        cover = "there is no cover"
    else:
        cover = "the cover is " + {
            "owner": "the owner's",
            "archive": "the archive's front",
            "embedded": "the files' embedded front",
            "folder": f"the folder's {image_plan.cover_name}",
        }[image_plan.cover_from]
    listed = "; ".join(f"{url} -> {status}" for url, status in dict.fromkeys(failures))
    return f"{_CAA_UNAVAILABLE}: {listed}; {cover}"


def _embedded_front(unit: Unit, pairs: Sequence[TrackPair] | None) -> bytes | None:
    if pairs is None:
        tracks = list(unit.tracks)
    else:
        tracks = [p.file for medium in sorted({p.medium for p in pairs}) for p in pairs if p.medium == medium]
    return images.first_embedded_front([Path(track.path) for track in tracks])


def plan_album(
    unit: Unit, release: dict, mb, caa, owner_input: dict | None = None,
    incoming: str | None = None, status: str | None = None,
    pairs: list[TrackPair] | None = None, edition: str | None = None,
    local: Sequence[tuple[str, bytes]] | None = None, created: Sequence[str] = (),
    owner_cover: bytes | None = None, composer: bool = True, chosen: bool = False,
    added: str | None = None, strays: Mapping[str, str | None] | None = None,
) -> Plan:
    """The full intended state of `unit`, planned against `release`.

    `edition` ends the album folder in brackets (`names.album_folder`).

    `local` stands in for the album folder's own covers (`images.local_covers`)
    when given: they come from another folder, so the file that becomes
    `cover.jpg` is never `consumed`, and nothing in this folder is deleted
    for sharing its name. `created` is the images an earlier job saved in this
    folder (paths from the library root) that a changed release leaves behind:
    each is deleted unless the plan writes its name again, and none counts as
    a copy of an image the plan would save.

    `owner_cover` is the owner's own image for `cover.jpg` (`images.plan_images`).

    `composer` lays each track's composers from MusicBrainz's work
    relationships over the file's composer tags (`composers`), at one more
    lookup per release. Off, those tags are left as the file has them.

    `added`, an import's `YYYY-MM-DDTHH:MM`, is every track's `ADDED` (`mapping.plan_tags`).

    `strays` is the owner's answer for each stray, a path relative to the
    album to a name or `None` to delete it (`strays.settle`).
    """
    owner_input = owner_input or {}
    root = unit.path.parents[2]

    settled = chosen and unit.status == NEEDS_A_PERSON and (unit.reason or "").startswith(DISAGREEMENT)
    if unit.status and not settled:
        return _blocked(unit, root, status, [f"{unit.status}: {unit.reason}"])
    if unit.unreadable:
        return _blocked(unit, root, status,
                        [f"unreadable: {rel}: {reason}" for rel, reason in unit.unreadable])

    source = unit.path.relative_to(root).as_posix()
    problems: list[str] = []

    latin = mb.latin_releases(release)
    if latin:
        release = mapping.with_titles_of(release, latin[0])

    release_group = mb.release_group(release["release-group"]["id"])
    release = _told_apart(release, release_group, mb)
    album_genres =_album_genres(release_group, unit.tracks, release, owner_input, incoming, mb)

    stray_rels = stray_paths(unit)
    stray_bytes = {rel: _stray_bytes(unit, rel) for rel in stray_rels}
    # A root stray is not a file "already there": an archive image equal to one is saved, and the stray is the copy.
    loose = _loose_files(unit)
    folder_files = {name: data for name, data in loose.items() if name not in stray_bytes}
    left_behind = {PurePosixPath(path).name for path in created if PurePosixPath(path).parent.as_posix() == unit.rel}
    redundant = set(images.redundant_archive_names(loose))
    discs = {folder: number for folder in _disc_folders(unit) if (number := disc_number(folder)) is not None}
    answered: list[Stray] = []

    if pairs is None:
        pairs = pair(unit, release)
    files_front = _embedded_front(unit, pairs) if local is None else None

    try:
        caa_images = caa.images(release["id"])
        listing_failure = None
    except CoverArtError as exc:
        caa_images, listing_failure = [], (exc.url, exc.status)

    def plan_images(local_covers, existing):
        failures = [] if listing_failure is None else [listing_failure]

        def download(url: str) -> bytes | None:
            try:
                return caa.download(url)
            except CoverArtError as exc:
                failures.append((exc.url, exc.status))
                return None

        def group_listing() -> list[dict]:
            try:
                return caa.release_group_images(release["release-group"]["id"])
            except CoverArtError as exc:
                failures.append((exc.url, exc.status))
                return []

        # With the release's listing failed, the group's is not asked in its place: it could name a
        # different edition's front.
        group_images = group_listing if listing_failure is None else (lambda: [])
        plan = images.plan_images(
            caa_images, download, group_images=group_images, local=local_covers,
            owner_cover=owner_cover, existing=existing, embedded=files_front)
        return plan, failures + [(url, "not an image") for url in plan.unreadable]

    folder_covers = images.local_covers(unit.path) if local is None else list(local)
    existing = {name: data for name, data in folder_files.items() if name not in left_behind}
    image_plan, failures = plan_images(folder_covers, existing)
    staying = {name: data for name, data in existing.items() if name not in redundant}
    answered = strays_module.settle(
        stray_bytes, discs, strays or {}, image_plan.files.get("cover.jpg"),
        {name: data for name, data in image_plan.files.items() if name != "cover.jpg"}, staying)
    kept_strays = {stray.keeps: stray_bytes[stray.path] for stray in answered if stray.keeps is not None}
    # A stray kept as `front.*` is a local cover like one already in the folder, so the archive's front
    # is judged against it: the plan is made again with it in. Only here, after the copy rule
    # has run, so that the stray is never deleted as a copy of the cover it became.
    fronts = [(name, data) for name, data in kept_strays.items()
              if Path(name).stem == "front" and Path(name).suffix in images.LOCAL_SUFFIXES]
    if fronts:
        covers = sorted([*folder_covers, *fronts],
                        key=lambda c: (images.LOCAL_STEMS.index(Path(c[0]).stem.casefold()), c[0].casefold()))
        image_plan, failures = plan_images(covers, {**existing, **kept_strays})
    taken = {strays_module.name_key(name) for name in kept_strays}
    for name in [n for n in image_plan.files if n != "cover.jpg" and strays_module.name_key(n) in taken]:
        del image_plan.files[name]

    problems.extend(p for p in image_plan.problems if p != images.NO_FRONT)
    if image_plan.no_cover:
        problems.append(_NO_COVER_ARCHIVE_FAILED if failures else _NO_COVER_NO_FRONT)
    embedded = images.embedded_front(image_plan.files["cover.jpg"]) if "cover.jpg" in image_plan.files else None

    album_date = _album_date(release, unit.tracks)
    credit = release.get("artist-credit") or []
    # The folder is built from the same converted text as the tag beside it,
    # never MusicBrainz's raw name, so the two never disagree over a curly
    # quote or an ellipsis.
    artist_name = folder_artist_name(credit, mb)
    artist_sort = ascii_.to_ascii(mapping.join_credit(credit, "sort-name"))
    compilation = is_compilation(release)
    artist_folder = names.artist_folder(artist_name, artist_sort, known=True, compilation=compilation)
    letter = names.letter(artist_folder)
    album_title = ascii_.to_ascii(release["title"])
    if album_date:
        release_group_info = release.get("release-group", {})
        album_folder = names.album_folder(
            album_date, album_title, release_group_info.get("primary-type"),
            tuple(release_group_info.get("secondary-types", [])),
            ascii_.to_ascii(edition) if edition else None,
        )
        destination = f"{letter}/{artist_folder}/{album_folder}"
    else:
        # names.album_folder cannot take a missing date: with none anywhere,
        # the album cannot be named, so the destination stays put and the
        # mapping problem below (from every track) is what stops the write.
        destination = source

    composed: dict[str, list[tuple[str, str]]] = {}
    if composer:
        try:
            composed = composers.composers_by_recording(mb.release_works(release["id"]), mb)
        except MusicBrainzNotFound:
            # Only a 404 means no composers; any other refusal holds the album.
            composed = {}

    file_plans: list[FilePlan] = []
    holds: list[str] = list(image_plan.holds)
    if failures:
        holds.append(_archive_hold(failures, image_plan))
    if settled:
        holds.append(f"{unit.status}: {unit.reason}")
    suggestions: dict[str, str] = {}
    if pairs is None:
        disk_counts = [len(tracks) for tracks in group_media(unit)]
        release_counts = [len(medium.tracks) for medium in counted_media(release)]
        # A per-medium mismatch would tag every file after it against the
        # wrong recording, and an extra medium on disk has no recording at
        # all: neither is a plan `check` could rescue, so no file is planned.
        problems.append(
            f"file counts do not match the release: {disk_counts} files per medium on disk, "
            f"release has {release_counts} tracks per medium"
        )
    else:
        for medium_index in sorted({p.medium for p in pairs}):
            medium_pairs = [p for p in pairs if p.medium == medium_index]
            disc_folder_name = _track_disc_folder(unit.path, [p.file for p in medium_pairs])
            for pair_ in medium_pairs:
                track = pair_.file
                planned = mapping.plan_tags(track, release, medium_index, pair_.position, album_genres,
                                            disc_folder=disc_folder_name, number=pair_.number,
                                            total=pair_.total, disc=pair_.disc, discs=pair_.discs,
                                            credited_name=lambda c: artists.credited_name(c, mb), added=added)
                problems.extend(planned.problems)
                holds.extend(planned.holds)
                people = composed.get(pair_.mb_track["recording"]["id"])
                if people:
                    planned.target.update(composers.tags(people, track.family))
                if planned.suggested_discsubtitle and disc_folder_name:
                    suggestions[disc_folder_name] = planned.suggested_discsubtitle

                title_key = mapping.PICARD["title"][track.family]
                title = planned.target[title_key][0]
                ext = Path(track.path).suffix.lstrip(".")
                filename = names.track_filename(pair_.number, title, ext, pair_.total)
                disc_dir = names.disc_folder(pair_.disc, pair_.discs)
                dest_rel = f"{destination}/{disc_dir}/{filename}" if disc_dir else f"{destination}/{filename}"
                for part in PurePosixPath(dest_rel).parts:
                    length = len(part.encode("utf-8"))
                    if length > _MAX_NAME_BYTES:
                        problems.append(
                            f"{part!r} is too long for a file name: {length} bytes, over {_MAX_NAME_BYTES}"
                        )
                source_rel = Path(track.path).relative_to(root).as_posix()
                fingerprint = (dict(track.tags), files.audio_fingerprint(track))
                file_plans.append(FilePlan(source=source_rel, destination=dest_rel,
                                           target=planned.target, removals=planned.removals,
                                           fingerprint=fingerprint))

    # `cover.jpg` (in any case) is always in this set, whether or not the
    # archive has a front for the release: with no front, the rip's own is
    # what `image_plan.files["cover.jpg"]` already carries forward.
    image_names = {"cover.jpg"} | {name.casefold() for name in image_plan.files}
    consumed = image_plan.consumed if local is None else None
    deletions, extras, kept = sort_others(unit, image_names, source != destination, consumed, created)
    deletions, kept, moved = lay_strays(unit, answered, deletions, kept)

    plan = Plan(
        root=root, source=source, destination=destination, release_id=release.get("id"),
        status="review" if holds else (status or "review"),
        files=file_plans, images=image_plan.files, embedded=embedded,
        deletions=deletions, extras=extras, kept=kept,
        holds=_dedupe(holds), suggestions=suggestions, problems=[], consumed=consumed,
        strays=answered, moved=moved,
    )

    problems.extend(f"{v.rule}: {v.detail}" for v in check.check_album(state_from_plan(plan), suffix_given=edition is not None))
    plan.problems = _dedupe(problems)
    return plan


def relocated(plan: Plan, rel: str) -> str:
    """Where `rel` (a path under `plan.source`, e.g. one of `plan.kept` or `plan.extras`) lands once the album moves.

    Shared with `write.write_album`: a kept file follows the album folder in
    the library, and an extra follows the same tail under `extras_root`
    instead - either way, only the part of the path above `plan.source`
    changes. Equal to `rel` itself when the album is not moving
    (`plan.source == plan.destination`).
    """
    tail = PurePosixPath(rel).relative_to(plan.source).as_posix()
    return f"{plan.destination}/{tail}"


def changes(plan: Plan) -> list[str]:
    """Every change writing `plan` would still make, judged against `plan.root` as it is right now.

    Unlike `plan_album` itself, this reads the files: a track's tag target
    is compared to a fresh `files.read`, since the plan may have been built
    before, or long after, the tags on disk last changed. The album's cover
    and every track's embedded picture are compared to the plan's own bytes
    directly, not through the tag snapshot: neither `mapping.plan_tags` nor
    `tagwrite.merge` ever touches an image key, so a track's planned target
    always carries the same digest the file already has for it, and a diff
    against `target` alone would never see a picture that changed.
    """
    out: list[str] = []

    for file_plan in plan.files:
        if file_plan.source != file_plan.destination:
            out.append(f"move: {file_plan.source} -> {file_plan.destination}")

        current = files.read(plan.root / file_plan.source)
        if current.tags != file_plan.target:
            out.append(f"tags: {file_plan.source}: does not match its planned target")

        pictures = [data for _type, data in images.embedded_pictures(plan.root / file_plan.source)]
        expected = [] if plan.embedded is None else [plan.embedded]
        if pictures != expected:
            out.append(f"cover: {file_plan.source}: embedded picture does not match the plan")

    for name, data in sorted(plan.images.items()):
        path = plan.root / plan.source / name
        if not path.is_file() or path.read_bytes() != data:
            out.append(f"image: {plan.source}/{name}: does not match the plan")

    for rel in plan.kept:
        destination = relocated(plan, rel)
        if destination != rel:
            out.append(f"move: {rel} -> {destination}")

    for rel, name in sorted(plan.moved.items()):
        out.append(f"move: {rel} -> {plan.destination}/{name}")

    for rel in plan.deletions:
        out.append(f"delete: {rel}")

    for rel in plan.extras:
        out.append(f"extra: {rel}: moves out of the library")

    return out


def state_from_plan(plan: Plan) -> check.AlbumState:
    """The `check.AlbumState` `plan` will have once written, judged by the same rules as `check`.

    An MP3 track is always ID3v2.4 with no ID3v1: that is what every write
    produces, never something `check_album` has to be told about per track.
    Every track carries one embedded front cover, the size `embedded` will
    actually be; with no `embedded` at all (no cover anywhere), no track has
    one either.
    """
    cover_size = None
    if plan.embedded is not None:
        from PIL import Image
        import io

        cover_size = Image.open(io.BytesIO(plan.embedded)).size

    parts = PurePosixPath(plan.destination).parts
    letter, artist, folder = (parts + ("", "", ""))[:3]

    tracks = []
    for file_plan in plan.files:
        rel = PurePosixPath(file_plan.destination).relative_to(plan.destination)
        family = _family_of(file_plan.destination)
        track = files.Track(path=file_plan.destination, family=family,
                            tags=file_plan.target, length=0.0)
        tracks.append(check.TrackState(
            filename=rel.name, disc_dir=rel.parts[0] if len(rel.parts) > 1 else None,
            track=track, front_covers=1 if plan.embedded is not None else 0,
            cover_size=cover_size, id3_version=(2, 4, 0) if family == "id3" else None,
            has_id3v1=False,
        ))

    prefix = f"{plan.source}/"
    # `plan.kept` already went through `sort_others`, which sorted a video
    # out to `plan.extras` with the real file in hand - so `classify_other`
    # never needs a path here to answer "keep" or "unexpected" for what is
    # left, only the name (`check.classify_other`'s own docstring).
    other_files = tuple(
        (stripped, check.classify_other(None, stripped))
        for stripped in (rel[len(prefix):] if rel.startswith(prefix) else rel for rel in plan.kept)
    )
    subdirs: set[str] = set()
    for file_plan in plan.files:
        rel = PurePosixPath(file_plan.destination).relative_to(plan.destination)
        if len(rel.parts) > 1:
            subdirs.add(rel.parts[0])
    for rel, _kind in other_files:
        parts = PurePosixPath(rel).parts
        if len(parts) > 1:
            subdirs.add(parts[0])

    return check.AlbumState(
        # Two plans of the same rip must give byte-identical `to_json()`
        # regardless of the interpreter's hash seed, and `subdirs` feeds
        # `check_album`'s "subfolder" problems in whatever order this tuple
        # holds.
        album=Path(plan.destination), letter=letter, artist=artist, folder=folder,
        tracks=tuple(tracks), other_files=other_files, subdirs=tuple(sorted(subdirs)),
        has_cover_jpg="cover.jpg" in plan.images,
        # A plan never carries an unreadable file: `plan_album` refuses the
        # unit before it gets this far (`unit.unreadable`, above).
        unreadable=(),
    )


def _family_of(destination: str) -> str:
    return files.FAMILY_BY_EXTENSION.get(Path(destination).suffix.lower(), "vorbis")
