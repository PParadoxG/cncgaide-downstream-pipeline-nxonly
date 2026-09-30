"""What a feature graph is, as one object the layers pass around.

A ``Representation`` fixes *what the graph is*: which classes enter the
assignment, which form the background layer, which attributes are compared
and in what unit, which relations survive and how their values are
normalised.  What it deliberately does **not** fix is the eight adjustable
weights: a weight says how much a kind of difference matters, and that is a
question for the cost layer.

Every table is derived from ``ontology/nx_v1_1/source`` through
``nx_policy``, so the representation changes when the ontology does, and the
semantics stamp (``ged.semantics``) notices.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from tbox import nx as tbox

from . import nx_policy


@dataclass(frozen=True)
class Representation:
    """The tables that say what a feature graph looks like."""

    name: str
    family_of: Mapping[str, str]
    surface_leaves: tuple[str, ...]
    semantic_leaves: frozenset[str]
    leaf_attributes: Mapping[str, tuple[str, ...]]
    attribute_kind: Mapping[str, str]
    angle_range_deg: Mapping[str, float]
    # Which relation types the projection keeps, and how it reads them.
    known_relations: frozenset[str]
    grouped_relations: frozenset[str]
    host_implying_relations: frozenset[str]
    edge_metrics: Mapping[str, Mapping[str, str]]
    # Insert / delete base weight of the relations the ontology publishes and
    # does *not* clique-normalise.  Which relations exist is the ontology's
    # answer, and so is what detaching one of them is worth.  A type absent
    # here falls back to ``cost.edge_cost.DEFAULT_BASE_WEIGHT``.
    static_edge_base_weight: Mapping[str, float] = field(default_factory=dict)
    # Fixed-node budget shares and attribute weights, by aggregate type key.
    fixed_budget_shares: Mapping[str, float] = field(default_factory=dict)
    fixed_attribute_weights: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    # The facts every table above is a function of, so the semantics stamp
    # can carry them.
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def kind_of(self, name: str) -> str:
        try:
            return self.attribute_kind[name]
        except KeyError as exc:  # pragma: no cover - guarded by the table checks
            raise KeyError(f"attribute {name!r} has no registered kind") from exc

    def angle_span(self, name: str) -> float:
        return float(self.angle_range_deg.get(name, 180.0))


def _relation_labels() -> tuple[str, ...]:
    return tuple(sorted(tbox.relation_types()))


def _build() -> Representation:
    tables = nx_policy.build()
    surfaces = tables["surface_leaves"]
    published = frozenset(_relation_labels())
    return Representation(
        name="nx",
        family_of=tables["family_of"],
        surface_leaves=surfaces,
        semantic_leaves=frozenset(c for c in tables["classes"] if c not in surfaces),
        leaf_attributes=tables["leaf_attributes"],
        attribute_kind=tables["attribute_kind"],
        angle_range_deg=tables["angle_range_deg"],
        # The relations the ontology declares, and nothing else.
        known_relations=published,
        # SHARES_HOST is derived by the projection from LOCATED_ON, so it is
        # grouped without being published.
        grouped_relations=frozenset(
            ("COAXIAL", "HOLE_SPACING", "SHARES_HOST", "POCKET_CLEARANCE", "SLOT_CLEARANCE")
        ) & (published | {"SHARES_HOST"}),
        host_implying_relations=frozenset(
            ("HOLE_SPACING", "POCKET_CLEARANCE", "SLOT_CLEARANCE")
        ) & published,
        edge_metrics={
            key: value for key, value in {
                "INTERSECTS": {"crossingAngle": "angle90"},
                "HOLE_SPACING": {"axisSpacing": "length"},
                "POCKET_CLEARANCE": {"pocketClearance": "length"},
                "SLOT_CLEARANCE": {"slotClearance": "length"},
            }.items() if key in published
        },
        # The relations that are published and not clique-normalised.
        static_edge_base_weight={
            key: value for key, value in {
                "LOCATED_ON": 0.6,
                "INTERSECTS": 1.0,
            }.items() if key in published
        },
        fixed_budget_shares=nx_policy.surface_budget_shares(surfaces),
        fixed_attribute_weights=nx_policy.surface_attribute_weights(surfaces),
        provenance={
            # Every table above is a function of these: a new NX install or an
            # edited ontology source invalidates the caches by itself.
            "installedSources": [
                {"path": item.get("path"), "sha256": item.get("sha256")}
                for item in (tbox.classes_head().get("source") or [])
            ],
            "ontologySourceVersion": dict(tbox.source_version()),
        },
    )


NX = _build()


def check(rep: Representation) -> None:
    """Every attribute a class publishes has a kind, and every angle a span."""
    for leaf, names in rep.leaf_attributes.items():
        if leaf not in rep.family_of:
            raise AssertionError(f"{rep.name}: {leaf} has attributes but no family")
        for name in names:
            kind = rep.attribute_kind.get(name)
            if kind is None:
                raise AssertionError(f"{rep.name}: {leaf}.{name} has no attribute kind")
            if kind == "angle" and name not in rep.angle_range_deg:
                raise AssertionError(f"{rep.name}: {name} is an angle without a range")
    priced = set(rep.static_edge_base_weight) - set(rep.known_relations)
    if priced:
        raise AssertionError(
            f"{rep.name}: base weights for relations it does not publish: {sorted(priced)}")
    missing = set(rep.semantic_leaves) - set(rep.leaf_attributes)
    if missing:
        raise AssertionError(f"{rep.name}: classes without an attribute policy: {sorted(missing)}")
    total = sum(rep.fixed_budget_shares.values())
    if rep.fixed_budget_shares and abs(total - 1.0) > 1.0e-9:
        raise AssertionError(f"{rep.name}: fixed-node budget shares sum to {total}, not 1")
    for type_key in rep.fixed_budget_shares:
        if type_key not in rep.fixed_attribute_weights:
            raise AssertionError(f"{rep.name}: {type_key} has a budget but no weights")


check(NX)
