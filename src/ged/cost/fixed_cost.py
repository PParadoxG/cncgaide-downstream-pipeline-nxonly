"""Fixed 1:1 aggregate substitution (surface background layer, unclaimed residue)."""

from __future__ import annotations

from ged.contract.representation import NX
from ged.contract.schema import GedFixedNode
from .config import FixedCostParts
from .node_cost import bounded_diff


def make_fixed_node_cost(w_res: float, *, shares=None, attribute_weights=None):
    """The aggregate cost for the background layer.

    Both tables are the representation's: there is one aggregate per class of
    NX's ``SURFACES`` family plus one for the faces no feature claimed, and
    the shares sum to 1 so the combined raw-cost ceiling is exactly ``W_RES``.
    """
    shares = dict(NX.fixed_budget_shares if shares is None else shares)
    attribute_weights = dict(
        NX.fixed_attribute_weights if attribute_weights is None else attribute_weights)

    def fixed_node_cost(left: GedFixedNode, right: GedFixedNode) -> FixedCostParts:
        if left.type_key != right.type_key:
            raise ValueError(f"fixed node type mismatch: {left.type_key} vs {right.type_key}")
        share = shares.get(left.type_key)
        weights = attribute_weights.get(left.type_key)
        if share is None or weights is None:
            raise ValueError(f"no fixed-node cost registered for {left.type_key}")
        differences: dict[str, float] = {}
        total = 0.0
        weight_sum = 0.0
        for name, weight in weights.items():
            if name not in left.attributes or name not in right.attributes:
                continue
            distance = bounded_diff(float(left.attributes[name]), float(right.attributes[name]))
            differences[name] = distance
            total += weight * distance
            weight_sum += weight
        mixture = total / weight_sum if weight_sum else 0.0
        return FixedCostParts(cost=w_res * share * mixture, differences=differences)

    return fixed_node_cost


def fixed_cost_upper_bound(w_res: float, *, shares=None) -> float:
    return w_res * sum((NX.fixed_budget_shares if shares is None else shares).values())
