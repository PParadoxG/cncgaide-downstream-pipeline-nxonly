"""Shared paths, namespaces and helpers of the build chain."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from rdflib import BNode

HERE = Path(__file__).resolve().parent
ONTOLOGY = HERE.parent
SOURCE = ONTOLOGY / "source"
# Everything generated goes under DIST.  The environment variable lets the
# reproducibility check generate a second copy somewhere else and compare it
# with what is on disk, without a generator knowing it is being checked.
DIST = Path(os.environ["CNCGAIDE_DIST"]).resolve() if os.environ.get("CNCGAIDE_DIST") else ONTOLOGY / "dist"
RULES = DIST / "rules"
ROOT = ONTOLOGY.parents[1]
SRC = ROOT / "src"

for candidate in (str(SRC), str(SRC / "nxline" / "vendor")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from tbox import nx as tbox  # noqa: E402

NX = tbox.NX
CG = tbox.CG
ONTOLOGY_IRI = "https://cncgaide.org/ontology/nx/1.1"

PREFIXES = {
    "nx": NX,
    "cg": CG,
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "sh": "http://www.w3.org/ns/shacl#",
}

XSD_BY_DATATYPE = {"Double": "decimal", "Integer": "integer", "String": "string", "Bool": "boolean"}

OUTCOMES = ("PASS", "FAIL", "NOT_EVALUABLE", "NOT_APPLICABLE")


_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


def local_name(term) -> str:
    """The last segment of an IRI, which is how the vocabulary names things."""
    return str(term).rsplit("#", 1)[-1].rsplit("/", 1)[-1]


class BlankNodes:
    """Blank nodes labelled after what they describe.

    An RDF blank node has no name of its own, so rdflib invents one, and the
    Turtle serialiser orders a subject's objects by the label it invented: the
    same graph written twice comes out in two different orders.  Deriving the
    label from the source instead makes the serialisation a function of the
    source alone, which is what lets dist/ be compared byte for byte.

    A label is a position in the source (a class and a section index, a rule
    and a class), so two blank nodes describing two different things cannot
    share one.  If they ever did the graph would silently merge them, so that
    is an error here rather than a surprise downstream.
    """

    def __init__(self) -> None:
        self._issued: set[str] = set()

    def __call__(self, *parts) -> BNode:
        label = "_".join(_UNSAFE.sub("_", str(part)) for part in parts)
        if label in self._issued:
            raise ValueError(f"two blank nodes claim the label {label!r}")
        self._issued.add(label)
        return BNode(label)


def sparql_prefixes() -> str:
    return "\n".join(f"PREFIX {k}: <{v}>" for k, v in PREFIXES.items() if k != "sh") + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
