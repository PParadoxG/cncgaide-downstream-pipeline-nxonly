"""One part's facts, read out of the store.

The projection needs a part as a set of plain values: its faces, its features
with NX's attribute values and the gaps beside them, and its relations with
their properties and terminals.  This module asks the store for exactly that
and nothing else, so the projection below it never writes SPARQL and never
sees an HTTP client.

What is current is read from the index graph, never from a file name: a part
is named by its ``partId``, and the facts graph that answers for it is the
one the index points at.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from contract.face_ids import raw_cad_face_id
from kg import iri
from tbox import nx as tbox


#: The part-level predicate that carries the length reference every geometric
#: attribute is normalised by (the diameter of the part's vertex cloud).
LENGTH_REFERENCE = "geometricDiameter"

#: Relation predicates that describe the edge itself rather than one of its
#: measured quantities.
_RELATION_STRUCTURE = frozenset(("relationId", "relationType", "from", "to", "directed",
                                 "sourceRule", "partOf", "evidence", "diagnostic", "terminal"))


class MissingFact(LookupError):
    """The store holds the part, but not a fact the projection needs."""


class PartAbsent(LookupError):
    """No such part in the index graph."""


@dataclass(frozen=True)
class FaceFacts:
    face_id: str
    surface_type: str
    area: float | None


@dataclass(frozen=True)
class FeatureFacts:
    node_id: str
    feature_type: str
    attributes: Mapping[str, Any]
    attribute_gaps: Mapping[str, str]
    face_ids: tuple[str, ...]


@dataclass(frozen=True)
class TerminalFacts:
    terminal_feature: str | None
    host_owner: str | None
    terminal_role: str | None


@dataclass(frozen=True)
class RelationFacts:
    relation_id: str
    relation_type: str
    source: str
    target: str
    properties: Mapping[str, Any]
    terminals: tuple[TerminalFacts, ...]


@dataclass(frozen=True)
class PartFacts:
    part_id: str
    facts_key: str
    facts_graph: str
    source_step: str | None
    length_reference: float | None
    faces: Mapping[str, FaceFacts]
    features: tuple[FeatureFacts, ...]
    relations: tuple[RelationFacts, ...]

    def require_length_reference(self) -> float:
        if self.length_reference is None or not self.length_reference > 0:
            raise MissingFact(
                f"{self.part_id}: the facts graph publishes no cg:{LENGTH_REFERENCE}, "
                "so no length reference can be read")
        return float(self.length_reference)


@dataclass(frozen=True)
class IndexRow:
    part_id: str
    status: str | None
    facts_key: str
    facts_graph: str
    source_step: str | None


# --------------------------------------------------------------- literals

def _quote(text: str) -> str:
    escaped = (str(text).replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n").replace("\r", "\\r"))
    return f'"{escaped}"'


def _scalar(binding: dict | None) -> Any:
    """One SPARQL binding as the Python value the store was given."""
    if binding is None:
        return None
    if binding.get("type") == "uri":
        return binding["value"]
    text = binding.get("value")
    datatype = binding.get("datatype") or ""
    if datatype in (f"{iri.XSD}decimal", f"{iri.XSD}double", f"{iri.XSD}float"):
        return float(text)
    if datatype == f"{iri.XSD}integer":
        return int(text)
    if datatype == f"{iri.XSD}boolean":
        return text in ("true", "1")
    if datatype == f"{iri.RDF}JSON":
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def _local(term: str, namespace: str) -> str:
    return term[len(namespace):] if term.startswith(namespace) else term


def _bindings(client, sparql: str) -> list[dict]:
    return client.query(sparql)["results"]["bindings"]


# ------------------------------------------------------------------ index

def index_rows(client) -> dict[str, IndexRow]:
    """Every part the index knows, by id."""
    rows = _bindings(client, f"""
        PREFIX cg: <{tbox.CG}>
        SELECT ?partId ?status ?factsKey ?factsGraph ?sourceStep WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{
            ?part cg:partId ?partId .
            OPTIONAL {{ ?part cg:status ?status }}
            OPTIONAL {{ ?part cg:factsKey ?factsKey }}
            OPTIONAL {{ ?part cg:factsGraph ?factsGraph }}
            OPTIONAL {{ ?part cg:sourceStep ?sourceStep }}
          }}
        }}""")
    out: dict[str, IndexRow] = {}
    for row in rows:
        part_id = row["partId"]["value"]
        out[part_id] = IndexRow(
            part_id=part_id,
            status=row.get("status", {}).get("value"),
            facts_key=row.get("factsKey", {}).get("value", ""),
            facts_graph=row.get("factsGraph", {}).get("value", ""),
            source_step=row.get("sourceStep", {}).get("value"),
        )
    return out


def index_row(client, part_id: str) -> IndexRow:
    rows = index_rows(client)
    try:
        return rows[part_id]
    except KeyError:
        raise PartAbsent(f"{part_id}: not in the store") from None


# ------------------------------------------------------------------ facts

def read_part(client, part_id: str, *, row: IndexRow | None = None) -> PartFacts:
    """Everything the projection reads about one part, in one pass."""
    row = row or index_row(client, part_id)
    if not row.facts_graph:
        raise MissingFact(f"{part_id}: the index names no facts graph")
    graph = row.facts_graph
    cg, nx = tbox.CG, tbox.NX

    part_block: dict[str, Any] = {}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?p ?o WHERE {{ GRAPH <{graph}> {{
              ?s a cg:Part ; cg:partId {_quote(part_id)} ; ?p ?o }} }}"""):
        name = _local(binding["p"]["value"], cg)
        if name not in part_block:
            part_block[name] = _scalar(binding["o"])

    faces: dict[str, FaceFacts] = {}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?faceId ?surfaceType ?area WHERE {{ GRAPH <{graph}> {{
              ?f cg:faceId ?faceId .
              OPTIONAL {{ ?f cg:surfaceType ?surfaceType }}
              OPTIONAL {{ ?f cg:area ?area }} }} }}"""):
        face_id = binding["faceId"]["value"]
        area = _scalar(binding.get("area"))
        faces[face_id] = FaceFacts(
            face_id=face_id,
            surface_type=str(_scalar(binding.get("surfaceType")) or "UNKNOWN"),
            area=float(area) if isinstance(area, (int, float)) else None,
        )

    types: dict[str, str] = {}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?nodeId ?type WHERE {{ GRAPH <{graph}> {{
              ?f cg:nodeId ?nodeId ; a ?type }} }}"""):
        types[binding["nodeId"]["value"]] = _local(binding["type"]["value"], nx)

    attributes: dict[str, dict[str, Any]] = {node_id: {} for node_id in types}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?nodeId ?p ?v WHERE {{ GRAPH <{graph}> {{
              ?f cg:nodeId ?nodeId ; ?p ?v .
              FILTER(STRSTARTS(STR(?p), {_quote(nx)})) }} }}"""):
        attributes.setdefault(binding["nodeId"]["value"], {})[
            _local(binding["p"]["value"], nx)] = _scalar(binding["v"])

    gaps: dict[str, dict[str, str]] = {node_id: {} for node_id in types}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?nodeId ?attribute ?reason WHERE {{ GRAPH <{graph}> {{
              ?f cg:nodeId ?nodeId ; cg:attributeGap ?g .
              ?g cg:attribute ?attribute ; cg:reason ?reason }} }}"""):
        gaps.setdefault(binding["nodeId"]["value"], {})[
            _local(binding["attribute"]["value"], nx)] = binding["reason"]["value"]

    owned: dict[str, set[str]] = {node_id: set() for node_id in types}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?nodeId ?faceId WHERE {{ GRAPH <{graph}> {{
              ?f cg:nodeId ?nodeId ; cg:ownsFace ?face . ?face cg:faceId ?faceId }} }}"""):
        owned.setdefault(binding["nodeId"]["value"], set()).add(binding["faceId"]["value"])

    features = tuple(
        FeatureFacts(
            node_id=node_id,
            feature_type=types[node_id],
            attributes=attributes.get(node_id, {}),
            attribute_gaps=gaps.get(node_id, {}),
            face_ids=tuple(sorted(owned.get(node_id, ()), key=_face_sort_key)),
        )
        for node_id in sorted(types)
    )

    relations = _read_relations(client, graph, cg)
    length = part_block.get(LENGTH_REFERENCE)
    return PartFacts(
        part_id=part_id,
        facts_key=row.facts_key,
        facts_graph=graph,
        source_step=part_block.get("sourceStep") or row.source_step,
        length_reference=float(length) if isinstance(length, (int, float)) else None,
        faces=faces,
        features=features,
        relations=relations,
    )


def _face_sort_key(face_id: str) -> tuple[float, str]:
    number = raw_cad_face_id(face_id)
    return (float(number) if number is not None else float("inf"), str(face_id))


def _read_relations(client, graph: str, cg: str) -> tuple[RelationFacts, ...]:
    heads: dict[str, tuple[str, str, str]] = {}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?relationId ?relationType ?source ?target WHERE {{ GRAPH <{graph}> {{
              ?r cg:relationId ?relationId ; cg:relationType ?relationType ;
                 cg:from ?a ; cg:to ?b .
              ?a cg:nodeId ?source . ?b cg:nodeId ?target }} }}"""):
        heads[binding["relationId"]["value"]] = (
            _local(binding["relationType"]["value"], cg),
            binding["source"]["value"],
            binding["target"]["value"],
        )

    properties: dict[str, dict[str, Any]] = {key: {} for key in heads}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?relationId ?p ?v WHERE {{ GRAPH <{graph}> {{
              ?r cg:relationId ?relationId ; ?p ?v . FILTER(isLiteral(?v)) }} }}"""):
        name = _local(binding["p"]["value"], cg)
        if name in _RELATION_STRUCTURE:
            continue
        properties.setdefault(binding["relationId"]["value"], {})[name] = _scalar(binding["v"])

    terminals: dict[str, list[TerminalFacts]] = {key: [] for key in heads}
    for binding in _bindings(client, f"""
            PREFIX cg: <{cg}>
            SELECT ?relationId ?terminalFeature ?hostOwner ?terminalRole WHERE {{ GRAPH <{graph}> {{
              ?r cg:relationId ?relationId ; cg:terminal ?t .
              OPTIONAL {{ ?t cg:terminalFeature ?tf . ?tf cg:nodeId ?terminalFeature }}
              OPTIONAL {{ ?t cg:hostOwner ?ho . ?ho cg:nodeId ?hostOwner }}
              OPTIONAL {{ ?t cg:terminalRole ?terminalRole }} }} }}"""):
        terminals.setdefault(binding["relationId"]["value"], []).append(TerminalFacts(
            terminal_feature=binding.get("terminalFeature", {}).get("value"),
            host_owner=binding.get("hostOwner", {}).get("value"),
            terminal_role=binding.get("terminalRole", {}).get("value"),
        ))

    return tuple(
        RelationFacts(
            relation_id=relation_id,
            relation_type=heads[relation_id][0],
            source=heads[relation_id][1],
            target=heads[relation_id][2],
            properties=properties.get(relation_id, {}),
            # Blank nodes have no order in the store, so the terminals are
            # sorted; nothing the projection derives from them depends on the
            # order they were written in.
            terminals=tuple(sorted(
                terminals.get(relation_id, ()),
                key=lambda t: (t.terminal_feature or "", t.host_owner or "", t.terminal_role or ""))),
        )
        for relation_id in sorted(heads)
    )
