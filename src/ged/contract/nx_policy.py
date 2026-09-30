"""The representation tables, derived from the ontology source.

Nothing here is a list somebody wrote down.  ``ontology/nx_v1_1/source`` holds
NX's own class tree and its own attribute declarations, transcribed from the
installed ``customization_base.xml``, and every table below is a function of
that source plus four rules:

* an attribute enters the geometry term when NX gives it a ``unit`` of
  ``Length`` / ``Angle`` / ``Area``;
* ``*_UPPER`` / ``*_LOWER`` are the two halves of a tolerance band, not a
  second and third dimension, and are excluded;
* ``STOCK_*`` is machining stock, a process allowance rather than a shape;
* positions are excluded: two identical pockets in different corners are the
  same pocket.

Two attributes are boolean in meaning while NX types them as a length or a
string (``TOP_OBSTRUCTED``, ``IS_THROUGH``).  They are categories: the
difference between obstructed and not is not a distance in millimetres.

The one number that is ours and not NX's is the angle span: NX declares no
value range for an angle, so every angle difference is normalised by 180
degrees.  It is named here rather than hidden in a formula.

The **family** of a class is its nearest abstract ancestor.  That is a
reading of NX's tree, not a grouping we invented.  The label is metadata; no
cost reads it, because the class substitution cost is Wu-Palmer over the
whole tree and needs no family at all.
"""

from __future__ import annotations

from tbox import nx as tbox


# The unit vocabulary NX itself uses for the quantities that can enter a
# geometric distance, mapped to the kinds ``GedAttribute`` knows.
UNIT_KIND: dict[str, str] = {"Length": "length", "Angle": "angle", "Area": "area"}

# Excluded by name, with the reason each exclusion encodes.
TOLERANCE_BAND_SUFFIXES: tuple[str, ...] = ("_UPPER", "_LOWER")
STOCK_PREFIX = "STOCK_"
POSITION_NAMES: frozenset[str] = frozenset((
    "X_POSITION", "Y_POSITION", "Z_POSITION",
    "START_HOLE_POS_X", "START_HOLE_POS_Y",
))

# Boolean in meaning, numeric or textual in NX's type system.
BOOLEAN_AS_CATEGORY: tuple[str, ...] = ("TOP_OBSTRUCTED", "IS_THROUGH")

# NX declares no value range for an angle; this one is ours.
NX_ANGLE_RANGE_DEG = 180.0

# The background layer: NX's own ``SURFACES`` family, by the family and not
# by a list of class names.
SURFACE_FAMILY = "SURFACES"

# How the ``W_RES`` budget splits across the aggregates.  NX's surface leaves
# are all planar, so the split is even and derived from how many there are;
# the unclaimed residue keeps the remaining share.
SURFACE_BUDGET = 0.7
UNCLAIMED_BUDGET = 0.3


def _is_geometric(name: str) -> bool:
    record = tbox.attribute_record(name)
    if record is None or record.get("unit") not in UNIT_KIND:
        return False
    if name in POSITION_NAMES or name.startswith(STOCK_PREFIX):
        return False
    return not name.endswith(TOLERANCE_BAND_SUFFIXES)


def attribute_kind(name: str) -> str | None:
    """``length`` / ``angle`` / ``area`` / ``category``, or None if excluded."""
    if name in BOOLEAN_AS_CATEGORY:
        return "category"
    if not _is_geometric(name):
        return None
    record = tbox.attribute_record(name)
    return UNIT_KIND[record["unit"]]


def build() -> dict:
    """Every representation table, derived in one pass over the ontology."""
    classes = tuple(sorted(tbox.recognisable_classes()))
    surface_leaves = tuple(c for c in classes if tbox.in_family(c, SURFACE_FAMILY))
    leaf_attributes: dict[str, tuple[str, ...]] = {}
    kinds: dict[str, str] = {}
    for leaf in classes:
        kept = []
        for name in tbox.effective_attributes(leaf):
            kind = attribute_kind(name)
            if kind is None:
                continue
            kept.append(name)
            kinds[name] = kind
        # A surface leaf is aggregated, so its own attributes are never
        # compared one by one.
        leaf_attributes[leaf] = () if leaf in surface_leaves else tuple(sorted(kept))
    return {
        "classes": classes,
        "surface_leaves": surface_leaves,
        "leaf_attributes": leaf_attributes,
        "attribute_kind": kinds,
        "angle_range_deg": {name: NX_ANGLE_RANGE_DEG
                            for name, kind in kinds.items() if kind == "angle"},
        "family_of": {leaf: family_of(leaf) for leaf in classes},
    }


def family_of(name: str) -> str:
    """The class's nearest abstract ancestor, NX's own name for its family."""
    for ancestor in tbox.ancestry(name)[1:]:
        record = tbox.class_record(ancestor)
        if record is not None and record.get("abstract"):
            return ancestor
    return "Unknown"


def surface_budget_shares(surface_leaves) -> dict[str, float]:
    """Fixed-node budget shares, keyed by aggregate type; they sum to 1."""
    leaves = tuple(surface_leaves)
    shares = {f"{leaf}Aggregate": SURFACE_BUDGET / len(leaves) for leaf in leaves} if leaves else {}
    shares["UnclaimedAggregate"] = UNCLAIMED_BUDGET if leaves else 1.0
    return shares


def surface_attribute_weights(surface_leaves) -> dict[str, dict[str, float]]:
    """What an aggregate is compared on.  A face normal is not among them: a
    feature publishes NX's attributes, and a face normal is not one."""
    weights = {f"{leaf}Aggregate": {"face_count": 0.5, "area": 0.5}
               for leaf in surface_leaves}
    weights["UnclaimedAggregate"] = {"face_count": 0.5, "area": 0.5}
    return weights
