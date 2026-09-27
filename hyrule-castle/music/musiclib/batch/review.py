"""`review.render`: the self-contained HTML page a `plan.json` becomes.

The grouping, the hold reasons, the candidates, the before/after of every
tag and path that changes, every deletion/extra/kept-file move and image,
and an input for every field the engine would write, are all built here in
Python, from the parsed `plan.json` alone, with no disk or network access of
its own. `review.css` and `review.js`, beside this file, are read once and
inlined: the page opens from `file://` with nothing beside it, so nothing
here may reference them, or anything else, from outside. (They live next to
this file rather than under a `data/` subdirectory because the repo's
`.gitignore` ignores every `data/` anywhere in the tree.)

An album already carrying a decision (`decision`, `release_id`, `game` -
identify folded a `decisions.json` back in) is rendered pre-selected: the
matching radio, candidate and game choice start checked, and
`#decisions-skeleton` starts from that decision rather than a blanket skip,
so exporting an untouched page never turns a fold back into one.

`render` must be deterministic: no timestamps, and every dict this module
walks is walked in sorted key order, however the caller happened to build it.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

_HERE = Path(__file__).parent

Album = dict[str, Any]
Doc = dict[str, Any]

#: Neutral fields (`mapping.PICARD`) that describe the release itself rather
#: than one recording: edited once on the page, the value goes into every
#: position. Track- and recording-scoped fields (title, artist, the sort
#: fields that follow them, discsubtitle, the MusicBrainz recording/track/
#: artist ids) are left out on purpose, since two tracks on the same album
#: can legitimately differ there.
ALBUM_WIDE_FIELDS = {
    "album", "albumartist", "albumartistsort", "date", "originaldate", "genre",
    "label", "catalognumber", "barcode", "asin", "releasecountry", "media",
    "release id", "release group id", "album artist id",
}


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _join(values: list[str]) -> str:
    return ", ".join(values)


def _script_json(id_: str, obj: Any) -> str:
    """`<script type="application/json">`, safe against a `</script>` or a
    `<!--` anywhere inside the value.

    Replacing only `</script` is not enough (a `<!--` earlier in the same
    value still confuses a real browser's tokenizer), so every `<`, `>` and
    `&` becomes a JSON `\\u` escape instead of an HTML entity: script content
    is never entity-decoded, so an HTML entity here would reach `json.loads`
    unparsed, but a JSON string escape is exactly what `json.loads` expects.
    """
    text = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    text = text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return f'<script type="application/json" id="{id_}">{text}</script>'


# --- one file's before/after -------------------------------------------

def _file_block(f: dict) -> str:
    rows = []
    if f["source"] != f["destination"]:
        rows.append(f'<div data-path>{_esc(f["source"])} → {_esc(f["destination"])}</div>')
    before, after = f.get("before", {}), f.get("after", {})
    for key in sorted(set(before) | set(after)):
        b, a = before.get(key, []), after.get(key, [])
        if b == a:
            continue
        rows.append(f'<div data-tag="{_esc(key)}">{_esc(key)}: {_esc(_join(b))} → {_esc(_join(a))}</div>')
    # The full source path is already the file's `data-file`, invisible to a
    # reader; the basename is enough to tell tracks apart under one album
    # heading, and far shorter than repeating the whole rel path per track.
    name = f["source"].rsplit("/", 1)[-1]
    return f'<div data-file="{_esc(f["source"])}">{_esc(name)}' + "".join(rows) + "</div>"


# --- reasons, candidates, residue, inputs -------------------------------

def _holds_block(holds: list[dict]) -> str:
    if not holds:
        return ""
    # Kind beside detail on one line: a `reopened` hold carries no detail at
    # all, and a line with only its (empty) detail would read as blank.
    items = "".join(
        f'<li>{_esc(h["kind"])}: {_esc(h["detail"])}</li>' if h["detail"] else f'<li>{_esc(h["kind"])}</li>'
        for h in holds
    )
    return f"<ul>{items}</ul>"


def _candidate_block(c: dict, album_key: str, checked: bool) -> str:
    checked_attr = " checked" if checked else ""
    # The MBID is visible text, not just the radio's value: the owner
    # compares it against MusicBrainz by eye.
    return (
        f'<label><input type="radio" name="candidate-{_esc(album_key)}" '
        f'value="{_esc(c["release_id"])}"{checked_attr}>'
        f'<img src="{_esc(c["thumbnail"])}" alt="">'
        f'{_esc(c.get("title", ""))} — {_esc(c.get("artist", ""))} '
        f'({_esc(c.get("date", ""))}) {_esc(c["release_id"])}'
        "</label>"
    )


def _residue_block(residue: list[dict]) -> str:
    if not residue:
        return ""
    items = []
    for r in residue:
        text = r["key"] if r["value"] is None else f'{r["key"]}={r["value"]}'
        items.append(f'<li data-residue>{_esc(text)} ({_esc(r["rule"])}) {_esc(r["file"])}</li>')
    return f'<ul>{"".join(items)}</ul>'


def _tail(entry: Album, rel: str) -> str:
    """The part of `rel` below the album folder."""
    return rel[len(entry["source"]) + 1:]


def _relocated(entry: Album, rel: str) -> str:
    """Where `rel` lands after the write: `destination` plus the tail below
    `source`, `musiclib.plan.relocated`'s own rule, recomputed here rather
    than imported so this module never needs 001's tag stack for one string
    operation - the docstring's promise that the page is built from
    `plan.json` alone.
    """
    return entry["destination"] + rel[len(entry["source"]):]


def _deletion_block(entry: Album) -> str:
    if not entry["deletions"]:
        return ""
    items = "".join(
        f'<li data-deletion="{_esc(rel)}">{_esc(_tail(entry, rel))}</li>' for rel in entry["deletions"]
    )
    return f"<ul>{items}</ul>"


def _extra_block(entry: Album) -> str:
    if not entry["extras"]:
        return ""
    items = "".join(
        f'<li data-extra="{_esc(rel)}">{_esc(_tail(entry, rel))} → {_esc(_relocated(entry, rel))}</li>'
        for rel in entry["extras"]
    )
    return f"<ul>{items}</ul>"


def _kept_block(entry: Album) -> str:
    if not entry["kept"]:
        return ""
    items = "".join(
        f'<li data-kept="{_esc(rel)}">{_esc(_tail(entry, rel))} → {_esc(_relocated(entry, rel))}</li>'
        for rel in entry["kept"]
    )
    return f"<ul>{items}</ul>"


def _image_block(images: dict) -> str:
    if not images:
        return ""
    items = "".join(f'<li data-image="{_esc(name)}">{_esc(name)}</li>' for name in sorted(images))
    return f"<ul>{items}</ul>"


def _position_key(position: str) -> tuple[int, int]:
    """Sorts `"<medium>-<track>"` numerically, so track 10 does not land
    before track 2 the way sorting the strings would."""
    medium, track = position.split("-")
    return int(medium), int(track)


def _field_input(field: str, value: str, position: str | None) -> str:
    # A field name as a plain text label, not a wrapping <label>/<span>: it
    # still reads fine, and at this multiplicity (tens of thousands of these
    # across a real library) the saved tags are most of what trimmed the page.
    position_attr = f' data-position="{_esc(position)}"' if position is not None else ""
    return f'{_esc(field)} <input data-field="{_esc(field)}"{position_attr} value="{_esc(value)}"> '


def _field_inputs(fields: dict[str, dict[str, list[str]]]) -> str:
    """One `<input>` per value: a single-value field gets one, a multi-value
    field one per value.

    A field in `ALBUM_WIDE_FIELDS` that carries the same value on every
    position it appears on is rendered once, with no `data-position` - an
    album of a dozen tracks does not need the same album title in a dozen
    boxes. The one place that disagrees (it should not, coming from one
    release) falls back to one input per position, the same as a
    track-scoped field. The JS export reads the absence of `data-position`
    to mean "every position", so this is also the only place that decision
    is made.
    """
    positions = sorted(fields, key=_position_key)
    fields_seen = sorted({field for position in positions for field in fields[position]})
    parts = []
    for field in fields_seen:
        holders = [position for position in positions if field in fields[position]]
        values_per_holder = [fields[position][field] for position in holders]
        if field in ALBUM_WIDE_FIELDS and len(set(map(tuple, values_per_holder))) <= 1:
            for value in values_per_holder[0]:
                parts.append(_field_input(field, value, position=None))
            continue
        for position in holders:
            for value in fields[position][field]:
                parts.append(_field_input(field, value, position=position))
    return "".join(parts)


def _game_block(entry: Album) -> str:
    key = entry["source"]
    name = f"game-{_esc(key)}"
    # `entry["game"]` is the game/not-game choice identify already folded
    # in: pre-selecting it means a re-export that touches nothing does not
    # lose it.
    chosen = entry.get("game")

    def sel(value: str) -> str:
        return " checked" if value == chosen else ""

    return (
        '<fieldset class="game"><legend>Composer choice</legend>'
        f'<label><input type="radio" name="{name}" value="video game music"{sel("video game music")}>'
        " video game music</label>"
        f'<label><input type="radio" name="{name}" value="not game music"{sel("not game music")}>'
        " not game music</label>"
        "</fieldset>"
    )


def _decision_block(entry: Album) -> str:
    key = entry["source"]
    name = f"action-{_esc(key)}"
    # The decision already folded into this entry (or "skip", with nothing
    # decided) is what starts checked - not a hard-coded skip - so a page
    # built after a fold opens on the owner's last answer, not over it.
    folded = entry.get("decision") if entry.get("decision") in ("accept", "repoint") else "skip"

    def sel(value: str) -> str:
        return " checked" if value == folded else ""

    accept = ""
    if entry["candidates"]:
        # Pre-checked candidate is the one the plan above was built against
        # (entry["release_id"]), not whichever the engine happened to list
        # first: the before/after the owner is looking at is only honest
        # about the release it names, folded decision or not.
        chosen = entry.get("release_id")
        candidates = "".join(
            _candidate_block(c, key, checked=(c["release_id"] == chosen))
            for c in entry["candidates"]
        )
        accept = f'<label><input type="radio" name="{name}" value="accept"{sel("accept")}> Accept{candidates}</label>'
    repoint_value = f' value="{_esc(entry["release_id"])}"' if folded == "repoint" and entry.get("release_id") else ""
    return (
        '<fieldset class="decision"><legend>Decision</legend>'
        f'<label><input type="radio" name="{name}" value="skip"{sel("skip")}> Skip</label>'
        + accept +
        f'<label><input type="radio" name="{name}" value="repoint"{sel("repoint")}> Repoint to'
        f' <input data-repoint="{_esc(key)}"{repoint_value} '
        'placeholder="MusicBrainz release URL or MBID"></label>'
        "</fieldset>"
    )


# --- one album's card ----------------------------------------------------

def _album_section(entry: Album) -> str:
    key, state = entry["source"], entry["state"]
    body = [f'<h4 class="source">{_esc(key)}</h4>']
    if entry.get("destination") and entry["destination"] != key:
        body.append(f'<div class="destination">→ {_esc(entry["destination"])}</div>')
    if state == "held":
        body.append(_holds_block(entry["holds"]))
    for f in entry["files"]:
        body.append(_file_block(f))
    # Every other path the write touches: an auto album is written with
    # nobody deciding, so it needs these shown just as much as a held one.
    body.append(_deletion_block(entry))
    body.append(_extra_block(entry))
    body.append(_kept_block(entry))
    body.append(_image_block(entry["images"]))
    if state == "held":
        body.append(_residue_block(entry["residue"]))
    body.append(_field_inputs(entry["fields"]))
    if entry["game_choice"]:
        body.append(_game_block(entry))
    if state == "held":
        body.append(_decision_block(entry))
    return (
        f'<section class="album" data-album="{_esc(key)}" data-state="{_esc(state)}">'
        + "".join(body) + "</section>"
    )


def _held_section(doc: Doc) -> str:
    held = [a for a in doc["albums"] if a["state"] == "held"]
    groups: dict[str, list[Album]] = {}
    for a in held:
        groups.setdefault(a["source"].split("/")[1], []).append(a)
    parts = ['<section class="held-albums"><h2>Held for review</h2>']
    # Iterated in sorted folder order rather than first-seen order, so the
    # page is byte-identical regardless of how the caller ordered `albums`.
    for folder in sorted(groups):
        sections = "".join(_album_section(a) for a in groups[folder])
        parts.append(f'<div class="group" data-artist="{_esc(folder)}"><h3>{_esc(folder)}</h3>{sections}</div>')
    parts.append("</section>")
    return "".join(parts)


def _auto_section(doc: Doc) -> str:
    autos = [a for a in doc["albums"] if a["state"] == "auto"]
    if not autos:
        return ""
    parts = ['<section class="auto-albums"><h2>Applying without a decision</h2>']
    for a in autos:
        parts.append(
            "<details><summary>Applying without a decision</summary>"
            + _album_section(a) + "</details>"
        )
    parts.append("</section>")
    return "".join(parts)


def _folded_decision(entry: Album) -> dict | None:
    """`entry`'s own `decision`/`release_id`/`game`, in `decisions.json`'s
    shape - `None` for nothing decided yet (a plain skip).

    `owner_edits` (not `inputs.edits`) is what a re-export carries: for a
    no-composer album, `inputs.edits` includes the genre `rebuild` writes
    for the folded game choice, and carrying that forward would make
    flipping the radio a no-op.
    """
    decision = entry.get("decision")
    if decision == "accept":
        return {"action": "accept", "release_id": entry["release_id"],
                "edits": entry["owner_edits"], "game": entry.get("game")}
    if decision == "repoint":
        return {"action": "repoint", "release": entry["release_id"]}
    return None


def _skeleton(doc: Doc) -> dict:
    """`#decisions-skeleton`: the folded decision for every held album
    (`skip` where there is none), plus every auto album whose entry already
    says accept, so an export of an untouched page repeats the answer
    identify already folded in rather than silently downgrading it to skip.
    """
    albums: dict[str, dict] = {}
    for a in doc["albums"]:
        if a["state"] == "held":
            albums[a["source"]] = _folded_decision(a) or {"action": "skip"}
        elif a["state"] == "auto":
            folded = _folded_decision(a)
            if folded is not None and folded["action"] == "accept":
                albums[a["source"]] = folded
    return {"job": doc["job"], "albums": albums}


def _trimmed_plan(doc: Doc) -> dict:
    """`#plan`: exactly what `review.js` reads, per listed album - not the
    whole entry, which once tripled the page for data the markup already
    shows in full (candidates, files, residue, images, holds, ...).
    """
    albums = []
    for a in doc["albums"]:
        if a["state"] not in ("held", "auto"):
            continue
        albums.append({
            "source": a["source"], "state": a["state"], "fields": a["fields"],
            "game_choice": a["game_choice"], "release_id": a["release_id"],
            "decision": a.get("decision"), "game": a.get("game"),
            "edits": a["owner_edits"],
        })
    return {"job": doc["job"], "albums": albums}


def render(plan_doc: Doc) -> bytes:
    """The whole `review.html` page for `plan_doc`, as UTF-8 bytes."""
    css = (_HERE / "review.css").read_text(encoding="utf-8")
    js = (_HERE / "review.js").read_text(encoding="utf-8")

    skeleton = _skeleton(plan_doc)

    body = (
        f'<h1>Job {_esc(plan_doc["job"])}</h1>'
        + _held_section(plan_doc)
        + _auto_section(plan_doc)
        + '<button id="export" type="button">Export decisions.json</button>'
    )

    page = (
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8">'
        f'<title>Review job {_esc(plan_doc["job"])}</title>'
        f"<style>{css}</style></head>"
        f"<body>{body}"
        + _script_json("plan", _trimmed_plan(plan_doc))
        + _script_json("decisions-skeleton", skeleton)
        + f"<script>{js}</script>"
        "</body></html>"
    )
    return page.encode("utf-8")
