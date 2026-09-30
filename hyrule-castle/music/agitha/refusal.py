"""A route that turns a request down raises `Refusal`; the dispatcher answers it."""

from __future__ import annotations

BUSY = "A musiclib process is queued or running for it; wait for it to finish."


class Refusal(Exception):
    def __init__(self, status: int, sentence: str) -> None:
        super().__init__(sentence)
        self.status, self.sentence = status, sentence
