"""Class substitution cost: Wu-Palmer over NX's own class tree.

NX arranges its classes itself: a ``STEP2HOLE`` **is a** ``STEP1HOLE`` with
one more section, ``SLOT_V_SHAPED`` sits under ``SLOTS``, and everything
hangs off ``MachiningFeature``.  The cost reads that arrangement:

    cost(a, b) = 1 - 2 * depth(LCA) / (depth(a) + depth(b))

Over the recognisable classes that is a few thousand unordered pairs taking a
few dozen distinct values, none of which anybody chose: a counterbore next to
a through hole lands near zero, six sections away further, a V-slot further
still, a wire-cut pocket furthest.  Raw hop count gets that ordering wrong -
it calls a hole nearer to a V-slot than to a six-section hole, because the
STEP ladder is deep - and the normalisation fixes it without introducing a
constant of ours.

``OVERRIDES`` is where a proven exception would go.  It is empty: what the
tree says is accepted rather than corrected by a formula we would then own.

The price of the whole scheme is that Wu-Palmer reads the *depth* of NX's
tree, and depth is an artifact of how Siemens modelled it.  A different NX
install can move every number, which is why the installed schema's sha256
travels in the semantics stamp.
"""

from __future__ import annotations

from functools import lru_cache

from tbox import nx as tbox


#: Empty by decision, not by omission.
OVERRIDES: dict[frozenset[str], float] = {}

SAME_LEAF = 0.0
# What an unknown class costs against anything else.  A class the ontology
# does not know has no depth, so Wu-Palmer has nothing to say; the answer is
# "as different as this scheme can express", stated rather than crashed.
UNKNOWN = 1.0


@lru_cache(maxsize=None)
def _depth(name: str) -> int:
    """Number of classes from the root down to *name*, inclusive.  0 = unknown."""
    return len(tbox.ancestry(name))


@lru_cache(maxsize=None)
def _lca_depth(left: str, right: str) -> int:
    right_chain = tbox.ancestry(right)
    if not right_chain:
        return 0
    seen = set(right_chain)
    for ancestor in tbox.ancestry(left):
        if ancestor in seen:
            return _depth(ancestor)
    return 0


def type_cost(left: str, right: str) -> float:
    if left == right:
        return SAME_LEAF
    key = frozenset((left, right))
    if key in OVERRIDES:
        return OVERRIDES[key]
    left_depth, right_depth = _depth(left), _depth(right)
    if not left_depth or not right_depth:
        return UNKNOWN
    shared = _lca_depth(left, right)
    if not shared:
        return UNKNOWN
    return 1.0 - (2.0 * shared) / (left_depth + right_depth)


def type_matrix() -> dict[str, dict[str, float]]:
    """Full class x class matrix over the recognisable classes, for reports and tests."""
    classes = sorted(tbox.recognisable_classes())
    return {a: {b: type_cost(a, b) for b in classes} for a in classes}


def distinct_costs() -> tuple[float, ...]:
    """The sorted set of off-diagonal values the tree produces."""
    classes = sorted(tbox.recognisable_classes())
    values = {round(type_cost(a, b), 12)
              for index, a in enumerate(classes) for b in classes[index + 1:]}
    return tuple(sorted(values))
