"""source/*.yaml -> dist/shapes.ttl (SHACL shapes for the facts graph and the
derived graph).

* one shape per recognisable class: every readable declared attribute has at
  most one value, of the declared datatype; the feature belongs to a part;
* FeatureRelation, LocatedOnTerminal, Verdict and KPIResult shapes.
"""
from __future__ import annotations

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, SH, XSD

from common import BlankNodes, CG, DIST, NX, XSD_BY_DATATYPE, OUTCOMES, local_name, tbox, write_text

nx = Namespace(NX)
cg = Namespace(CG)


def prop(g: Graph, bnode: BlankNodes, shape, path, **constraints) -> None:
    node = bnode("property", local_name(shape), local_name(path))
    g.add((shape, SH.property, node))
    g.add((node, SH.path, path))
    for key, value in constraints.items():
        g.add((node, SH[key], value))


def build() -> Graph:
    bnode = BlankNodes()
    g = Graph()
    g.bind("nx", nx)
    g.bind("cg", cg)
    g.bind("sh", SH)

    for name in tbox.recognisable_classes():
        if tbox.is_abstract(name):
            continue
        shape = cg[f"{name}Shape"]
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetClass, nx[name]))
        prop(g, bnode, shape, cg.partOf, minCount=Literal(1), maxCount=Literal(1), **{"class": cg.Part})
        prop(g, bnode, shape, cg.nodeId, minCount=Literal(1), maxCount=Literal(1), datatype=XSD.string)
        for attribute in tbox.effective_attributes(name):
            record = tbox.attribute_record(attribute) or {}
            data_type = record.get("dataType")
            if not record.get("apiReadable") or data_type not in XSD_BY_DATATYPE:
                continue
            prop(g, bnode, shape, nx[attribute], maxCount=Literal(1), datatype=XSD[XSD_BY_DATATYPE[data_type]])
        for derived_name in tbox.derived_attributes():
            prop(g, bnode, shape, cg[derived_name], maxCount=Literal(1), datatype=XSD.decimal)

    relation = cg.FeatureRelationShape
    g.add((relation, RDF.type, SH.NodeShape))
    g.add((relation, SH.targetClass, cg.FeatureRelation))
    prop(g, bnode, relation, cg.relationType, minCount=Literal(1), maxCount=Literal(1), nodeKind=SH.IRI)
    prop(g, bnode, relation, cg["from"], minCount=Literal(1), maxCount=Literal(1))
    prop(g, bnode, relation, cg.to, minCount=Literal(1), maxCount=Literal(1))
    prop(g, bnode, relation, cg.partOf, minCount=Literal(1), maxCount=Literal(1))
    for record in tbox.relation_types().values():
        for p in record.get("properties") or []:
            prop(g, bnode, relation, cg[p["name"]], maxCount=Literal(1), datatype=XSD[p["range"].split(":")[1]])

    terminal = cg.LocatedOnTerminalShape
    g.add((terminal, RDF.type, SH.NodeShape))
    g.add((terminal, SH.targetClass, cg.LocatedOnTerminal))
    prop(g, bnode, terminal, cg.terminalFeature, minCount=Literal(1), maxCount=Literal(1))
    prop(g, bnode, terminal, cg.hostOwner, minCount=Literal(1), maxCount=Literal(1))
    prop(g, bnode, terminal, cg.hostFace, minCount=Literal(1), maxCount=Literal(1))

    verdict = cg.VerdictShape
    g.add((verdict, RDF.type, SH.NodeShape))
    g.add((verdict, SH.targetClass, cg.Verdict))
    prop(g, bnode, verdict, cg.heuristic, minCount=Literal(1), maxCount=Literal(1), nodeKind=SH.IRI)
    prop(g, bnode, verdict, cg.target, minCount=Literal(1), maxCount=Literal(1))
    prop(g, bnode, verdict, cg.partOf, minCount=Literal(1), maxCount=Literal(1))
    outcome = bnode("property", "VerdictShape", "outcome")
    g.add((verdict, SH.property, outcome))
    g.add((outcome, SH.path, cg.outcome))
    g.add((outcome, SH.minCount, Literal(1)))
    g.add((outcome, SH.maxCount, Literal(1)))
    # The list of admissible outcomes, linked by hand: rdflib's Collection mints
    # blank nodes of its own, and every blank node in dist/ carries a label that
    # comes from the source.
    cells = [bnode("outcome", index) for index in range(len(OUTCOMES))]
    for index, (cell, name) in enumerate(zip(cells, OUTCOMES)):
        g.add((cell, RDF.first, cg[name]))
        g.add((cell, RDF.rest, cells[index + 1] if index + 1 < len(cells) else RDF.nil))
    g.add((outcome, SH["in"], cells[0]))

    kpi = cg.KPIResultShape
    g.add((kpi, RDF.type, SH.NodeShape))
    g.add((kpi, SH.targetClass, cg.KPIResult))
    prop(g, bnode, kpi, cg.kpiType, minCount=Literal(1), maxCount=Literal(1), nodeKind=SH.IRI)
    prop(g, bnode, kpi, cg.kpiValue, minCount=Literal(1), maxCount=Literal(1))
    prop(g, bnode, kpi, cg.kpiUnit, minCount=Literal(1), maxCount=Literal(1), datatype=XSD.string)
    return g


def main() -> None:
    g = build()
    write_text(DIST / "shapes.ttl", g.serialize(format="turtle"))
    print(f"shapes.ttl: {len(g)} triples")


if __name__ == "__main__":
    main()
