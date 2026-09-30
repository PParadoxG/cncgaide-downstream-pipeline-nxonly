"""Load the built ontology and shapes into the store, one graph per source digest."""

from __future__ import annotations

from pathlib import Path

from kg import iri
from kg.fuseki import Fuseki
from tbox import nx as tbox

TBOX_FILE = tbox.DIST_DIR / "cncgaide_nx.ttl"
SHAPES_FILE = tbox.DIST_DIR / "shapes.ttl"
RULES_DIR = tbox.DIST_DIR / "rules"


def built() -> bool:
    return TBOX_FILE.is_file() and SHAPES_FILE.is_file() and (RULES_DIR / "ORDER.txt").is_file()


def require_built() -> None:
    if not built():
        raise RuntimeError("the ontology is not built; run: python run.py build")
    text = TBOX_FILE.read_text(encoding="utf-8")
    if f'cg:ontologyDigest "{tbox.ontology_digest()}"' not in text:
        raise RuntimeError("ontology/nx_v1_1/dist is older than source/*.yaml; run: python run.py build")


def ontology_graph() -> str:
    return iri.ontology_graph(tbox.ontology_digest())


def shapes_graph() -> str:
    return iri.shapes_graph(tbox.ontology_digest())


def ensure_loaded(client: Fuseki) -> dict:
    require_built()
    loaded = {}
    for graph, path in ((ontology_graph(), TBOX_FILE), (shapes_graph(), SHAPES_FILE)):
        if not client.graph_exists(graph):
            client.put_graph(graph, path.read_bytes(), "text/turtle")
            loaded[graph] = "loaded"
        else:
            loaded[graph] = "present"
    return loaded


def shapes_text() -> str:
    return SHAPES_FILE.read_text(encoding="utf-8")


def rule_order() -> list[str]:
    return (RULES_DIR / "ORDER.txt").read_text(encoding="utf-8").split()


def rule_text(name: str) -> str:
    return (RULES_DIR / f"{name}.ru").read_text(encoding="utf-8")


def stale_graphs(client: Fuseki) -> list[str]:
    """Ontology and shapes graphs of earlier source digests."""
    keep = {ontology_graph(), shapes_graph()}
    return [g for g in client.graphs(f"{iri.GRAPHS}ontology/") + client.graphs(f"{iri.GRAPHS}shapes/") if g not in keep]


def file_digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
