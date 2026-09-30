"""The default cost configuration: the eight weights and what they price."""

from __future__ import annotations

from ged.contract.representation import NX, Representation

from .config import CostConfig
from .edge_cost import edge_mismatch, make_edge_base_weight
from .fixed_cost import fixed_cost_upper_bound, make_fixed_node_cost
from .node_cost import make_geometry_distance
from .type_matrix import type_cost


W_SEM = 1.0
W_GEOM = 0.3
W_REL = 0.5
W_SCALE = 0.1
W_RES = 0.12
C_INS = 0.5
C_DEL = 0.5
# Local-structure steering of the assignment (see CostConfig.w_local).  It is
# needed because attribute-identical features are told apart only by what they
# are attached to: without it, plain assignment maps them by enumeration order
# and turns a preserved relation into a delete plus an insert.
W_LOCAL = 1.0


def default_config(name: str = "v0_default", *, w_local: float = W_LOCAL,
                   representation: Representation = NX) -> CostConfig:
    return CostConfig(
        name=name,
        w_sem=W_SEM,
        w_geom=W_GEOM,
        w_rel=W_REL,
        w_scale=W_SCALE,
        w_res=W_RES,
        c_del=C_DEL,
        c_ins=C_INS,
        type_cost=type_cost,
        geometry_distance=make_geometry_distance(representation, skip_both_zero=True),
        edge_base_weight=make_edge_base_weight(representation),
        edge_mismatch=edge_mismatch,
        fixed_node_cost=make_fixed_node_cost(
            W_RES, shares=representation.fixed_budget_shares,
            attribute_weights=representation.fixed_attribute_weights),
        fixed_cost_upper_bound=fixed_cost_upper_bound(
            W_RES, shares=representation.fixed_budget_shares),
        w_local=w_local,
        representation=representation,
    )
