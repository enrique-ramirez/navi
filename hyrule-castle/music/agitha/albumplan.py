"""What a hand edit would do to one album: the plan `editor.plan` builds, which a preview answers and a save carries out.

A save writes only the keys in each track's `named`, each as `after` holds it,
and never `after` whole: `after` is `before` merged with the edits and also
lacks the duplicate fields `tagwrite.merge` drops. It then renames each file
to its `new_path` and the album folder to `AlbumPlan.new_path`.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from musiclib import check, mapping

from . import library

_YEAR = re.compile(r"\d{4}")


@dataclasses.dataclass
class TrackPlan:
    """One track: the tags it holds, the tags it would hold, and the path it would have in its album."""

    #: Album-relative, as the file is now.
    path: str
    #: Album-relative, as the file would be named; equal to `path` where nothing moves.
    new_path: str
    family: str
    #: The file's own tags, every key as the engine's reader gives it.
    before: dict[str, list[str]]
    #: `before` with the draft's edits laid over it.
    after: dict[str, list[str]]
    #: `(key as the page names it, the file's own key)` of each tag the draft names for this track, in the draft's order.
    named: list[tuple[str, str]]
    length: float
    #: The engine's reading of the file, or `None` where only the library's reader could open it.
    state: check.TrackState | None = None

    def changes(self) -> list[dict[str, Any]]:
        return [{"key": shown, "before": self.before.get(real), "after": self.after.get(real)}
                for shown, real in self.named if self.before.get(real) != self.after.get(real)]

    def first(self, name: str, tags: dict[str, list[str]]) -> str | None:
        """The first value of the tag the readable `name` means in this track's format."""
        values = tags.get(mapping.READABLE[name][self.family] or "")
        return values[0] if values else None

    def number(self, name: str, tags: dict[str, list[str]]) -> int:
        """The leading number of the tag the readable `name` means, 0 where there is none."""
        return library.leading_number(self.family, tags, mapping.READABLE[name])

    def edited(self, name: str) -> str | None:
        """The first value of the tag `name` as the draft leaves it, where it has one and the file's differs."""
        new = self.first(name, self.after)
        return new if new and new != self.first(name, self.before) else None

    def edited_year(self) -> str | None:
        """The year of the date as the draft leaves it, where it has one and the file's differs."""
        new = _YEAR.match(self.first("Date", self.after) or "")
        old = _YEAR.match(self.first("Date", self.before) or "")
        return new.group() if new and (old is None or new.group() != old.group()) else None

    def edited_number(self, name: str) -> int:
        """The number of the tag `name` as the draft leaves it, where it has one and the file's differs; else 0."""
        new = self.number(name, self.after)
        return new if new != self.number(name, self.before) else 0


@dataclasses.dataclass
class AlbumPlan:
    #: Library-relative, `Letter/Artist/Album`.
    path: str
    new_path: str
    #: Every track of the album, in disc and track order, changed or not.
    tracks: list[TrackPlan]
    problems: list[dict[str, str]]
    refused: list[dict[str, str]]
    #: Whether the folder keeps an edition suffix `new_path` carries.
    edition: bool = False
    cover: dict[str, Any] | None = None
    #: The upload the draft names as the cover; the image is read when the save copies it.
    cover_token: str | None = None
    #: Why a batch leaves the album out (`batch.skip_reason`), or `None`; a skipped album lists no track.
    skip: str | None = None

    def problem_sentence(self) -> str | None:
        """The first problem as `rule: detail`, or `None` where there is none."""
        if not self.problems:
            return None
        first = self.problems[0]
        return f"{first['rule']}: {first['detail']}"

    def answer(self) -> dict[str, Any]:
        return {
            "path": self.path, "new_path": self.new_path,
            "tracks": [{"path": track.path, "new_path": track.new_path, "changes": changes}
                       for track in self.tracks if self.skip is None and (changes := track.changes())],
            "cover": self.cover, "problems": self.problems, "refused": self.refused, "skip": self.skip,
        }
