"""Version stamp for everything a cached distance depends on besides the weights.

Two things already version a cached pair: the configuration hash covers the
eight adjustable scalars and *nothing else*, and each part's facts key covers
the facts it was projected from.  Neither covers the code and the tables in
between - which classes exist, which attributes are compared, what a class
substitution is worth.  Editing one of them changes every distance while the
hash and both facts keys stay the same, so a cached pair would keep answering
with what the old tables produced.

The stamp closes that hole the same way the facts key closes its own: it
joins the cache key, an entry whose stamp differs never matches again and is
overwritten by the next computation.  Lazy invalidation, no migration, no
orphaned files.

It is made of three things:

* ``VERSION`` - the representation's own version.  Raise it when the
  projection or the solver computes a distance differently without any table
  below changing.
* the ontology digest - source and build, so a changed class, attribute,
  relation or threshold invalidates by itself.
* the sha256 of the installed NX schema every class name and unit was
  transcribed from, so a different NX install invalidates too.

The cost layer's own constants are neither the ontology's nor a weight, so
they are hashed in beside the three.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from kg.sync import schema_sha256
from tbox import nx as tbox

from ged.contract.representation import NX
from ged.cost import edge_cost, node_cost, type_matrix


#: Raise when representation or cost *code* changes without a table changing.
VERSION = 1


def _canonical(value: Any) -> Any:
    """A deterministic, JSON-serialisable image of a table."""
    if isinstance(value, (frozenset, set)):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, dict):
        if any(isinstance(key, (frozenset, set)) for key in value):
            return sorted([_canonical(key), _canonical(item)] for key, item in value.items())
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


#: The cost-layer constants that price a distance and are not one of the eight
#: weights.  Every representation table is a function of the ontology digest,
#: which is in the stamp already.
COST_TABLES: dict[str, Any] = {
    "EDGE_STATIC_BASE_WEIGHT": NX.static_edge_base_weight,
    "EDGE_DEFAULT_BASE_WEIGHT": edge_cost.DEFAULT_BASE_WEIGHT,
    "LABEL_MISMATCH_BASE": edge_cost.LABEL_MISMATCH_BASE,
    "ATTRIBUTE_MISMATCH_BASE": edge_cost.ATTRIBUTE_MISMATCH_BASE,
    "CATEGORY_DISTANCE": node_cost.CATEGORY_DISTANCE,
    "TYPE_OVERRIDES": type_matrix.OVERRIDES,
    "TYPE_SAME_LEAF": type_matrix.SAME_LEAF,
    "TYPE_UNKNOWN": type_matrix.UNKNOWN,
    "FIXED_BUDGET_SHARES": NX.fixed_budget_shares,
    "FIXED_ATTRIBUTE_WEIGHTS": NX.fixed_attribute_weights,
    "SKIP_BOTH_ZERO": True,
}


def ingredients() -> dict[str, Any]:
    """What the stamp is a function of, for a report or a test."""
    return {
        "version": VERSION,
        "representation": NX.name,
        "ontologyDigest": tbox.ontology_digest(),
        "schemaSha256": schema_sha256(),
        "costTables": {key: _canonical(table) for key, table in sorted(COST_TABLES.items())},
    }


def semantics_stamp() -> str:
    """``r<VERSION>-<8 hex digits>`` - the stamp that versions a cached pair."""
    payload = json.dumps(ingredients(), sort_keys=True)
    return f"r{VERSION}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:8]}"
