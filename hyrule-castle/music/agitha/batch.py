"""What a draft that says it is a batch does differently from one that does not.

A batch is no route of its own. The preview and the save take it as they take
any draft, and `editor.plan` plans it with these rules: the tags that name a
track or an album or move a file are refused, no path changes, and an album
the draft cannot go through with is left out with a reason in `skip` while the
others go on.
"""

from __future__ import annotations

from .albumplan import AlbumPlan
from .refusal import SKIP_CHANGED

NOTHING_TO_CHANGE = "nothing to change"
ON_ITS_PAGE = "is edited on the album's page"

#: The readable names of the tags that name a track or an album, or move a file; a batch leaves them to the album's page.
PAGE_TAGS = frozenset({
    "Title", "Artist", "Album artist", "Artist sort order", "Album artist sort order", "Album", "Date",
    "Original release date", "Track number", "Disc number", "Disc subtitle",
})


def skip_reason(plan: AlbumPlan, changed: bool) -> str | None:
    """Why the album of `plan`, which is not in review, is left out of a batch, or `None`.

    Where two reasons apply, a page that is out of date comes first, then the
    first rule the draft would newly break, then there being nothing to change.
    """
    if changed:
        return SKIP_CHANGED
    if (problem := plan.problem_sentence()) is not None:
        return problem
    if not any(track.changes() for track in plan.tracks):
        return NOTHING_TO_CHANGE
    return None
