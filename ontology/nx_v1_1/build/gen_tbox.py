"""source/*.yaml -> dist/cncgaide_nx.ttl (the ontology: classes, attributes,
relations, derived quantities, thresholds, heuristics, KPI vocabulary).

Everything the run-time rules read about the vocabulary is in this one graph:
class tree and labels, per-class attribute declarations, the ladder section
table, heuristic domains and per-class required attributes, threshold values,
KPI types and derivations.  ``display.yaml`` is not published here.
"""
from __future__ import annotations

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS, XSD

from common import BlankNodes, CG, DIST, NX, ONTOLOGY_IRI, XSD_BY_DATATYPE, OUTCOMES, tbox, write_text

nx = Namespace(NX)
cg = Namespace(CG)


def literal(value):
    if isinstance(value, bool):
        return Literal(value)
    if isinstance(value, int):
        return Literal(value)
    if isinstance(value, float):
        return Literal(str(value), datatype=XSD.decimal)
    return Literal(str(value))


def build() -> Graph:
    bnode = BlankNodes()
    g = Graph()
    g.bind("nx", nx)
    g.bind("cg", cg)
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("owl", OWL)

    onto = URIRef(ONTOLOGY_IRI)
    g.add((onto, RDF.type, OWL.Ontology))
    g.add((onto, OWL.versionInfo, Literal(tbox.ONTOLOGY_VERSION)))
    g.add((onto, RDFS.label, Literal("CNCgAIde NX feature ontology")))
    for source in tbox.classes_head()["source"]:
        g.add((onto, DCTERMS.source, Literal(f"{source['path']} sha256 {source['sha256']}")))
    g.add((onto, cg.sourceDigest, Literal(tbox.source_digest())))
    g.add((onto, cg.ontologyDigest, Literal(tbox.ontology_digest())))

    # ---- pipeline classes ------------------------------------------------
    for name, definition in {
        "Part": "One part, as read from one STEP file.",
        "Face": "One face of the part's boundary representation.",
        "FeatureRelation": "One relation between two features.",
        "RelationType": "The kind of a feature relation.",
        "LocatedOnTerminal": "One resolved opening of a feature and the host face it opens onto.",
        "Measurement": "One derived quantity measured by the geometry kernel, with its method and evidence.",
        "MeasurementRefusal": "A derived quantity the kernel could not measure, with the reason.",
        "AttributeGap": "An attribute NX declares on the feature and did not hand over, with NX's reason.",
        "Threshold": "A named limit a rule compares against.",
        "Heuristic": "One design rule with its domain, condition and effect on KPIs.",
        "Verdict": "The outcome of one rule on one feature or one relation.",
        "Outcome": "One of the four outcomes of a rule.",
        "Value": "A named quantity computed while evaluating a rule.",
        "KPIType": "Controlled vocabulary of key performance indicators.",
        "KPIResult": "One value of one KPI type for one feature or one run.",
        "KpiDerivation": "A rule deriving a feature-level KPI result from geometry.",
    }.items():
        g.add((cg[name], RDF.type, OWL.Class))
        g.add((cg[name], RDFS.label, Literal(name)))
        g.add((cg[name], SKOS.definition, Literal(definition)))
    for outcome in OUTCOMES:
        g.add((cg[outcome], RDF.type, cg.Outcome))
        g.add((cg[outcome], RDFS.label, Literal(outcome)))

    # ---- NX classes ------------------------------------------------------
    for name in tbox.class_names():
        record = tbox.class_record(name)
        c = nx[name]
        g.add((c, RDF.type, OWL.Class))
        g.add((c, RDFS.label, Literal(record.get("label") or name)))
        if record["parent"]:
            g.add((c, RDFS.subClassOf, nx[record["parent"]]))
        else:
            g.add((c, cg.parentOutsideSchema, Literal(tbox.classes_head()["rootParent"])))
        g.add((c, cg.abstract, Literal(bool(record["abstract"]))))
        g.add((c, cg.recognisable, Literal(bool(record.get("recognisable")))))
        for attribute in record["attributes"]:
            g.add((c, cg.declaresAttribute, nx[attribute]))
        label = record.get("label") or ""
        if tbox.in_family(name, "STEP") and not record["abstract"]:
            g.add((c, cg.blind, Literal("Blind" in label)))
        sections = tbox.sections(name)
        if sections:
            for s in sections:
                node = bnode("section", name, s["index"])
                g.add((c, cg.section, node))
                g.add((node, cg["index"], Literal(s["index"])))
                g.add((node, cg.diameterAttribute, nx[s["diameterAttribute"]]))
                g.add((node, cg.depthToAttribute, nx[s["depthToAttribute"]]))
                if s["depthFromAttribute"]:
                    g.add((node, cg.depthFromAttribute, nx[s["depthFromAttribute"]]))
            g.add((c, cg.entryDiameterAttribute, nx[sections[0]["diameterAttribute"]]))
            g.add((c, cg.baseDiameterAttribute, nx[sections[-1]["diameterAttribute"]]))

    # ---- NX attributes ---------------------------------------------------
    for name in tbox.attribute_names():
        record = tbox.attribute_record(name)
        a = nx[name]
        data_type = record.get("dataType")
        if data_type in ("Face", "Class"):
            g.add((a, RDF.type, OWL.ObjectProperty))
            g.add((a, RDFS.range, cg.Face if data_type == "Face" else OWL.Thing))
        else:
            g.add((a, RDF.type, OWL.DatatypeProperty))
            if data_type in XSD_BY_DATATYPE:
                g.add((a, RDFS.range, XSD[XSD_BY_DATATYPE[data_type]]))
        g.add((a, RDFS.label, Literal(name)))
        if data_type:
            g.add((a, cg.dataType, Literal(data_type)))
        if record.get("unit"):
            g.add((a, cg.unit, Literal(record["unit"])))
        if record.get("subType"):
            g.add((a, cg.subType, Literal(record["subType"])))
        g.add((a, cg.declaredIn, Literal(record["declaredIn"])))
        g.add((a, cg.apiReadable, Literal(bool(record.get("apiReadable")))))
        on = record.get("declaredOn")
        if on == "root":
            g.add((a, cg.declaredOnEveryFeature, Literal(True)))
        elif isinstance(on, list):
            for owner in on:
                g.add((a, cg.declaredOn, nx[owner]))

    # ---- relations -------------------------------------------------------
    for label, record in tbox.relation_types().items():
        r = cg[label]
        g.add((r, RDF.type, cg.RelationType))
        g.add((r, RDFS.label, Literal(label)))
        g.add((r, SKOS.definition, Literal(record["definition"])))
        g.add((r, cg.directed, Literal(bool(record["directed"]))))
        g.add((r, cg.method, Literal(record["method"])))
        for index, pair in enumerate(record.get("allowedPairs") or []):
            node = bnode("pair", label, index)
            g.add((r, cg.allowedPair, node))
            g.add((node, cg.first, nx[pair[0]]))
            g.add((node, cg.second, nx[pair[1]]))
        for prop in record.get("properties") or []:
            p = cg[prop["name"]]
            g.add((p, RDF.type, OWL.DatatypeProperty))
            g.add((p, RDFS.domain, cg.FeatureRelation))
            g.add((p, RDFS.range, XSD[prop["range"].split(":")[1]]))
            g.add((p, RDFS.label, Literal(prop["name"])))
            g.add((p, SKOS.definition, Literal(prop["definition"])))
            if prop.get("unit"):
                g.add((p, cg.unit, Literal(prop["unit"])))
            g.add((p, cg.onRelationType, r))
        terminal = record.get("terminal")
        if terminal:
            for field in terminal["fields"]:
                p = cg[field["name"]]
                kind = OWL.ObjectProperty if field["range"] in ("feature", "face") else OWL.DatatypeProperty
                g.add((p, RDF.type, kind))
                g.add((p, RDFS.domain, cg.LocatedOnTerminal))
                g.add((p, RDFS.label, Literal(field["name"])))
                g.add((p, SKOS.definition, Literal(field["definition"])))

    # ---- derived quantities ---------------------------------------------
    for name, record in tbox.derived_attributes().items():
        d = cg[name]
        g.add((d, RDF.type, OWL.DatatypeProperty))
        g.add((d, RDFS.label, Literal(record["label"])))
        g.add((d, SKOS.definition, Literal(record["definition"])))
        g.add((d, RDFS.range, XSD[record["range"].split(":")[1]]))
        g.add((d, cg.unit, Literal(record["unit"])))
        g.add((d, cg.method, Literal(record["method"])))
        g.add((d, cg.derivedQuantity, Literal(True)))
        for cls in tbox.expand_patterns(record["appliesTo"]):
            if not tbox.is_abstract(cls):
                g.add((d, cg.appliesTo, nx[cls]))

    # ---- thresholds ------------------------------------------------------
    for symbol, record in tbox.thresholds().items():
        t = cg[symbol]
        g.add((t, RDF.type, cg.Threshold))
        g.add((t, RDFS.label, Literal(symbol)))
        g.add((t, SKOS.definition, Literal(record["definition"])))
        if record.get("unit"):
            g.add((t, cg.unit, Literal(record["unit"])))
        if "members" in record:
            for member in record["members"]:
                g.add((t, cg.member, literal(member)))
        else:
            g.add((t, cg.value, literal(record["value"])))

    # ---- KPI -------------------------------------------------------------
    for kpi_id, record in tbox.kpi_types().items():
        k = cg[kpi_id]
        g.add((k, RDF.type, cg.KPIType))
        g.add((k, RDFS.label, Literal(record["label"])))
        g.add((k, SKOS.definition, Literal(record["definition"])))
        g.add((k, cg.unit, Literal(record["unit"])))
        g.add((k, cg.kind, Literal(record["kind"])))
        g.add((k, cg.worseWhen, Literal(record["worseWhen"])))
    for proxy in tbox.kpi().get("proxies") or []:
        g.add((cg[proxy["quantity"]], cg.proxyFor, cg[proxy["proxyFor"]]))
        g.add((cg[proxy["quantity"]], cg.proxyNote, Literal(proxy["definition"])))
    for derivation in tbox.kpi_derivations():
        d = cg[derivation["id"]]
        g.add((d, RDF.type, cg.KpiDerivation))
        g.add((d, RDFS.label, Literal(derivation["id"])))
        g.add((d, cg.kpiType, cg[derivation["kpiType"]]))
        g.add((d, cg.formula, Literal(derivation["formula"])))
        g.add((d, cg.condition, Literal(derivation["sparql"])))
        for cls in tbox.kpi_derivation_domain(derivation):
            g.add((d, cg.appliesTo, nx[cls]))
        for pattern in derivation.get("usesAttributes") or []:
            g.add((d, cg.usesAttributePattern, Literal(pattern)))

    # ---- heuristics ------------------------------------------------------
    derived_names = set(tbox.derived_attributes())
    for h_id, record in tbox.definitions().items():
        h = cg[h_id]
        g.add((h, RDF.type, cg.Heuristic))
        g.add((h, RDFS.label, Literal(record["label"])))
        g.add((h, cg.statement, Literal(record["statement"])))
        g.add((h, cg.scope, Literal(record["scope"])))
        if record.get("relationType"):
            g.add((h, cg.relationType, cg[record["relationType"]]))
        g.add((h, cg.condition, Literal(record["condition"])))
        for pattern in record.get("appliesTo") or []:
            g.add((h, cg.appliesToPattern, Literal(pattern)))
        for cls in tbox.heuristic_domain(h_id):
            g.add((h, cg.appliesTo, nx[cls]))
            required = tbox.required_attributes(h_id, cls)
            if required:
                node = bnode("requires", h_id, cls)
                g.add((h, cg.requires, node))
                g.add((node, cg.onClass, nx[cls]))
                for attribute in required:
                    g.add((node, cg.attribute, cg[attribute] if attribute in derived_names else nx[attribute]))
        for pattern in record.get("usesAttributes") or []:
            g.add((h, cg.usesAttributePattern, Literal(pattern)))
        for rel in record.get("usesRelations") or []:
            g.add((h, cg.usesRelation, cg[rel]))
        for symbol in record.get("usesThresholds") or []:
            g.add((h, cg.usesThreshold, cg[symbol]))
        for kpi_id in record.get("affectsKpi") or []:
            g.add((h, cg.affectsKpi, cg[kpi_id]))
        for value in record.get("values") or []:
            g.add((h, cg.publishesValue, Literal(value)))
    return g


def main() -> None:
    g = build()
    DIST.mkdir(parents=True, exist_ok=True)
    text = g.serialize(format="turtle")
    write_text(DIST / "cncgaide_nx.ttl", text)
    print(f"cncgaide_nx.ttl: {len(g)} triples")


if __name__ == "__main__":
    main()
