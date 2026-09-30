"""Every IRI the system mints, in one place.

Instance IRIs are slash IRIs under ``https://cncgaide.org/parts/<partId>/``;
graph IRIs live under ``https://cncgaide.org/graph/`` and carry the content
key that decides whether a graph is current.
"""

from __future__ import annotations

from urllib.parse import quote

from tbox.nx import CG, GRAPHS, NX, PARTS

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XSD = "http://www.w3.org/2001/XMLSchema#"

INDEX_GRAPH = f"{GRAPHS}index"


def _segment(value: str) -> str:
    return quote(str(value), safe="")


def part(part_id: str) -> str:
    return f"{PARTS}{_segment(part_id)}"


def feature(part_id: str, node_id: str) -> str:
    return f"{part(part_id)}/feature/{_segment(node_id)}"


def face(part_id: str, face_id: str) -> str:
    return f"{part(part_id)}/face/{_segment(face_id)}"


def relation(part_id: str, edge_id: str) -> str:
    return f"{part(part_id)}/relation/{_segment(edge_id)}"


def ontology_graph(source_digest: str) -> str:
    return f"{GRAPHS}ontology/{source_digest}"


def shapes_graph(source_digest: str) -> str:
    return f"{GRAPHS}shapes/{source_digest}"


def facts_graph(part_id: str, key: str) -> str:
    return f"{GRAPHS}facts/{_segment(part_id)}/{key}"


def derived_graph(part_id: str, key: str) -> str:
    return f"{GRAPHS}derived/{_segment(part_id)}/{key}"


def whatif_graph(token: str) -> str:
    return f"{GRAPHS}whatif/{_segment(token)}"


__all__ = [
    "CG", "GRAPHS", "NX", "PARTS", "RDF", "RDFS", "XSD", "INDEX_GRAPH",
    "part", "feature", "face", "relation",
    "ontology_graph", "shapes_graph", "facts_graph", "derived_graph", "whatif_graph",
]
