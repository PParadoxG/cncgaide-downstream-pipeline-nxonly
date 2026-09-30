"""One part's facts as RDF: the serialiser the NX journal writes with.

Standard library only, because it runs inside NX's own Python.  The output is
one TriG file holding one named graph: the part, its faces, NX's features
with NX's attribute names and values, the pipeline's derived quantities and
measurements, the relations with their properties, evidence and terminals,
and the part-level diagnostics.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path

from kg import iri
from tbox import nx as tbox

RDF_TYPE = f"<{iri.RDF}type>"
RDFS_LABEL = f"<{iri.RDFS}label>"


def nx(name: str) -> str:
    return f"<{iri.NX}{name}>"


def cg(name: str) -> str:
    return f"<{iri.CG}{name}>"


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))


def string(value) -> str:
    return f'"{_escape(str(value))}"'


def decimal(value) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f'"{value}"^^<{iri.XSD}decimal>'
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return f'"{format(Decimal(repr(value)), "f")}"^^<{iri.XSD}decimal>'
    return None


def integer(value) -> str:
    return f'"{int(value)}"^^<{iri.XSD}integer>'


def boolean(value) -> str:
    return f'"{"true" if value else "false"}"^^<{iri.XSD}boolean>'


def literal(value) -> str | None:
    """A typed literal for any scalar; JSON text for anything structured."""
    if value is None:
        return None
    if isinstance(value, bool):
        return boolean(value)
    if isinstance(value, int):
        return integer(value)
    if isinstance(value, float):
        return decimal(value)
    if isinstance(value, str):
        return string(value)
    if isinstance(value, (list, tuple)) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return string(" ".join(format(Decimal(repr(float(v))), "f") for v in value))
    return f'"{_escape(json.dumps(value, sort_keys=True, default=str))}"^^<{iri.RDF}JSON>'


def attribute_literal(name: str, value) -> str | None:
    """NX attribute values typed by the declared DataType."""
    record = tbox.attribute_record(name) or {}
    data_type = record.get("dataType")
    if value is None:
        return None
    if data_type == "Double":
        return decimal(float(value)) if isinstance(value, (int, float)) and not isinstance(value, bool) else string(value)
    if data_type == "Integer":
        return integer(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else string(value)
    if data_type == "Bool":
        return boolean(bool(value))
    if data_type == "String":
        if isinstance(value, bool):
            return string("true" if value else "false")
        return string(value if isinstance(value, str) else str(value))
    return literal(value)


class Triples:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._blank = 0

    def add(self, s: str, p: str, o: str | None) -> None:
        if o is None:
            return
        self.lines.append(f"{s} {p} {o} .")

    def blank(self) -> str:
        self._blank += 1
        return f"_:b{self._blank}"

    def add_map(self, subject: str, predicate: str, mapping: dict, *, key_prop: str, value_prop: str) -> None:
        """One blank node per entry: ``subject predicate [ key_prop "k" ; value_prop v ]``."""
        for key in sorted(mapping):
            node = self.blank()
            self.add(subject, predicate, node)
            self.add(node, cg(key_prop), string(key))
            self.add(node, cg(value_prop), literal(mapping[key]))


def _vector(value) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return literal([float(v) for v in value])
    return None


def geometric_diameter(model) -> float | None:
    """Largest distance between two vertices of the part, or None without vertices."""
    vertices = getattr(model, "vertices", None) or {}
    coords = [tuple(float(c) for c in v.coordinates) for v in vertices.values()]
    best = 0.0
    for i, (ax, ay, az) in enumerate(coords):
        for bx, by, bz in coords[i + 1:]:
            dx, dy, dz = ax - bx, ay - by, az - bz
            d = math.sqrt(dx * dx + dy * dy + dz * dz)
            if d > best:
                best = d
    return best if best > 0 else None


def part_triples(t: Triples, part_id: str, model, diagnostics: dict, relation_diagnostics: dict,
                 derived_summary: dict, source: dict) -> str:
    p = f"<{iri.part(part_id)}>"
    t.add(p, RDF_TYPE, cg("Part"))
    t.add(p, cg("partId"), string(part_id))
    t.add(p, RDFS_LABEL, string(part_id))
    for key in ("sourceStep", "sourceSha256", "factsKey"):
        if source.get(key):
            t.add(p, cg(key), string(source[key]))
    if source.get("factsGraph"):
        t.add(p, cg("factsGraph"), f"<{source['factsGraph']}>")
    metadata = getattr(model, "metadata", None)
    if metadata is not None:
        t.add(p, cg("lengthUnit"), string(getattr(metadata, "length_unit", "") or ""))
        t.add(p, cg("geometryProvider"), string(getattr(metadata, "geometry_provider", "") or "nxline"))
    t.add(p, cg("faceCount"), integer(len(getattr(model, "faces", {}) or {})))
    diameter = geometric_diameter(model)
    if diameter is not None:
        t.add(p, cg("geometricDiameter"), decimal(diameter))
    for key in ("recognitionProvider", "projection", "registeredTypeCount", "featureCount",
                "claimedFaceCount", "unmatchedNativeFaceCount"):
        if key in diagnostics:
            t.add(p, cg(key), literal(diagnostics[key]))
    for key, value in sorted((diagnostics.get("recipe") or {}).items()):
        node = t.blank()
        t.add(p, cg("recipe"), node)
        t.add(node, cg("name"), string(key))
        t.add(node, cg("value"), literal(value))
    for key, value in sorted((diagnostics.get("environment") or {}).items()):
        if value not in (None, ""):
            t.add(p, cg(f"nx_{key}"), literal(value))
    for face_id in diagnostics.get("unclaimedFaceIds") or []:
        t.add(p, cg("unclaimedFace"), f"<{iri.face(part_id, face_id)}>")
    for name, counts in sorted((derived_summary or {}).items()):
        node = t.blank()
        t.add(p, cg("derivedSummary"), node)
        t.add(node, cg("quantity"), cg(name))
        t.add(node, cg("measured"), integer(counts.get("measured", 0)))
        t.add(node, cg("refused"), integer(counts.get("refused", 0)))
    for edge_type, count in sorted(((relation_diagnostics or {}).get("relationCounts") or {}).items()):
        node = t.blank()
        t.add(p, cg("relationCount"), node)
        t.add(node, cg("relationType"), cg(edge_type))
        t.add(node, cg("count"), integer(count))
    if relation_diagnostics:
        t.add(p, cg("relationDiagnostics"), literal(relation_diagnostics))
    return p


def face_triples(t: Triples, part_id: str, model, part: str) -> None:
    faces = getattr(model, "faces", {}) or {}
    for face_id in sorted(faces, key=lambda fid: int(str(fid).rsplit("_", 1)[-1]) if str(fid).rsplit("_", 1)[-1].isdigit() else 0):
        face = faces[face_id]
        f = f"<{iri.face(part_id, face_id)}>"
        t.add(f, RDF_TYPE, cg("Face"))
        t.add(f, cg("partOf"), part)
        t.add(f, cg("faceId"), string(face_id))
        surface = getattr(face, "surface_type", None)
        t.add(f, cg("surfaceType"), string(getattr(surface, "value", surface)))
        t.add(f, cg("area"), decimal(float(face.area)))
        t.add(f, cg("isReversed"), boolean(bool(face.is_reversed)))
        t.add(f, cg("isOuter"), boolean(bool(face.is_outer)))
        parameters = face.parameters or {}
        for key in ("normal", "axis_direction", "axis", "axis_location", "location", "center", "apex"):
            if key in parameters:
                t.add(f, cg(f"surface_{key}"), _vector(parameters[key]))
        for key in ("radius", "semi_angle", "major_radius", "minor_radius"):
            if key in parameters and isinstance(parameters[key], (int, float)):
                t.add(f, cg(f"surface_{key}"), decimal(float(parameters[key])))
        if face.centroid:
            t.add(f, cg("centroid"), _vector(face.centroid))
        if face.bbox:
            t.add(f, cg("bboxMin"), _vector(face.bbox.get("min")))
            t.add(f, cg("bboxMax"), _vector(face.bbox.get("max")))
        for raw in face.merged_from or []:
            t.add(f, cg("cadFaceId"), string(raw))
        for adjacency in face.adjacencies or []:
            node = t.blank()
            t.add(f, cg("adjacency"), node)
            t.add(node, cg("face"), f"<{iri.face(part_id, adjacency.adjacent_face_id)}>")
            t.add(node, cg("sharedEdge"), string(adjacency.shared_edge_id))
            connection = adjacency.connection_type
            t.add(node, cg("concavity"), string(getattr(connection, "value", connection)))


def feature_triples(t: Triples, part_id: str, nodes, part: str) -> None:
    for node in nodes:
        f = f"<{iri.feature(part_id, node.nodeId)}>"
        t.add(f, RDF_TYPE, nx(node.featureType))
        t.add(f, cg("partOf"), part)
        t.add(f, cg("nodeId"), string(node.nodeId))
        nx_block = (node.diagnostics or {}).get("nx") or {}
        if nx_block.get("typeDisplayName"):
            t.add(f, RDFS_LABEL, string(nx_block["typeDisplayName"]))
        for key in ("name", "sourceType", "status"):
            if nx_block.get(key):
                t.add(f, cg(f"nx_{key}"), string(nx_block[key]))
        for name in sorted(node.attributes):
            t.add(f, nx(name), attribute_literal(name, node.attributes[name]))
        for name, reason in sorted((node.missingAttributes or {}).items()):
            gap = t.blank()
            t.add(f, cg("attributeGap"), gap)
            t.add(gap, RDF_TYPE, cg("AttributeGap"))
            t.add(gap, cg("attribute"), nx(name))
            t.add(gap, cg("reason"), string(reason))
        reading = (node.diagnostics or {}).get("attributeReading") or {}
        for pile in ("ruleDefault", "identity", "zeroValued"):
            for name in reading.get(pile) or []:
                r = t.blank()
                t.add(f, cg("attributeReading"), r)
                t.add(r, cg("attribute"), nx(name))
                t.add(r, cg("pile"), string(pile))
        for face_id in node.partmodelFaceIds or []:
            t.add(f, cg("ownsFace"), f"<{iri.face(part_id, face_id)}>")
        for name, entry in sorted((node.derived or {}).items()):
            if entry.get("value") is not None:
                t.add(f, cg(name), decimal(float(entry["value"])))
                m = t.blank()
                t.add(f, cg("measurement"), m)
                t.add(m, RDF_TYPE, cg("Measurement"))
                t.add(m, cg("quantity"), cg(name))
                t.add(m, cg("value"), decimal(float(entry["value"])))
                if entry.get("method"):
                    t.add(m, cg("method"), string(entry["method"]))
                if entry.get("derivedBy"):
                    t.add(m, cg("derivedBy"), string(entry["derivedBy"]))
                for key, value in sorted((entry.get("evidence") or {}).items()):
                    if key.endswith("FaceIds") and isinstance(value, list):
                        for face_id in value:
                            t.add(m, cg("evidenceFace"), f"<{iri.face(part_id, face_id)}>")
                    else:
                        e = t.blank()
                        t.add(m, cg("evidence"), e)
                        t.add(e, cg("key"), string(key))
                        t.add(e, cg("value"), literal(value))
            else:
                m = t.blank()
                t.add(f, cg("measurementRefusal"), m)
                t.add(m, RDF_TYPE, cg("MeasurementRefusal"))
                t.add(m, cg("quantity"), cg(name))
                t.add(m, cg("reason"), string(entry.get("reason") or "refused without a recorded reason"))


def relation_triples(t: Triples, part_id: str, edges, part: str) -> None:
    for edge in edges:
        r = f"<{iri.relation(part_id, edge.edgeId)}>"
        t.add(r, RDF_TYPE, cg("FeatureRelation"))
        t.add(r, cg("partOf"), part)
        t.add(r, cg("relationId"), string(edge.edgeId))
        t.add(r, cg("relationType"), cg(edge.edgeType))
        t.add(r, cg("from"), f"<{iri.feature(part_id, edge.source)}>")
        t.add(r, cg("to"), f"<{iri.feature(part_id, edge.target)}>")
        t.add(r, cg("directed"), boolean(bool(edge.directed)))
        if edge.sourceRule:
            t.add(r, cg("sourceRule"), string(edge.sourceRule))
        properties = dict(edge.properties or {})
        terminals = properties.pop("terminals", None)
        for key in sorted(properties):
            t.add(r, cg(key), literal(properties[key]))
        if terminals:
            witnesses = (edge.evidence or {}).get("locatedOnWitnesses") or []
            for index, terminal in enumerate(terminals):
                witness = witnesses[index] if index < len(witnesses) else {}
                node = t.blank()
                t.add(r, cg("terminal"), node)
                t.add(node, RDF_TYPE, cg("LocatedOnTerminal"))
                source_id = witness.get("semanticSourceFeatureId")
                host_id = witness.get("hostOwnerNodeId")
                if source_id is None:
                    source_id = edge.target if edge.source == host_id else edge.source
                if host_id is None:
                    host_id = edge.target if edge.source == source_id else edge.source
                t.add(node, cg("terminalFeature"), f"<{iri.feature(part_id, source_id)}>")
                t.add(node, cg("hostOwner"), f"<{iri.feature(part_id, host_id)}>")
                if witness.get("hostFaceId"):
                    t.add(node, cg("hostFace"), f"<{iri.face(part_id, witness['hostFaceId'])}>")
                if witness.get("terminalRole"):
                    t.add(node, cg("terminalRole"), string(witness["terminalRole"]))
                if terminal.get("hostSurfaceType"):
                    t.add(node, cg("hostSurfaceType"), string(terminal["hostSurfaceType"]))
                if terminal.get("hostSurfaceNormal") is not None:
                    t.add(node, cg("hostSurfaceNormal"), literal(terminal["hostSurfaceNormal"]))
        evidence = {k: v for k, v in (edge.evidence or {}).items() if k != "locatedOnWitnesses"}
        t.add_map(r, cg("evidence"), evidence, key_prop="key", value_prop="value")
        t.add_map(r, cg("diagnostic"), edge.diagnostics or {}, key_prop="key", value_prop="value")


def build(part_id: str, model, nodes, edges, diagnostics: dict, *, relation_diagnostics: dict | None = None,
          derived_summary: dict | None = None, source: dict | None = None) -> Triples:
    t = Triples()
    part = part_triples(t, part_id, model, diagnostics or {}, relation_diagnostics or {},
                        derived_summary or {}, source or {})
    face_triples(t, part_id, model, part)
    feature_triples(t, part_id, nodes, part)
    relation_triples(t, part_id, edges, part)
    return t


def write_trig(path: str | Path, graph_iri: str, triples: Triples) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join("  " + line for line in triples.lines)
    text = f"<{graph_iri}> {{\n{body}\n}}\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return len(triples.lines)
