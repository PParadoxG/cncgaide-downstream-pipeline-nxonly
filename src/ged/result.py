"""The result of one distance, graph-agnostic."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class GedBreakdown:
    node_cost: float
    fixed_cost: float
    edge_cost: float
    scale_cost: float
    n_sub: float
    n_type_change: float
    n_del: float
    n_ins: float
    edges_preserved: float
    edges_changed: float
    edges_del: float
    edges_ins: float


# Display contract for the result: the words a page prints for each key of a
# breakdown and for each section of an edit path, with a one-line explanation
# for the tooltip.  This is the one place they are written; the similarity
# service hands them to the pages beside the weight specifications, so no page
# code names a key.  A key missing here is shown by its own name.
BREAKDOWN_LABELS: dict[str, dict[str, str]] = {
    "node_cost": {"label": "Features",
                  "hint": "machining features matched, removed or added: changed types and dimensions"},
    "fixed_cost": {"label": "Background faces",
                   "hint": "plain faces that belong to no machining feature, compared by count and area"},
    "edge_cost": {"label": "Relations",
                  "hint": "relations between features that changed, disappeared or appeared"},
    "scale_cost": {"label": "Overall size",
                   "hint": "difference in the overall size of the two parts"},
    "n_sub": {"label": "features matched",
              "hint": "features paired with a feature of the other part"},
    "n_type_change": {"label": "type changes",
                      "hint": "matched features whose type differs"},
    "n_del": {"label": "features removed",
              "hint": "features of the query part with no counterpart in the candidate"},
    "n_ins": {"label": "features added",
              "hint": "features of the candidate with no counterpart in the query part"},
    "edges_preserved": {"label": "relations kept",
                        "hint": "relations found unchanged in both parts"},
    "edges_changed": {"label": "relations changed",
                      "hint": "relations found in both parts, with different values"},
    "edges_del": {"label": "relations removed",
                  "hint": "relations of the query part with no counterpart in the candidate"},
    "edges_ins": {"label": "relations added",
                  "hint": "relations of the candidate with no counterpart in the query part"},
}

EDIT_PATH_LABELS: dict[str, dict[str, str]] = {
    "nodes": {"label": "Features",
              "hint": "each machining feature: matched, removed or added"},
    "fixed_nodes": {"label": "Background faces",
                    "hint": "the plain faces that belong to no machining feature, compared as totals"},
    "edges": {"label": "Relations",
              "hint": "each relation between features: kept, changed, removed or added"},
    "scale": {"label": "Overall size",
              "hint": "the overall size of the two parts"},
}


def result_labels() -> dict[str, dict[str, dict[str, str]]]:
    """``{"breakdown": {key: {label, hint}}, "editPath": {section: {label, hint}}}``."""
    return {
        "breakdown": {key: dict(entry) for key, entry in BREAKDOWN_LABELS.items()},
        "editPath": {key: dict(entry) for key, entry in EDIT_PATH_LABELS.items()},
    }


@dataclass(frozen=True)
class GedResult:
    graph_id_a: str
    graph_id_b: str
    raw_cost: float
    upper_bound: float
    normalized_distance: float
    similarity_percent: float
    breakdown: GedBreakdown
    edit_path: Mapping[str, Any]
    config_name: str

    def to_dict(self, *, include_edit_path: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "graph_id_a": self.graph_id_a,
            "graph_id_b": self.graph_id_b,
            "raw_cost": self.raw_cost,
            "upper_bound": self.upper_bound,
            "normalized_distance": self.normalized_distance,
            "similarity_percent": self.similarity_percent,
            "breakdown": asdict(self.breakdown),
            "config": self.config_name,
        }
        if include_edit_path:
            payload["edit_path"] = dict(self.edit_path)
        return payload
