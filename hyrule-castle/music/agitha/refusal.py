"""A route that turns a request down raises `Refusal`; the dispatcher answers it.

The sentences more than one module answers with are here.
"""

from __future__ import annotations

BUSY = "A musiclib process is queued or running for it; wait for it to finish."
BEING_SAVED = "the album is being saved"
OPEN_IN_REVIEW = "the album is open in review"
#: The rule, and the start of the sentence, for a folder that is already another album's.
TAKEN = "already in the library"
#: A save or a preview that finds the page out of date, for one album.
ALBUM_CHANGED = "the album changed since this page loaded"
MATCH_CHANGED = "the library's copy changed since this match began; start over"
#: A match copies the album into the inbox, where a link would be written through or followed.
HOLDS_A_LINK = "the album holds a link, which a match cannot copy; replace the link with the file and match again"
#: Why a batch leaves an album out.
SKIP_OPEN = "open in review"
SKIP_CHANGED = "changed since this page loaded"


class Refusal(Exception):
    def __init__(self, status: int, sentence: str) -> None:
        super().__init__(sentence)
        self.status, self.sentence = status, sentence
