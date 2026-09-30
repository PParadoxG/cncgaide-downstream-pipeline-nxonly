"""Project one part's facts to a ``GedGraph``.

This module *is* the representation layer:

- a feature of a recognisable class becomes a node that enters the
  assignment; a feature of the ``SURFACES`` family is background and is
  aggregated into a mandatory fixed node instead;
- only the attributes ``nx_policy`` keeps are compared, lengths divided by
  ``L_ref`` and areas by ``L_ref**2``;
- ``LOCATED_ON`` onto a surface host becomes ``SHARES_HOST`` edges between
  the features that share that host, while ``LOCATED_ON`` onto a feature
  host stays a real edge; the metric relations keep their normalised value;
- faces no feature claims are aggregated into one low-weight fixed node;
- ``L_ref`` is a measured quantity and is read from the facts, not
  recomputed here;
- the finished graph is in **canonical order** (``canonical_node_key``), so
  renumbering the features cannot move a distance.

Nothing here assigns a cost.  The audit collects every place where the facts
deviate from the contract, so a representation problem is visible without
rebuilding the part.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from contract.face_ids import raw_cad_face_id

from .facts import FaceFacts, FeatureFacts, PartFacts, RelationFacts, read_part
from .representation import NX, Representation
from .schema import GedAttribute, GedEdge, GedFixedNode, GedGraph, GedNode


FIXED_UNCLAIMED = "__unclaimed__"

#: ``LOCATED_ON`` names one feature as the located one and one as the host.
#: When both ends name each other the relation holds but its direction is not
#: stated, and it is not invented here.
DIRECTION_STATED = "u_on_v"
DIRECTION_UNSTATED = "unstated"


@dataclass
class ProjectionAudit:
    """Everything the projection had to decide beyond the happy path."""

    graph_id: str = ""
    unknown_leaf_types: list[str] = field(default_factory=list)
    attributes_absent: list[dict[str, Any]] = field(default_factory=list)
    attributes_null: list[dict[str, Any]] = field(default_factory=list)
    unknown_relation_types: list[str] = field(default_factory=list)
    edges_dropped: dict[str, int] = field(default_factory=dict)
    located_on_unresolved: list[dict[str, Any]] = field(default_factory=list)
    area_source: dict[str, str] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)

    def note_drop(self, reason: str) -> None:
        self.edges_dropped[reason] = self.edges_dropped.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "graphId": self.graph_id,
            "unknownLeafTypes": list(self.unknown_leaf_types),
            "attributesAbsent": list(self.attributes_absent),
            "attributesNull": list(self.attributes_null),
            "unknownRelationTypes": list(self.unknown_relation_types),
            "edgesDropped": dict(self.edges_dropped),
            "locatedOnUnresolved": list(self.located_on_unresolved),
            "areaSource": dict(self.area_source),
            "counts": dict(self.counts),
        }


# --------------------------------------------------------------------------
# helpers


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _normalise_value(kind: str, raw: float, name: str, l_ref: float) -> float:
    if kind == "length":
        return raw / l_ref
    if kind == "area":
        return raw / (l_ref * l_ref)
    if kind == "angle":
        return raw
    if kind == "count":
        return raw
    raise ValueError(f"numeric normalisation undefined for {kind} ({name})")


def _node_attributes(feature: FeatureFacts, leaf: str, l_ref: float,
                     audit: ProjectionAudit, representation: Representation) -> dict[str, GedAttribute]:
    missing = feature.attribute_gaps or {}
    values = feature.attributes or {}
    out: dict[str, GedAttribute] = {}
    for name in representation.leaf_attributes[leaf]:
        kind = representation.kind_of(name)
        present = name in values
        raw = values.get(name)
        if kind == "category":
            if isinstance(raw, str) and raw:
                out[name] = GedAttribute(name, "category", raw, raw, "valid")
                continue
        elif _is_number(raw):
            out[name] = GedAttribute(
                name, kind, _normalise_value(kind, float(raw), name, l_ref), raw, "valid"  # type: ignore[arg-type]
            )
            continue
        reason = missing.get(name)
        if reason is None:
            reason = "absent_in_node" if not present else "null_without_reason"
            audit.attributes_absent.append(
                {"nodeId": feature.node_id, "leaf": leaf, "attribute": name})
        else:
            audit.attributes_null.append(
                {"nodeId": feature.node_id, "leaf": leaf, "attribute": name})
        out[name] = GedAttribute(name, kind, None, raw, "null", str(reason))  # type: ignore[arg-type]
    return out


def _surface_aggregate(leaf: str, features: tuple[FeatureFacts, ...],
                       faces: dict[str, FaceFacts], l_ref: float,
                       audit: ProjectionAudit) -> GedFixedNode:
    count = 0
    area = 0.0
    sources: set[str] = set()
    for feature in features:
        if feature.feature_type != leaf:
            continue
        count += 1
        for face_id in feature.face_ids:
            face = faces.get(str(face_id))
            if face is None or face.area is None:
                raise ValueError(f"{feature.node_id}: face {face_id} has no area")
            area += face.area
            sources.add("face.area")
    if sources:
        audit.area_source[leaf] = "+".join(sorted(sources))
    return GedFixedNode(
        id=f"__{leaf}__",
        type_key=f"{leaf}Aggregate",
        attributes={"face_count": float(count), "area": area / (l_ref * l_ref)},
        raw={"face_count": count, "area_mm2": area, "normal_classes": None},
    )


def _unclaimed_aggregate(features: tuple[FeatureFacts, ...], faces: dict[str, FaceFacts],
                         l_ref: float) -> GedFixedNode:
    claimed: set[str] = set()
    for feature in features:
        claimed.update(str(face_id) for face_id in feature.face_ids)
    count = 0
    area = 0.0
    surface_mix: dict[str, int] = {}
    for face_id, face in faces.items():
        if face_id in claimed:
            continue
        count += 1
        area += face.area or 0.0
        surface_mix[face.surface_type] = surface_mix.get(face.surface_type, 0) + 1
    return GedFixedNode(
        id=FIXED_UNCLAIMED,
        type_key="UnclaimedAggregate",
        attributes={"face_count": float(count), "area": area / (l_ref * l_ref)},
        raw={"face_count": count, "area_mm2": area, "surface_mix": dict(sorted(surface_mix.items()))},
    )


def _located_on_endpoints(relation: RelationFacts, semantic_ids: set[str],
                          surface_ids: set[str]) -> tuple[str | None, list[str], str]:
    """``(located feature, host features, direction)`` from the terminals.

    ``direction`` is ``u_on_v`` when the terminals say which end is located on
    which, and ``unstated`` when the two ends witness each other: NX's
    relation layer records, for instance, a corner notch and the hole through
    it as meeting at these terminals without saying which is on which.  The
    relation holds either way, and no cost reads the direction - the edge's
    key is the sorted pair plus the type - so leaving it blank keeps a real
    relation instead of dropping it over a field nobody uses.
    """
    sources: list[str] = []
    hosts: list[str] = []
    for terminal in relation.terminals:
        if terminal.terminal_feature and terminal.terminal_feature not in sources:
            sources.append(terminal.terminal_feature)
        if terminal.host_owner and terminal.host_owner not in hosts:
            hosts.append(terminal.host_owner)
    endpoints = [relation.source, relation.target]
    if len(sources) == 1:
        return _with_hosts(sources[0], hosts, endpoints, DIRECTION_STATED)
    candidates = [e for e in endpoints if e in semantic_ids]
    others = [e for e in endpoints if e in surface_ids]
    if len(candidates) == 1 and len(others) == 1:
        return _with_hosts(candidates[0], hosts, endpoints, DIRECTION_STATED)
    if (len(sources) == 2 and endpoints[0] != endpoints[1]
            and set(sources) == set(endpoints)
            and all(end in semantic_ids for end in endpoints)):
        first, second = sorted(endpoints)
        return first, [second], DIRECTION_UNSTATED
    return None, [], DIRECTION_STATED


def _with_hosts(source: str, hosts: list[str], endpoints: list[str],
                direction: str) -> tuple[str, list[str], str]:
    return source, hosts or [e for e in endpoints if e != source], direction


def _component_sizes(pairs: list[tuple[str, str]]) -> dict[str, int]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for u, v in pairs:
        parent.setdefault(u, u)
        parent.setdefault(v, v)
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[ru] = rv
    sizes: dict[str, int] = {}
    for node in parent:
        root = find(node)
        sizes[root] = sizes.get(root, 0) + 1
    return {node: sizes[find(node)] for node in parent}


# --------------------------------------------------------------------------
# canonical order


def _face_order(face_id: object) -> tuple[float, str]:
    """One face id, ordered by its CAD face number: ``face_9`` before ``face_10``."""
    number = raw_cad_face_id(face_id)
    return (float(number) if number is not None else math.inf, str(face_id))


def canonical_node_key(node: GedNode) -> tuple[str, tuple[tuple[float, str], ...], str]:
    """The order a graph's nodes enter the solver in.

    ``(class, owned face ids in numeric order, node id)``.  The first two
    components are what the *part* is - a feature is the class NX recognised
    over the faces it owns - and they do not move when NX walks the model in a
    different order and hands out different ordinals.  The node id is only the
    tie-break, for the case two features of one class own the very same faces.

    Why this exists: the solver is an approximation, and among equal-cost
    assignments the Hungarian step picks the one the enumeration order leads
    to.  Ordering the projection canonically makes the distance a function of
    the graph rather than of the ordinals NX happened to issue.
    """
    return (node.type_key, tuple(sorted(_face_order(f) for f in node.face_ids)), node.id)


def _canonical_edge_key(edge: GedEdge, rank: dict[str, int]) -> tuple[int, int, str]:
    """An edge follows its two ends: the pair of canonical node positions.

    Unordered, because the cost layer's edge key is the sorted pair plus the
    type; ``u`` and ``v`` themselves are left alone, since LOCATED_ON's ``u``
    is the located feature and swapping it would rewrite what the edge says.
    """
    left, right = rank[edge.u], rank[edge.v]
    return (min(left, right), max(left, right), edge.type_key)


# --------------------------------------------------------------------------
# projection


def project_part(facts: PartFacts, *, graph_id: str | None = None,
                 audit: ProjectionAudit | None = None,
                 representation: Representation = NX) -> GedGraph:
    surface_leaves = representation.surface_leaves
    semantic_leaves = representation.semantic_leaves
    family_of = representation.family_of
    known_relations = representation.known_relations
    grouped_relations = representation.grouped_relations
    host_implying = representation.host_implying_relations
    edge_metrics = representation.edge_metrics
    audit = audit if audit is not None else ProjectionAudit()
    graph_id = graph_id or facts.part_id
    audit.graph_id = graph_id
    if not graph_id:
        raise ValueError("the facts name no part and no graph_id was given")

    l_ref = facts.require_length_reference()
    faces = dict(facts.faces)

    # --- nodes --------------------------------------------------------------
    nodes: list[GedNode] = []
    semantic_ids: set[str] = set()
    surface_ids: set[str] = set()
    for feature in facts.features:
        node_id = feature.node_id
        leaf = feature.feature_type
        if not node_id:
            raise ValueError(f"{graph_id}: feature without a node id")
        if leaf in surface_leaves:
            surface_ids.add(node_id)
            continue
        if leaf not in semantic_leaves:
            if leaf not in audit.unknown_leaf_types:
                audit.unknown_leaf_types.append(leaf)
            # An unknown class still enters as a node - the class
            # substitution cost handles it - but carries no comparable
            # attributes.
            nodes.append(GedNode(node_id, leaf, family_of.get(leaf, "Unknown"), {}))
            semantic_ids.add(node_id)
            continue
        nodes.append(
            GedNode(
                id=node_id,
                type_key=leaf,
                family=family_of[leaf],
                attributes=_node_attributes(feature, leaf, l_ref, audit, representation),
                feature_axis=None,
                face_ids=tuple(str(f) for f in feature.face_ids),
            )
        )
        semantic_ids.add(node_id)
    if len(semantic_ids) != len(nodes):
        raise ValueError(f"{graph_id}: duplicate node ids")

    # --- fixed nodes ------------------------------------------------------
    fixed: list[GedFixedNode] = [
        _surface_aggregate(leaf, facts.features, faces, l_ref, audit)
        for leaf in surface_leaves
    ]
    fixed.append(_unclaimed_aggregate(facts.features, faces, l_ref))

    # --- edges ------------------------------------------------------------
    edges: list[GedEdge] = []
    slots: set[tuple[str, str, str]] = set()
    pair_relations: dict[tuple[str, str], set[str]] = {}
    host_members: dict[str, list[str]] = {}

    def add_edge(edge: GedEdge) -> None:
        key = (*sorted((edge.u, edge.v)), edge.type_key)
        if key in slots:
            raise ValueError(f"{graph_id}: duplicate typed edge slot {key}")
        slots.add(key)
        edges.append(edge)
        pair_relations.setdefault(key[:2], set()).add(edge.type_key)

    for relation in facts.relations:
        edge_type = relation.relation_type
        source = relation.source
        target = relation.target
        if edge_type not in known_relations:
            if edge_type not in audit.unknown_relation_types:
                audit.unknown_relation_types.append(edge_type)
            audit.note_drop(f"unknown:{edge_type}")
            continue
        if edge_type == "LOCATED_ON":
            src, hosts, direction = _located_on_endpoints(relation, semantic_ids, surface_ids)
            if src is None or src not in semantic_ids:
                audit.located_on_unresolved.append(
                    {"edgeId": relation.relation_id, "source": source, "target": target})
                audit.note_drop("LOCATED_ON:unresolved")
                continue
            for host in hosts:
                if host in surface_ids:
                    members = host_members.setdefault(host, [])
                    if src not in members:
                        members.append(src)
                elif host in semantic_ids and host != src:
                    key = (*sorted((src, host)), "LOCATED_ON")
                    if key in slots:
                        continue
                    roles = [t.terminal_role for t in relation.terminals]
                    metadata: dict[str, Any] = {"direction": direction, "terminalRoles": roles}
                    if direction == DIRECTION_UNSTATED:
                        metadata["reason"] = "mutual_witness"
                    add_edge(GedEdge(src, host, "LOCATED_ON", metadata=metadata))
                else:
                    audit.located_on_unresolved.append(
                        {"edgeId": relation.relation_id, "host": host})
                    audit.note_drop("LOCATED_ON:host_unknown")
            continue
        # metric / axis relations between features that entered the assignment
        if source not in semantic_ids or target not in semantic_ids:
            audit.note_drop(f"{edge_type}:non_semantic_endpoint")
            continue
        attributes: dict[str, float] = {}
        raw_attributes: dict[str, object] = {}
        for name, norm in edge_metrics.get(edge_type, {}).items():
            value = relation.properties.get(name)
            if _is_number(value):
                raw_attributes[name] = value
                attributes[name] = float(value) / l_ref if norm == "length" else float(value) / 90.0
        add_edge(GedEdge(source, target, edge_type, attributes=attributes,
                         raw_attributes=raw_attributes))

    # SHARES_HOST: the features that open onto one background host.
    shares: dict[tuple[str, str], list[str]] = {}
    for host, members in host_members.items():
        ordered = sorted(members)
        for i, a in enumerate(ordered):
            for b in ordered[i + 1:]:
                pair = (a, b)
                if pair_relations.get(pair, set()) & host_implying:
                    continue
                shares.setdefault(pair, []).append(host)
    for (a, b), hosts in sorted(shares.items()):
        add_edge(GedEdge(a, b, "SHARES_HOST", metadata={"hosts": sorted(hosts)}))

    # Group sizes for clique-normalised relation types.
    grouped: dict[str, list[tuple[str, str]]] = {}
    for edge in edges:
        if edge.type_key in grouped_relations:
            grouped.setdefault(edge.type_key, []).append((edge.u, edge.v))
    sizes_by_type = {t: _component_sizes(pairs) for t, pairs in grouped.items()}
    finished: list[GedEdge] = []
    for edge in edges:
        if edge.type_key in grouped_relations:
            size = sizes_by_type[edge.type_key][edge.u]
            finished.append(
                GedEdge(
                    edge.u,
                    edge.v,
                    edge.type_key,
                    edge.label,
                    edge.attributes,
                    edge.raw_attributes,
                    {**edge.metadata, "group_size": size},
                )
            )
        else:
            finished.append(edge)

    # Canonical order, last: everything above may append in read order, and
    # nothing above reads a position.  The nodes decide, the edges follow.
    nodes.sort(key=canonical_node_key)
    rank = {node.id: index for index, node in enumerate(nodes)}
    finished.sort(key=lambda edge: _canonical_edge_key(edge, rank))

    histogram: dict[str, int] = {}
    for node in nodes:
        histogram[node.type_key] = histogram.get(node.type_key, 0) + 1
    relation_histogram: dict[str, int] = {}
    for edge in finished:
        relation_histogram[edge.type_key] = relation_histogram.get(edge.type_key, 0) + 1
    audit.counts = {
        "features": len(facts.features),
        "semanticNodes": len(nodes),
        "surfaceNodes": len(surface_ids),
        "relations": len(facts.relations),
        "gedEdges": len(finished),
        "hostsWithMembers": len(host_members),
        "L_ref": l_ref,
    }
    meta = {
        "partId": graph_id,
        "factsKey": facts.facts_key,
        "typeHistogram": dict(sorted(histogram.items())),
        "relationHistogram": dict(sorted(relation_histogram.items())),
        "surfaceNodeCount": len(surface_ids),
    }
    return GedGraph(
        graph_id=graph_id,
        nodes=tuple(nodes),
        edges=tuple(finished),
        fixed_nodes=tuple(fixed),
        l_ref=l_ref,
        meta=meta,
    )


def load_part(client, part_id: str, *, graph_id: str | None = None,
              audit: ProjectionAudit | None = None,
              representation: Representation = NX) -> GedGraph:
    """Read one part out of the store and project it."""
    return project_part(read_part(client, part_id), graph_id=graph_id or part_id,
                        audit=audit, representation=representation)
