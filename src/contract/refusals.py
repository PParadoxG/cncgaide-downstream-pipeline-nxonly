"""Refusals the pipeline words identically wherever they are raised.

A refusal is a first-class answer.  When an input is out of scope for the
pipeline as a whole - not for one measurement, not for one rule - the reason
belongs here, once, so that every caller prints the same sentence and a reader
of two parts can see they were refused for the same thing.

Standard library only, like the rest of ``contract``.
"""

from __future__ import annotations

#: A STEP with more than one solid body.  Building the first body and saying
#: nothing would publish a part that silently lost geometry, so the whole part
#: is refused instead; the count is in the text because "how many" is the first
#: thing a reader asks.
MULTI_BODY_UNSUPPORTED = (
    "multi-body part ({count} solid bodies): refusing rather than picking the first body"
)


def multi_body_unsupported(count: int) -> str:
    """The refusal text for a part carrying *count* solid bodies."""
    return MULTI_BODY_UNSUPPORTED.format(count=int(count))
