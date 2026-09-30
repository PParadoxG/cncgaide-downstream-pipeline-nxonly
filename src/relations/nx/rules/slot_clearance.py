"""SLOT_CLEARANCE — the gap between two slots' opening boundaries."""

from __future__ import annotations

from core.models import FeatureEdge
from relations.base import RelationContext, RelationRule
from relations.nx._shared import (
    SEPARATION_TOL_MM,
    _report,
    boundary_set_clearance,
    feature_type,
    in_any_family,
    nx_edge,
    opening_boundary_polylines,
)
from relations.nx.registry import register_rule


@register_rule
class NxSlotClearance(RelationRule):
    """Measured where ``relations.yaml`` says: at the openings.

    Reading "between two slots" as the two whole owned face sets would be a
    weaker quantity, because a slot's floor is part of its owned set and two
    slots on opposite faces of a web would then be called close when their
    floors nearly meet.  The opening boundaries are what is measured instead:
    ``face_set_openings`` walks the boundary of a feature's own patch, and
    that walk is the same one LOCATED_ON runs.  It needs no kernel, so
    ``relations.yaml`` files the relation as ``nx_topology``.

    Two clauses, both from the ontology: the boundaries have to be findable,
    and they have to be **separated**.  A zero reading is two slots touching,
    and a contact is not a clearance.  There is no shared-host gate; the note
    on HOLE_SPACING says why.
    """

    rule_id = "slot_clearance_nx"
    edge_type = "SLOT_CLEARANCE"
    priority = 70
    enabled_by_default = True
    directed = False
    description = "NX SLOTS-family pair, opening boundaries measured on the PartModel."

    family = "SLOTS"
    property_name = "slotClearance"

    def build_edges(self, context: RelationContext) -> list[FeatureEdge]:
        edges: list[FeatureEdge] = []
        members = [node for node in context.nodes
                   if in_any_family(feature_type(node), (self.family,))]
        for index, left in enumerate(members):
            left_boundaries = opening_boundary_polylines(context, left)
            for right in members[index + 1:]:
                right_boundaries = opening_boundary_polylines(context, right)
                value, details = boundary_set_clearance(left_boundaries, right_boundaries)
                if value is None:
                    _report(context, self.rule_id, details["status"])
                    continue
                if value <= SEPARATION_TOL_MM:
                    details["status"] = "contacting"
                    _report(context, self.rule_id, "contactingOpeningBoundaries")
                    continue
                edges.append(nx_edge(
                    left, right, self.edge_type, self.rule_id, "nx_topology",
                    {
                        "relationBasis": "shortestDistanceBetweenSeparatedOpeningBoundaries",
                        "nxBasis": "PartModel face-set boundary walk plus polyline distance; "
                                   "the same basis cnc:SLOT_CLEARANCE measures on",
                        "featureA": {"nodeId": left.nodeId, "featureType": feature_type(left)},
                        "featureB": {"nodeId": right.nodeId, "featureType": feature_type(right)},
                        "separationTolerance": SEPARATION_TOL_MM,
                        "clearanceWitness": details,
                    },
                    properties={self.property_name: value},
                ))
        return edges
