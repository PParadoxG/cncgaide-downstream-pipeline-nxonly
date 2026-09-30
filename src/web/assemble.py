"""What the page reads, assembled out of the store with SPARQL.

One function per endpoint.  Everything a number-bearing answer contains comes
from a query against the named graphs the index graph points at, so the page
can never show a part from one build and its verdicts from another: the index
says which facts graph and which derived graph are current, and every query
here starts there.

Two things do not come from the store, for the same reason: they are not
facts about a part.  Presentation defaults (colours, hidden classes, outcome
labels) are read from ``source/display.yaml`` through :mod:`tbox.nx`, which
is where the one rule says they live; the declared knowledge the page prints
beside the results - rule words, thresholds, units, which KPI a rule
affects, the direction a KPI moves, the query vocabulary - is read from the
same source, so it is there even while the store waits for a sync.

Nothing here decides anything.  A colour pattern is expanded to the classes
it covers, literals are given their Python types, IRIs are shortened to the
local names the page uses as keys - and that is the whole of it.
"""

from __future__ import annotations

import json
from pathlib import Path

from kg import iri, ontology, rules, sync
from kg.fuseki import Fuseki
from tbox import nx as tbox

PREFIXES = f"""
PREFIX cg: <{iri.CG}>
PREFIX nx: <{iri.NX}>
PREFIX rdf: <{iri.RDF}>
PREFIX rdfs: <{iri.RDFS}>
PREFIX xsd: <{iri.XSD}>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
"""

NUMERIC_TYPES = {
    f"{iri.XSD}decimal", f"{iri.XSD}double", f"{iri.XSD}float",
}
INTEGER_TYPES = {
    f"{iri.XSD}integer", f"{iri.XSD}int", f"{iri.XSD}long", f"{iri.XSD}nonNegativeInteger",
}


# ----------------------------------------------------------------- literals

def value_of(term: dict):
    """One SPARQL binding as the Python value the page should see."""
    if term is None:
        return None
    if term.get("type") == "uri":
        return term["value"]
    datatype = term.get("datatype")
    text = term.get("value")
    if datatype in INTEGER_TYPES:
        try:
            return int(text)
        except ValueError:
            return text
    if datatype in NUMERIC_TYPES:
        try:
            number = float(text)
        except ValueError:
            return text
        return int(number) if number.is_integer() and abs(number) < 1e15 else number
    if datatype == f"{iri.XSD}boolean":
        return text in ("true", "1")
    if datatype == f"{iri.RDF}JSON":
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def local(term) -> str | None:
    """The local name of an IRI: what the page uses as a key."""
    if not term:
        return None
    text = term if isinstance(term, str) else term.get("value")
    if not text:
        return None
    for prefix in (iri.CG, iri.NX):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text.rsplit("/", 1)[-1] if "/" in text else text.rsplit("#", 1)[-1]


def select(client: Fuseki, sparql: str) -> list[dict]:
    """Rows with typed values and no empty keys."""
    result = client.query(PREFIXES + sparql)
    rows = []
    for binding in result["results"]["bindings"]:
        rows.append({name: value_of(term) for name, term in binding.items()})
    return rows


# ------------------------------------------------------------------ display

def display_block() -> dict:
    """Every colour and default the page needs, as concrete names.

    The source writes patterns (``STEP*``); the page is not allowed to know
    what a pattern means, so they are expanded here, once, to the classes
    the vocabulary actually has.
    """
    classes = [name for name in tbox.recognisable_classes() if not tbox.is_abstract(name)]
    feature_colors = {}
    hidden = []
    labels = {}
    for name in classes:
        color = tbox.feature_color(name)
        if color:
            feature_colors[name] = color
        if tbox.is_hidden_by_default(name):
            hidden.append(name)
        label = tbox.label(name)
        if label:
            labels[name] = label
    relation_colors = {}
    for edge_type in sorted(tbox.relation_types()):
        color = tbox.relation_color(edge_type)
        if color:
            relation_colors[edge_type] = color
    configured = tbox.display()
    return {
        "featureColors": feature_colors,
        "featureLabels": labels,
        "relationColors": relation_colors,
        "relationsVisibleByDefault": list(configured.get("relationsVisibleByDefault") or []),
        "kpiColors": dict(configured.get("kpiColors") or {}),
        "hiddenTypes": sorted(hidden),
        "backgroundTypes": list(tbox.background_types()),
        "outcomeLabels": dict(configured.get("outcomeLabels") or {}),
    }


# -------------------------------------------------------------------- index

def index_rows(client: Fuseki) -> list[dict]:
    return select(client, f"""
        SELECT ?partId ?status ?sourceStep ?sourceSha256 ?factsKey ?derivedKey
               ?factsGraph ?derivedGraph ?updatedAt ?detail WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{
            ?part cg:partId ?partId .
            OPTIONAL {{ ?part cg:status ?status }}
            OPTIONAL {{ ?part cg:sourceStep ?sourceStep }}
            OPTIONAL {{ ?part cg:sourceSha256 ?sourceSha256 }}
            OPTIONAL {{ ?part cg:factsKey ?factsKey }}
            OPTIONAL {{ ?part cg:derivedKey ?derivedKey }}
            OPTIONAL {{ ?part cg:factsGraph ?factsGraph }}
            OPTIONAL {{ ?part cg:derivedGraph ?derivedGraph }}
            OPTIONAL {{ ?part cg:updatedAt ?updatedAt }}
            OPTIONAL {{ ?part cg:detail ?detail }}
          }}
        }} ORDER BY ?partId""")


def _class_counts(client: Fuseki) -> dict[str, dict[str, int]]:
    rows = select(client, f"""
        SELECT ?partId ?cls (COUNT(?f) AS ?n) WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:factsGraph ?g }}
          GRAPH ?g {{ ?f cg:partOf ?part ; cg:nodeId ?nodeId ; rdf:type ?cls }}
        }} GROUP BY ?partId ?cls""")
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        counts.setdefault(row["partId"], {})[local(row["cls"])] = int(row["n"])
    return counts


def _verdict_counts(client: Fuseki) -> dict[str, dict[str, int]]:
    rows = select(client, f"""
        SELECT ?partId ?outcome (COUNT(?v) AS ?n) WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:derivedGraph ?g }}
          GRAPH ?g {{ ?v a cg:Verdict ; cg:partOf ?part ; cg:outcome ?outcome }}
        }} GROUP BY ?partId ?outcome""")
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        counts.setdefault(row["partId"], {})[local(row["outcome"])] = int(row["n"])
    return counts


def _kpi_rows(client: Fuseki) -> dict[str, dict[str, dict]]:
    """Per part, per KPI type: how many results and the largest value."""
    rows = select(client, f"""
        SELECT ?partId ?kpiType ?unit (COUNT(?k) AS ?n) (MAX(?value) AS ?max) WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:derivedGraph ?g }}
          GRAPH ?g {{ ?k a cg:KPIResult ; cg:partOf ?part ; cg:kpiType ?kpiType ; cg:kpiValue ?value .
                      OPTIONAL {{ ?k cg:kpiUnit ?unit }} }}
        }} GROUP BY ?partId ?kpiType ?unit""")
    out: dict[str, dict[str, dict]] = {}
    for row in rows:
        out.setdefault(row["partId"], {})[local(row["kpiType"])] = {
            "count": int(row["n"]), "max": row.get("max"), "unit": row.get("unit"),
        }
    return out


def _part_numbers(client: Fuseki) -> dict[str, dict]:
    """Per part: faces, unclaimed faces and relations, read from its facts graph."""
    out: dict[str, dict] = {}
    for row in select(client, f"""
        SELECT ?partId ?faceCount WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:factsGraph ?g }}
          GRAPH ?g {{ ?part cg:faceCount ?faceCount }}
        }}"""):
        out.setdefault(row["partId"], {})["faceCount"] = row.get("faceCount")
    for row in select(client, f"""
        SELECT ?partId (COUNT(?u) AS ?n) WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:factsGraph ?g }}
          GRAPH ?g {{ ?part cg:unclaimedFace ?u }}
        }} GROUP BY ?partId"""):
        out.setdefault(row["partId"], {})["unclaimedFaceCount"] = int(row["n"])
    for row in select(client, f"""
        SELECT ?partId (COUNT(?r) AS ?n) WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:factsGraph ?g }}
          GRAPH ?g {{ ?r a cg:FeatureRelation ; cg:partOf ?part }}
        }} GROUP BY ?partId"""):
        out.setdefault(row["partId"], {})["relationCount"] = int(row["n"])
    return out


# The two segments a derived key adds to the facts key, in order, and the
# words the page prints for each when it no longer matches.
DERIVED_KEY_SEGMENTS = ("ontology", "rule engine")


def rules_changed(derived_key: str | None, expected: str | None) -> list[str]:
    """Which part of the derived key moved: the ontology, the rule engine, or both.

    ``derivedKey = factsKey-ontologyDigest[:8]-digest(kg/rules.py)[:8]``, so
    the last two dash-separated segments name the two things a rules-only
    rerun would pick up.  Empty when nothing moved or there is nothing to
    compare.
    """
    if not derived_key or not expected or derived_key == expected:
        return []
    held = derived_key.rsplit("-", 2)
    wanted = expected.rsplit("-", 2)
    if len(held) != 3 or len(wanted) != 3:
        return list(DERIVED_KEY_SEGMENTS)
    changed = [name for name, a, b in zip(DERIVED_KEY_SEGMENTS, held[1:], wanted[1:]) if a != b]
    return changed or list(DERIVED_KEY_SEGMENTS)


def index_digest(rows: list[dict]) -> str:
    """One short string that changes whenever the index graph does.

    The page compares it between polls: a new value means a sync replaced
    what the page is holding.
    """
    import hashlib

    text = "\n".join(f"{row.get('partId')}|{row.get('factsKey')}|{row.get('derivedKey')}|{row.get('status')}"
                     for row in sorted(rows, key=lambda row: row.get("partId") or ""))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def source_state(row: dict, input_dir: Path) -> dict:
    """The light: what the STEP file on disk says about this indexed part.

    ``new`` is the file that has never been built, ``changed`` the one whose
    bytes no longer match what the store was made from, ``source_missing``
    the part whose file has gone, ``fresh`` the one that agrees.
    """
    part_id = row["partId"]
    step = None
    for suffix in sync.STEP_SUFFIXES:
        candidate = input_dir / f"{part_id}{suffix}"
        if candidate.is_file():
            step = candidate
            break
    if step is None:
        return {"state": "source_missing", "sha256": None}
    sha = sync.sha256_file(step)
    if not row.get("factsKey"):
        return {"state": "new", "sha256": sha}
    if row.get("sourceSha256") != sha:
        return {"state": "changed", "sha256": sha}
    return {"state": "fresh", "sha256": sha}


def index(client: Fuseki, input_dir: Path) -> dict:
    """One row per part: the light, the counts and the keys."""
    rows = index_rows(client)
    classes = _class_counts(client)
    verdicts = _verdict_counts(client)
    kpi = _kpi_rows(client)
    numbers = _part_numbers(client)
    indexed = {row["partId"] for row in rows}
    parts = []
    for row in rows:
        part_id = row["partId"]
        per_class = classes.get(part_id, {})
        outcomes = verdicts.get(part_id, {})
        light = source_state(row, input_dir)
        expected_derived = (sync.derived_key(row["factsKey"]) if row.get("factsKey") else None)
        counted = numbers.get(part_id, {})
        parts.append({
            "partId": part_id,
            "status": row.get("status"),
            "detail": row.get("detail"),
            "sourceStep": row.get("sourceStep"),
            "updatedAt": row.get("updatedAt"),
            "factsKey": row.get("factsKey"),
            "derivedKey": row.get("derivedKey"),
            "light": light["state"],
            "sourceSha256": light["sha256"],
            "rulesChanged": rules_changed(row.get("derivedKey"), expected_derived),
            "faceCount": counted.get("faceCount"),
            "unclaimedFaceCount": counted.get("unclaimedFaceCount", 0) if row.get("factsKey") else None,
            "relationCount": counted.get("relationCount", 0) if row.get("factsKey") else None,
            "featureCount": sum(per_class.values()),
            "featureCounts": per_class,
            "verdicts": {
                "met": outcomes.get("PASS", 0),
                "notMet": outcomes.get("FAIL", 0),
                "notEvaluable": outcomes.get("NOT_EVALUABLE", 0),
            },
            "kpi": kpi.get(part_id, {}),
            "kpiResultCount": sum(entry["count"] for entry in kpi.get(part_id, {}).values()),
        })
    # A STEP file nobody has built yet is a part too - the page lists it so
    # that "add a part, then refresh" is one screen, not two.
    for step in _list_inputs(input_dir):
        part_id = step.stem
        if part_id in indexed:
            continue
        parts.append({
            "partId": part_id, "status": None, "detail": None,
            "sourceStep": step.as_posix(), "updatedAt": None,
            "factsKey": None, "derivedKey": None, "light": "new", "sourceSha256": None,
            "rulesChanged": [], "faceCount": None, "unclaimedFaceCount": None, "relationCount": None,
            "featureCount": 0, "featureCounts": {},
            "verdicts": {"met": 0, "notMet": 0, "notEvaluable": 0},
            "kpi": {}, "kpiResultCount": 0,
        })
    parts.sort(key=lambda entry: entry["partId"])
    return {
        "parts": parts,
        "display": display_block(),
        "ontologyDigest": tbox.ontology_digest(),
        "indexDigest": index_digest(rows),
        "inputPath": input_dir.name,
    }


def _list_inputs(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        return []
    return sync.list_inputs(input_dir)


# --------------------------------------------------------------- part bundle

class PartNotFound(LookupError):
    pass


class OntologyNotLoaded(RuntimeError):
    """The ontology built from the source is not the one the store holds.

    Several ontology graphs can sit in the store at once - each build leaves
    its own - so a query that simply matched "an ontology graph" would read
    whichever one it found first.  Everything here names the current graph,
    and says so plainly when that graph is not there instead of answering
    with an empty table.
    """


def ontology_graph(client: Fuseki) -> str:
    graph = ontology.ontology_graph()
    if not client.graph_exists(graph):
        raise OntologyNotLoaded(
            "the ontology built from ontology/nx_v1_1/source is not loaded in the store; "
            "run: python run.py sync")
    return graph


def _part_row(client: Fuseki, part_id: str) -> dict:
    for row in index_rows(client):
        if row["partId"] == part_id:
            return row
    raise PartNotFound(f"{part_id}: not in the index graph")


def _part_header(client: Fuseki, part_id: str, facts_graph: str) -> dict:
    rows = select(client, f"""
        SELECT ?p ?o WHERE {{
          GRAPH <{facts_graph}> {{ <{iri.part(part_id)}> ?p ?o }}
        }}""")
    header: dict = {"nx": {}}
    for row in rows:
        name = local(row["p"])
        value = row["o"]
        if name in ("faceCount", "featureCount", "claimedFaceCount", "lengthUnit",
                    "unmatchedNativeFaceCount", "recognitionProvider", "geometryProvider",
                    "registeredTypeCount", "projection"):
            header[name] = value
        elif name.startswith("nx_"):
            header["nx"][name[3:]] = value
    unclaimed = select(client, f"""
        SELECT ?faceId WHERE {{
          GRAPH <{facts_graph}> {{ <{iri.part(part_id)}> cg:unclaimedFace ?face . ?face cg:faceId ?faceId }}
        }} ORDER BY ?faceId""")
    header["unclaimedFaceIds"] = [row["faceId"] for row in unclaimed]
    recipe = select(client, f"""
        SELECT ?name ?value WHERE {{
          GRAPH <{facts_graph}> {{ <{iri.part(part_id)}> cg:recipe ?r . ?r cg:name ?name ; cg:value ?value }}
        }} ORDER BY ?name""")
    header["recipe"] = {row["name"]: row["value"] for row in recipe}
    return header


def _faces(client: Fuseki, part_id: str, facts_graph: str) -> list[dict]:
    rows = select(client, f"""
        SELECT ?faceId ?surfaceType ?area ?isOuter ?isReversed WHERE {{
          GRAPH <{facts_graph}> {{
            ?face a cg:Face ; cg:partOf <{iri.part(part_id)}> ; cg:faceId ?faceId .
            OPTIONAL {{ ?face cg:surfaceType ?surfaceType }}
            OPTIONAL {{ ?face cg:area ?area }}
            OPTIONAL {{ ?face cg:isOuter ?isOuter }}
            OPTIONAL {{ ?face cg:isReversed ?isReversed }}
          }}
        }}""")
    return sorted(rows, key=lambda row: _ordinal(row["faceId"]))


def _ordinal(face_id: str) -> int:
    tail = str(face_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _features(client: Fuseki, part_id: str, facts_graph: str) -> list[dict]:
    base = select(client, f"""
        SELECT ?f ?nodeId ?cls ?label WHERE {{
          GRAPH <{facts_graph}> {{
            ?f cg:partOf <{iri.part(part_id)}> ; cg:nodeId ?nodeId ; rdf:type ?cls .
            OPTIONAL {{ ?f rdfs:label ?label }}
          }}
        }}""")
    features: dict[str, dict] = {}
    used_by_class = tbox.used_attributes_by_class()
    for row in base:
        feature_type = local(row["cls"])
        features[row["f"]] = {
            "nodeId": row["nodeId"],
            "featureType": feature_type,
            "label": row.get("label") or tbox.label(feature_type) or feature_type,
            "attributes": {},
            "attributeGaps": {},
            "attributeReading": {},
            "usedAttributes": list(used_by_class.get(feature_type) or ()),
            "derived": {},
            "faceIds": [],
            "hiddenByDefault": tbox.is_hidden_by_default(feature_type),
        }

    for row in select(client, f"""
        SELECT ?f ?p ?v WHERE {{
          GRAPH <{facts_graph}> {{ ?f cg:partOf <{iri.part(part_id)}> ; cg:nodeId ?nodeId ; ?p ?v }}
          FILTER(STRSTARTS(STR(?p), "{iri.NX}"))
        }}"""):
        entry = features.get(row["f"])
        if entry is not None:
            entry["attributes"][local(row["p"])] = row["v"]

    for row in select(client, f"""
        SELECT ?f ?attribute ?reason WHERE {{
          GRAPH <{facts_graph}> {{
            ?f cg:partOf <{iri.part(part_id)}> ; cg:attributeGap ?gap .
            ?gap cg:attribute ?attribute ; cg:reason ?reason }}
        }}"""):
        entry = features.get(row["f"])
        if entry is not None:
            entry["attributeGaps"][local(row["attribute"])] = row["reason"]

    for row in select(client, f"""
        SELECT ?f ?attribute ?pile WHERE {{
          GRAPH <{facts_graph}> {{
            ?f cg:partOf <{iri.part(part_id)}> ; cg:attributeReading ?r .
            ?r cg:attribute ?attribute ; cg:pile ?pile }}
        }}"""):
        entry = features.get(row["f"])
        if entry is not None:
            entry["attributeReading"].setdefault(row["pile"], []).append(local(row["attribute"]))

    for row in select(client, f"""
        SELECT ?f ?faceId WHERE {{
          GRAPH <{facts_graph}> {{
            ?f cg:partOf <{iri.part(part_id)}> ; cg:ownsFace ?face . ?face cg:faceId ?faceId }}
        }}"""):
        entry = features.get(row["f"])
        if entry is not None:
            entry["faceIds"].append(row["faceId"])

    for row in select(client, f"""
        SELECT ?f ?quantity ?value ?method ?derivedBy WHERE {{
          GRAPH <{facts_graph}> {{
            ?f cg:partOf <{iri.part(part_id)}> ; cg:measurement ?m .
            ?m cg:quantity ?quantity ; cg:value ?value .
            OPTIONAL {{ ?m cg:method ?method }}
            OPTIONAL {{ ?m cg:derivedBy ?derivedBy }} }}
        }}"""):
        entry = features.get(row["f"])
        if entry is not None:
            entry["derived"][local(row["quantity"])] = {
                "value": row["value"], "method": row.get("method"),
                "derivedBy": row.get("derivedBy"), "evidenceFaces": [],
            }

    for row in select(client, f"""
        SELECT ?f ?quantity ?faceId WHERE {{
          GRAPH <{facts_graph}> {{
            ?f cg:partOf <{iri.part(part_id)}> ; cg:measurement ?m .
            ?m cg:quantity ?quantity ; cg:evidenceFace ?face . ?face cg:faceId ?faceId }}
        }}"""):
        entry = features.get(row["f"])
        if entry is None:
            continue
        measurement = entry["derived"].get(local(row["quantity"]))
        if measurement is not None:
            measurement["evidenceFaces"].append(row["faceId"])

    for row in select(client, f"""
        SELECT ?f ?quantity ?reason WHERE {{
          GRAPH <{facts_graph}> {{
            ?f cg:partOf <{iri.part(part_id)}> ; cg:measurementRefusal ?m .
            ?m cg:quantity ?quantity ; cg:reason ?reason }}
        }}"""):
        entry = features.get(row["f"])
        if entry is not None:
            entry["derived"][local(row["quantity"])] = {"value": None, "reason": row["reason"]}

    out = list(features.values())
    for entry in out:
        entry["faceIds"].sort(key=_ordinal)
        for measurement in entry["derived"].values():
            if "evidenceFaces" in measurement:
                measurement["evidenceFaces"].sort(key=_ordinal)
        for pile in entry["attributeReading"].values():
            pile.sort()
    out.sort(key=lambda entry: entry["nodeId"])
    return out


RELATION_STRUCTURE = {"partOf", "relationId", "relationType", "from", "to", "directed",
                      "sourceRule", "evidence", "diagnostic", "terminal"}


def _relations(client: Fuseki, part_id: str, facts_graph: str) -> list[dict]:
    base = select(client, f"""
        SELECT ?r ?relationId ?relationType ?source ?target ?directed ?sourceRule WHERE {{
          GRAPH <{facts_graph}> {{
            ?r a cg:FeatureRelation ; cg:partOf <{iri.part(part_id)}> ; cg:relationId ?relationId ;
               cg:relationType ?relationType ; cg:from ?a ; cg:to ?b .
            ?a cg:nodeId ?source . ?b cg:nodeId ?target .
            OPTIONAL {{ ?r cg:directed ?directed }}
            OPTIONAL {{ ?r cg:sourceRule ?sourceRule }}
          }}
        }}""")
    relations: dict[str, dict] = {}
    for row in base:
        relations[row["r"]] = {
            "relationId": row["relationId"],
            "edgeType": local(row["relationType"]),
            "source": row["source"],
            "target": row["target"],
            "directed": bool(row.get("directed")),
            "sourceRule": row.get("sourceRule"),
            "properties": {},
            "evidence": {},
            "diagnostics": {},
            "terminals": [],
        }

    for row in select(client, f"""
        SELECT ?r ?p ?v WHERE {{
          GRAPH <{facts_graph}> {{ ?r a cg:FeatureRelation ; cg:partOf <{iri.part(part_id)}> ; ?p ?v }}
          FILTER(STRSTARTS(STR(?p), "{iri.CG}"))
        }}"""):
        entry = relations.get(row["r"])
        name = local(row["p"])
        if entry is not None and name not in RELATION_STRUCTURE:
            entry["properties"][name] = row["v"]

    for predicate, field in (("evidence", "evidence"), ("diagnostic", "diagnostics")):
        for row in select(client, f"""
            SELECT ?r ?key ?value WHERE {{
              GRAPH <{facts_graph}> {{
                ?r a cg:FeatureRelation ; cg:partOf <{iri.part(part_id)}> ; cg:{predicate} ?e .
                ?e cg:key ?key ; cg:value ?value }}
            }}"""):
            entry = relations.get(row["r"])
            if entry is not None:
                entry[field][row["key"]] = row["value"]

    for row in select(client, f"""
        SELECT ?r ?terminalFeature ?hostOwner ?hostFaceId ?terminalRole ?hostSurfaceType WHERE {{
          GRAPH <{facts_graph}> {{
            ?r a cg:FeatureRelation ; cg:partOf <{iri.part(part_id)}> ; cg:terminal ?t .
            ?t cg:terminalFeature ?tf ; cg:hostOwner ?ho .
            ?tf cg:nodeId ?terminalFeature . ?ho cg:nodeId ?hostOwner .
            OPTIONAL {{ ?t cg:hostFace ?face . ?face cg:faceId ?hostFaceId }}
            OPTIONAL {{ ?t cg:terminalRole ?terminalRole }}
            OPTIONAL {{ ?t cg:hostSurfaceType ?hostSurfaceType }} }}
        }}"""):
        entry = relations.get(row["r"])
        if entry is not None:
            entry["terminals"].append({
                "terminalFeature": row["terminalFeature"], "hostOwner": row["hostOwner"],
                "hostFaceId": row.get("hostFaceId"), "terminalRole": row.get("terminalRole"),
                "hostSurfaceType": row.get("hostSurfaceType"),
            })

    out = list(relations.values())
    out.sort(key=lambda entry: entry["relationId"])
    return out


def _verdicts(client: Fuseki, part_id: str, facts_graph: str, derived_graph: str) -> list[dict]:
    if not derived_graph:
        return []
    base = select(client, f"""
        SELECT ?v ?hId ?scope ?outcome ?target ?targetId WHERE {{
          GRAPH <{derived_graph}> {{
            ?v a cg:Verdict ; cg:heuristic ?hId ; cg:scope ?scope ; cg:outcome ?outcome ; cg:target ?target .
          }}
          GRAPH <{facts_graph}> {{
            {{ ?target cg:nodeId ?targetId }} UNION {{ ?target cg:relationId ?targetId }}
          }}
        }}""")
    definitions = tbox.definitions()
    verdicts: dict[str, dict] = {}
    for row in base:
        entry = verdicts.setdefault(row["v"], {
            "hId": local(row["hId"]),
            "scope": row["scope"],
            "target": row["targetId"],
            "targetNodeIds": [],
            "outcome": local(row["outcome"]),
            "values": {},
            "thresholds": [],
            "gaps": [],
            "affectsKpi": list((definitions.get(local(row["hId"])) or {}).get("affectsKpi") or []),
        })

    for row in select(client, f"""
        SELECT ?v ?name ?value WHERE {{
          GRAPH <{derived_graph}> {{ ?v a cg:Verdict ; cg:value ?entry .
                                     ?entry cg:name ?name ; cg:value ?value }}
        }}"""):
        entry = verdicts.get(row["v"])
        if entry is not None:
            entry["values"][row["name"]] = row["value"]

    for row in select(client, f"""
        SELECT ?v ?threshold ?value WHERE {{
          GRAPH <{derived_graph}> {{ ?v a cg:Verdict ; cg:usedThreshold ?u .
                                     ?u cg:threshold ?threshold ; cg:value ?value }}
        }}"""):
        entry = verdicts.get(row["v"])
        if entry is not None:
            entry["thresholds"].append({"symbol": local(row["threshold"]), "value": row["value"]})

    for row in select(client, f"""
        SELECT ?v ?attribute ?reason WHERE {{
          GRAPH <{derived_graph}> {{ ?v a cg:Verdict ; cg:gap ?g .
                                     ?g cg:attribute ?attribute . OPTIONAL {{ ?g cg:reason ?reason }} }}
        }}"""):
        entry = verdicts.get(row["v"])
        if entry is not None:
            entry["gaps"].append({"attribute": local(row["attribute"]), "reason": row.get("reason")})

    for row in select(client, f"""
        SELECT ?v ?nodeId WHERE {{
          GRAPH <{derived_graph}> {{ ?v a cg:Verdict ; cg:target ?target }}
          GRAPH <{facts_graph}> {{
            {{ ?target cg:from ?end }} UNION {{ ?target cg:to ?end }}
            ?end cg:nodeId ?nodeId }}
        }}"""):
        entry = verdicts.get(row["v"])
        if entry is not None and row["nodeId"] not in entry["targetNodeIds"]:
            entry["targetNodeIds"].append(row["nodeId"])

    out = list(verdicts.values())
    for entry in out:
        entry["targetNodeIds"] = entry["targetNodeIds"] or [entry["target"]]
        entry["thresholds"].sort(key=lambda item: item["symbol"])
    out.sort(key=lambda entry: (entry["hId"], entry["target"]))
    return out


def rule_definitions(h_ids=None) -> dict:
    """What each rule is called, what it reads and which KPI it moves.

    Declared knowledge, read where it is declared (``source/heuristics.yaml``
    through :mod:`tbox.nx`) rather than out of whichever ontology graph the
    store still holds, so the words are there even while the store waits for
    a sync.  Thresholds carry the value the source sets now; a verdict carries
    the value it was computed with.
    """
    declared = tbox.thresholds()
    out = {}
    for h_id, rule in tbox.definitions().items():
        if h_ids is not None and h_id not in h_ids:
            continue
        out[h_id] = {
            "hId": h_id,
            "label": rule.get("label"),
            "statement": rule.get("statement"),
            "scope": rule.get("scope"),
            "appliesTo": list(rule.get("appliesTo") or []),
            "usesRelations": list(rule.get("usesRelations") or []),
            "thresholds": [{"symbol": symbol, "value": tbox.threshold_value(symbol),
                            "unit": (declared.get(symbol) or {}).get("unit")}
                           for symbol in rule.get("usesThresholds") or []],
            "affectsKpi": list(rule.get("affectsKpi") or []),
        }
    return out


def kpi_types() -> dict:
    """``{kpiType: {label, unit, kind, worseWhen, computed}}`` in source order.

    ``worseWhen`` is the direction a KPI moves when a rule that affects it is
    not met; ``computed`` says whether a derivation computes feature values
    for it here (the others are imported from a simulation run).
    """
    computed = {entry.get("kpiType") for entry in tbox.kpi_derivations()}
    return {kpi_id: {
        "label": entry.get("label"), "unit": entry.get("unit"), "kind": entry.get("kind"),
        "worseWhen": entry.get("worseWhen"), "computed": kpi_id in computed,
    } for kpi_id, entry in tbox.kpi_types().items()}


def derived_ontology_graph(client: Fuseki, derived_key: str | None) -> str | None:
    """The ontology graph a derived graph was computed under.

    The derived key carries the first eight characters of that ontology's
    digest; the store keeps every build's ontology graph, so the one that
    matches is still there after the source has moved on.
    """
    if not derived_key or derived_key.count("-") < 2:
        return None
    digest = derived_key.rsplit("-", 2)[1]
    prefix = iri.ontology_graph(digest)
    rows = select(client, f"""
        SELECT DISTINCT ?g WHERE {{
          GRAPH ?g {{ ?h a cg:Heuristic }}
          FILTER(STRSTARTS(STR(?g), "{prefix}"))
        }}""")
    graphs = sorted(row["g"] for row in rows)
    return graphs[0] if graphs else None


def not_applicable(client: Fuseki, row: dict, cache: dict | None = None) -> dict:
    """Per rule, the features of this part that are not applicable.

    ``kg.rules.not_applicable_counts``, asked against the ontology graph the
    part's verdicts were computed under.
    """
    facts_graph = row.get("factsGraph")
    derived_graph = row.get("derivedGraph")
    if not facts_graph or not derived_graph:
        return {}
    cache = {} if cache is None else cache
    key = row.get("derivedKey")
    digest = key.rsplit("-", 2)[1] if key and key.count("-") >= 2 else None
    if digest not in cache:
        cache[digest] = derived_ontology_graph(client, key)
    graph = cache[digest]
    if not graph:
        return {}
    try:
        counts = rules.not_applicable_counts(client, facts_graph=facts_graph,
                                             out_graph=derived_graph, ontology_graph=graph)
    except Exception:  # noqa: BLE001 - a count, never a reason to lose the answer
        return {}
    return {h_id: count for h_id, count in counts.items() if count}


def _kpi_results(client: Fuseki, part_id: str, facts_graph: str, derived_graph: str) -> list[dict]:
    if not derived_graph:
        return []
    rows = select(client, f"""
        SELECT ?kpiType ?nodeId ?value ?unit ?derivation WHERE {{
          GRAPH <{derived_graph}> {{
            ?k a cg:KPIResult ; cg:kpiType ?kpiType ; cg:kpiValue ?value .
            OPTIONAL {{ ?k cg:kpiUnit ?unit }}
            OPTIONAL {{ ?k cg:derivation ?derivation }}
            OPTIONAL {{ ?k cg:kpiOfFeature ?feature }} }}
          GRAPH <{facts_graph}> {{ ?feature cg:nodeId ?nodeId }}
        }}""")
    out = [{
        "kpiType": local(row["kpiType"]), "nodeId": row.get("nodeId"), "value": row["value"],
        "unit": row.get("unit"), "derivation": local(row.get("derivation")),
    } for row in rows]
    out.sort(key=lambda entry: (entry["kpiType"], entry["nodeId"] or ""))
    return out


def part(client: Fuseki, part_id: str) -> dict:
    """The part bundle: everything one part page draws, in one answer."""
    row = _part_row(client, part_id)
    facts_graph = row.get("factsGraph")
    derived_graph = row.get("derivedGraph")
    if not facts_graph:
        raise PartNotFound(f"{part_id}: the index has no facts graph for this part "
                           f"(status {row.get('status') or 'unknown'})")
    verdicts = _verdicts(client, part_id, facts_graph, derived_graph)
    counts_na = not_applicable(client, row)
    header = _part_header(client, part_id, facts_graph)
    return {
        "partId": part_id,
        "status": row.get("status"),
        "sourceStep": row.get("sourceStep"),
        "factsKey": row.get("factsKey"),
        "derivedKey": row.get("derivedKey"),
        "updatedAt": row.get("updatedAt"),
        "part": header,
        "faces": _faces(client, part_id, facts_graph),
        "features": _features(client, part_id, facts_graph),
        "relations": _relations(client, part_id, facts_graph),
        "verdicts": verdicts,
        "rules": rule_definitions({verdict["hId"] for verdict in verdicts} | set(counts_na)),
        "notApplicable": counts_na,
        "kpi": _kpi_results(client, part_id, facts_graph, derived_graph),
        "kpiTypes": kpi_types(),
        "display": display_block(),
        # Declared knowledge like the rule words: the unit of every name the
        # source gives one, NX's unit kinds resolved against this part's
        # length unit (tbox.nx.units).  The values above stay bare numbers.
        "units": tbox.units(header.get("lengthUnit")),
    }


# ------------------------------------------------------------ corpus views

OUTCOMES = ("PASS", "FAIL", "NOT_EVALUABLE", "NOT_APPLICABLE")


def _verdict_tally(client: Fuseki) -> dict[str, dict[str, dict[str, int]]]:
    """``{partId: {hId: {outcome: count}}}`` over every current derived graph."""
    rows = select(client, f"""
        SELECT ?partId ?h ?outcome (COUNT(?v) AS ?n) WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:derivedGraph ?g }}
          GRAPH ?g {{ ?v a cg:Verdict ; cg:partOf ?part ; cg:heuristic ?h ; cg:outcome ?outcome }}
        }} GROUP BY ?partId ?h ?outcome""")
    out: dict[str, dict[str, dict[str, int]]] = {}
    for row in rows:
        out.setdefault(row["partId"], {}).setdefault(local(row["h"]), {})[local(row["outcome"])] = int(row["n"])
    return out


def heuristics(client: Fuseki) -> dict:
    """Every rule against every part: the four outcome counts per cell.

    Verdicts come from the derived graphs the index points at; not applicable
    is counted the way ``kg.rules.not_applicable_counts`` counts it, against
    the ontology graph each part's verdicts were computed under.  The rule
    definitions and the KPI directions are read from the source.
    """
    rows = sorted((row for row in index_rows(client) if row.get("derivedGraph")),
                  key=lambda row: row["partId"].lower())
    tally = _verdict_tally(client)
    definitions = rule_definitions()
    cache: dict = {}
    parts = []
    corpus = {h_id: {"counts": dict.fromkeys(OUTCOMES, 0), "records": 0, "domainNodes": 0}
              for h_id in definitions}
    for row in rows:
        part_id = row["partId"]
        counted = tally.get(part_id, {})
        na = not_applicable(client, row, cache)
        summary = {}
        for h_id in sorted(set(counted) | set(na)):
            counts = dict.fromkeys(OUTCOMES, 0)
            counts.update(counted.get(h_id, {}))
            counts["NOT_APPLICABLE"] = na.get(h_id, 0)
            records = counts["PASS"] + counts["FAIL"] + counts["NOT_EVALUABLE"]
            summary[h_id] = {"counts": counts, "records": records}
            total = corpus.setdefault(h_id, {"counts": dict.fromkeys(OUTCOMES, 0),
                                             "records": 0, "domainNodes": 0})
            for outcome in OUTCOMES:
                total["counts"][outcome] += counts[outcome]
            total["records"] += records
            total["domainNodes"] += records + counts["NOT_APPLICABLE"]
        parts.append({"partId": part_id, "summary": summary})
    return {
        "rules": definitions,
        "corpus": corpus,
        "parts": parts,
        "kpiTypes": kpi_types(),
        "display": display_block(),
        "ontologyDigest": tbox.ontology_digest(),
    }


def kpi_table(client: Fuseki) -> dict:
    """One row per part, one column per KPI type.

    A cell carries the rules that are not met on the part and affect the KPI
    (with their not-met counts), and - for a KPI a derivation computes here -
    the part's value in the KPI's worse direction: the largest when higher is
    worse, the smallest when lower is.
    """
    types = kpi_types()
    definitions = rule_definitions()
    affected_by: dict[str, list[str]] = {kpi_id: [] for kpi_id in types}
    for h_id, rule in definitions.items():
        for kpi_id in rule["affectsKpi"]:
            affected_by.setdefault(kpi_id, []).append(h_id)
    failing = select(client, f"""
        SELECT ?partId ?h (COUNT(?v) AS ?n) WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:derivedGraph ?g }}
          GRAPH ?g {{ ?v a cg:Verdict ; cg:partOf ?part ; cg:heuristic ?h ; cg:outcome cg:FAIL }}
        }} GROUP BY ?partId ?h""")
    not_met: dict[str, dict[str, int]] = {}
    for row in failing:
        not_met.setdefault(row["partId"], {})[local(row["h"])] = int(row["n"])
    results = select(client, f"""
        SELECT ?partId ?kpiType ?nodeId ?value ?unit WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{ ?part cg:partId ?partId ; cg:derivedGraph ?g ; cg:factsGraph ?fg }}
          GRAPH ?g {{ ?k a cg:KPIResult ; cg:partOf ?part ; cg:kpiType ?kpiType ; cg:kpiValue ?value .
                      OPTIONAL {{ ?k cg:kpiUnit ?unit }}
                      OPTIONAL {{ ?k cg:kpiOfFeature ?feature }} }}
          OPTIONAL {{ GRAPH ?fg {{ ?feature cg:nodeId ?nodeId }} }}
        }}""")
    worst: dict[str, dict[str, dict]] = {}
    for row in results:
        kpi_id = local(row["kpiType"])
        value = row.get("value")
        if not isinstance(value, (int, float)):
            continue
        higher_is_worse = (types.get(kpi_id) or {}).get("worseWhen") != "lower"
        entry = worst.setdefault(row["partId"], {}).get(kpi_id)
        if entry is None:
            worst[row["partId"]][kpi_id] = {"value": value, "unit": row.get("unit"),
                                             "nodeId": row.get("nodeId"), "count": 1}
            continue
        entry["count"] += 1
        if (value > entry["value"]) if higher_is_worse else (value < entry["value"]):
            entry.update(value=value, nodeId=row.get("nodeId"), unit=row.get("unit") or entry["unit"])
    parts = []
    for row in sorted(index_rows(client), key=lambda row: row["partId"].lower()):
        if not row.get("derivedGraph"):
            continue
        part_id = row["partId"]
        failed = not_met.get(part_id, {})
        pressure = {}
        for kpi_id in types:
            rules_here = {h_id: failed[h_id] for h_id in affected_by.get(kpi_id, []) if h_id in failed}
            pressure[kpi_id] = {"rules": dict(sorted(rules_here.items()))}
        parts.append({"partId": part_id, "pressure": pressure, "worst": worst.get(part_id, {})})
    return {
        "kpiTypes": [{"kpiType": kpi_id, **entry, "affectedBy": sorted(affected_by.get(kpi_id, []))}
                     for kpi_id, entry in types.items()],
        "parts": parts,
        "display": display_block(),
    }


def vocabulary() -> dict:
    """The names a query can use: classes, attributes, relations, thresholds, KPI.

    Read from the source, like every other definition the page shows, and
    limited to names and values.
    """
    classes = []
    for name in tbox.class_names():
        record = tbox.class_record(name) or {}
        classes.append({"name": name, "parent": record.get("parent"), "label": record.get("label"),
                        "abstract": bool(record.get("abstract")),
                        "recognisable": bool(record.get("recognisable"))})
    thresholds = [{"symbol": symbol, "value": tbox.threshold_value(symbol), "unit": entry.get("unit")}
                  for symbol, entry in sorted(tbox.thresholds().items())]
    return {
        "prefixes": {"cg": iri.CG, "nx": iri.NX},
        "graphs": ["{INDEX}", "{ONTOLOGY}"],
        "classes": classes,
        "attributes": list(tbox.attribute_names()),
        "derivedQuantities": sorted(tbox.derived_attributes()),
        "relationTypes": sorted(tbox.relation_types()),
        "thresholds": thresholds,
        "heuristics": sorted(tbox.definitions()),
        "kpiTypes": [{"kpiType": kpi_id, "label": entry.get("label"), "worseWhen": entry.get("worseWhen")}
                     for kpi_id, entry in tbox.kpi_types().items()],
    }


# ------------------------------------------------- competency questions, query

def competency_questions(root: Path) -> dict:
    """The preset questions, as ``config/competency_questions.yaml`` writes them."""
    import yaml

    path = root / "config" / "competency_questions.yaml"
    if not path.is_file():
        return {"questions": []}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = []
    for entry in loaded.get("questions") or []:
        questions.append({
            "id": entry.get("id"),
            "question": entry.get("question"),
            "sparql": (entry.get("sparql") or "").strip(),
        })
    return {"questions": questions, "prefixes": PREFIXES.strip()}


UPDATE_KEYWORDS = ("INSERT", "DELETE", "LOAD", "CLEAR", "DROP", "CREATE",
                   "COPY", "MOVE", "ADD", "WITH")


def strip_comments(sparql: str) -> str:
    """The query without its comments, and without breaking an IRI.

    A ``#`` starts a comment only outside a string literal and outside
    ``<...>``: the hash in ``<https://cncgaide.org/...#H01>`` is part of the
    name, and cutting the line there would leave a query that no longer
    parses - and, worse, would hide from the guard below whatever followed.
    """
    out = []
    quote = None
    in_iri = False
    index = 0
    while index < len(sparql):
        char = sparql[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < len(sparql):
                out.append(sparql[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
        elif in_iri:
            out.append(char)
            if char == ">":
                in_iri = False
        elif char in "\"'":
            quote = char
            out.append(char)
        elif char == "<":
            in_iri = True
            out.append(char)
        elif char == "#":
            while index < len(sparql) and sparql[index] != "\n":
                index += 1
            continue
        else:
            out.append(char)
        index += 1
    return "".join(out)


def update_keyword(sparql: str) -> str | None:
    """The first update keyword the text uses as a word, if any.

    A word, not a substring: ``?deleted`` and ``cg:createdAt`` are data, and
    refusing them would make half the store unaskable.  Comments are removed
    first, because ``ADD`` and ``WITH`` are ordinary English and a reader
    writing a note above their query should not be told it is an update.
    Anything that still reads as an update keyword on its own is refused,
    and refused before the store is asked anything at all.
    """
    import re

    text = strip_comments(sparql)
    for keyword in UPDATE_KEYWORDS:
        if re.search(rf"(?<![?$:\w]){keyword}\b", text, re.IGNORECASE):
            return keyword
    return None


def substitute_graphs(sparql: str) -> str:
    """``{INDEX}`` and ``{ONTOLOGY}`` name the graphs now in force.

    The same convention the rules use, for the same reason: a question that
    hard-codes an ontology digest stops being askable the next time the
    ontology is built, and one that omits the graph reads whichever copy the
    store happens to still hold.
    """
    return (sparql.replace("{INDEX}", iri.INDEX_GRAPH)
                  .replace("{ONTOLOGY}", ontology.ontology_graph()))


def substitute_checked(client: Fuseki, sparql: str) -> str:
    """As :func:`substitute_graphs`, but only once the graph is really there."""
    if "{ONTOLOGY}" in sparql:
        ontology_graph(client)
    return substitute_graphs(sparql)


def query(client: Fuseki, sparql: str, *, timeout: float = 30.0) -> dict:
    """Read-only pass-through, with the page's prefixes in front."""
    import time

    sparql = substitute_checked(client, sparql)
    text = sparql if sparql.lstrip().upper().startswith("PREFIX") else PREFIXES + sparql
    asked = Fuseki(base=client.base, dataset=client.dataset, timeout=timeout)
    started = time.perf_counter()
    result = asked.query(text)
    result["elapsedMs"] = round((time.perf_counter() - started) * 1000.0, 1)
    return result


# ---------------------------------------------------------------------- plan

def plan(client: Fuseki, input_dir: Path, *, force_all: bool = False) -> dict:
    """What a sync would do, without doing any of it."""
    items = sync.plan(client, input_dir, force_all=force_all)
    return {"plan": [{
        "partId": item.part_id,
        "action": item.action,
        "factsKey": item.facts_key,
        "derivedKey": item.derived_key,
        "currentFactsKey": item.current_facts_key,
        "currentDerivedKey": item.current_derived_key,
        "notes": list(item.notes),
    } for item in items]}
