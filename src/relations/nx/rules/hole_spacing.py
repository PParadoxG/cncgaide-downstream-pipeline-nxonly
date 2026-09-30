"""HOLE_SPACING — perpendicular offset between two parallel hole axes."""

from __future__ import annotations

from core.models import FeatureEdge
from relations.base import RelationContext, RelationRule
from relations.nx._shared import (
    AXIS_LINE_TOL_MM,
    PARALLEL_ANGLE_TOL_DEG,
    SPACING_BASIS,
    _report,
    acute_angle_deg,
    axis,
    axis_point,
    feature_type,
    is_hole_like,
    nx_edge,
    parallel_axis_spacing,
)
from relations.nx.registry import register_rule


@register_rule
class NxHoleSpacing(RelationRule):
    """Every parallel hole pair in the part, not only the same-host ones.

    ``relations.yaml`` states in as many words that this relation has no
    shared-host gate, because "same host" is not a reliable notion here: NX
    registers one physical plane as several SURFACE_PLANAR features, merges no
    faces, and lets two features own the same raw face, so gating on a common
    host both keeps pairs that only share a bore they opened into and drops
    small features that resolve to no host at all.  Parallelism and a finite
    offset are what this relation claims, and both come straight from NX's own
    scalars.
    """

    rule_id = "hole_spacing_nx"
    edge_type = "HOLE_SPACING"
    priority = 50
    enabled_by_default = True
    directed = False
    description = "Parallel NX hole-family features, with the offset between their axes."

    def build_edges(self, context: RelationContext) -> list[FeatureEdge]:
        edges: list[FeatureEdge] = []
        holes = [node for node in context.nodes if is_hole_like(node)]
        for index, left in enumerate(holes):
            for right in holes[index + 1:]:
                left_axis, right_axis = axis(left), axis(right)
                left_point, right_point = axis_point(left), axis_point(right)
                if None in (left_axis, right_axis, left_point, right_point):
                    _report(context, self.rule_id, "axisLineProofUnavailable")
                    continue
                angle = acute_angle_deg(left_axis, right_axis)
                spacing = parallel_axis_spacing(left_point, left_axis, right_point, right_axis)
                if spacing is None:
                    _report(context, self.rule_id, "nonParallelAxisRejected")
                    continue
                # A coaxial pair has no spacing to speak of: the two axes are
                # one line, the number would be a degenerate zero and H12
                # would read it as a violation.  Gate on the degenerate metric
                # rather than on the COAXIAL edge, so a change to that
                # relation's allowed pairs cannot let a zero through.
                if spacing <= AXIS_LINE_TOL_MM:
                    _report(context, self.rule_id, "coaxialPairRejected")
                    continue
                edges.append(nx_edge(
                    left, right, self.edge_type, self.rule_id, "nx_arithmetic",
                    {
                        "relationBasis": "parallelInfiniteFeatureAxisLines",
                        "nxBasis": "X/Y/Z_ORIENTATION_D and X/Y/Z_POSITION, as NX published them",
                        "featureA": {"nodeId": left.nodeId, "featureType": feature_type(left)},
                        "featureB": {"nodeId": right.nodeId, "featureType": feature_type(right)},
                        "axisA": left_axis,
                        "axisB": right_axis,
                        "axisPointA": left_point,
                        "axisPointB": right_point,
                        "acuteAngularDeviation": round(angle, 6),
                        "angularTolerance": PARALLEL_ANGLE_TOL_DEG,
                        "spacingBasis": SPACING_BASIS,
                    },
                    properties={"axisSpacing": round(spacing, 6)},
                ))
        return edges
