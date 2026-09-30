"""Run the rules against changed threshold values and answer what moved.

A copy of the ontology graph with the given values, a temporary derived
graph, a comparison against the verdicts the index points at, and then both
graphs go away again.  Nothing is indexed and nothing is kept: this is a
question, not a build.

    from kg import server, whatif
    whatif.whatif(server.client(), "<part id>", {"t_hole_ld": 3})
"""

from __future__ import annotations

import uuid

from kg import iri, ontology, rules
from kg.fuseki import Fuseki
from tbox import nx as tbox

NUMERIC = {f"{iri.XSD}{name}" for name in ("decimal", "double", "float", "integer", "int", "long")}


class PartNotFound(LookupError):
    """The part has no current facts and verdicts to compare against."""


class OntologyNotLoaded(RuntimeError):
    """The ontology graph built from the source is not in the store."""


def _value(term: dict | None):
    if term is None:
        return None
    text = term.get("value")
    if term.get("datatype") in NUMERIC:
        try:
            number = float(text)
        except (TypeError, ValueError):
            return text
        return int(number) if number.is_integer() and abs(number) < 1e15 else number
    return text


def _local(text: str | None) -> str | None:
    if not text:
        return None
    for prefix in (iri.CG, iri.NX):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text.rsplit("/", 1)[-1] if "/" in text else text.rsplit("#", 1)[-1]


def _select(client: Fuseki, sparql: str) -> list[dict]:
    result = client.query(f"PREFIX cg: <{iri.CG}>\n" + sparql)
    return [{name: _value(term) for name, term in binding.items()}
            for binding in result["results"]["bindings"]]


def _part_graphs(client: Fuseki, part_id: str) -> tuple[str | None, str | None]:
    literal = str(part_id).replace("\\", "\\\\").replace('"', '\\"')
    rows = _select(client, f"""
        SELECT ?factsGraph ?derivedGraph WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{
            ?part cg:partId "{literal}" .
            OPTIONAL {{ ?part cg:factsGraph ?factsGraph }}
            OPTIONAL {{ ?part cg:derivedGraph ?derivedGraph }}
          }}
        }}""")
    if not rows:
        raise PartNotFound(f"{part_id}: not in the index graph")
    return rows[0].get("factsGraph"), rows[0].get("derivedGraph")


def _verdict_map(client: Fuseki, facts_graph: str, derived_graph: str) -> dict:
    rows = _select(client, f"""
        SELECT ?h ?targetId ?outcome ?scope WHERE {{
          GRAPH <{derived_graph}> {{ ?v a cg:Verdict ; cg:heuristic ?h ; cg:target ?target ;
                                        cg:outcome ?outcome ; cg:scope ?scope }}
          GRAPH <{facts_graph}> {{ {{ ?target cg:nodeId ?targetId }} UNION {{ ?target cg:relationId ?targetId }} }}
        }}""")
    mapped = {}
    for row in rows:
        mapped[(_local(row["h"]), row["targetId"])] = {
            "outcome": _local(row["outcome"]), "scope": row["scope"],
        }
    for row in _select(client, f"""
        SELECT ?h ?targetId ?name ?value WHERE {{
          GRAPH <{derived_graph}> {{ ?v a cg:Verdict ; cg:heuristic ?h ; cg:target ?target ;
                                        cg:value ?entry . ?entry cg:name ?name ; cg:value ?value }}
          GRAPH <{facts_graph}> {{ {{ ?target cg:nodeId ?targetId }} UNION {{ ?target cg:relationId ?targetId }} }}
        }}"""):
        entry = mapped.get((_local(row["h"]), row["targetId"]))
        if entry is not None:
            entry.setdefault("values", {})[row["name"]] = row["value"]
    return mapped


def _outcome_tally(verdicts: dict) -> dict:
    tally = {"PASS": 0, "FAIL": 0, "NOT_EVALUABLE": 0}
    for entry in verdicts.values():
        tally[entry["outcome"]] = tally.get(entry["outcome"], 0) + 1
    return tally


def whatif(client: Fuseki, part_id: str, thresholds: dict) -> dict:
    """Run the rules of one part against changed threshold values.

    Answers the thresholds (``was`` / ``now``), every verdict whose outcome
    changed (``before`` / ``after`` / ``values``) and the outcome tallies on
    both sides.  The temporary graphs are dropped whatever happens.
    """
    known = tbox.thresholds()
    changes = {}
    for symbol, value in (thresholds or {}).items():
        if symbol not in known:
            raise ValueError(f"unknown threshold {symbol!r}")
        if "members" in known[symbol]:
            raise ValueError(f"{symbol} is a set of members, not a single value")
        try:
            changes[symbol] = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{symbol}: expected a number, got {value!r}") from None
    if not changes:
        raise ValueError("no threshold given")

    facts_graph, derived_graph = _part_graphs(client, part_id)
    if not facts_graph or not derived_graph:
        raise PartNotFound(f"{part_id}: no current facts and verdicts to compare against")

    source_graph = ontology.ontology_graph()
    if not client.graph_exists(source_graph):
        raise OntologyNotLoaded(
            "the ontology built from ontology/nx_v1_1/source is not loaded in the store; "
            "run: python run.py sync")
    token = uuid.uuid4().hex[:16]
    ontology_copy = iri.whatif_graph(token)
    derived_copy = iri.whatif_graph(f"{token}-derived")
    try:
        client.update(f"COPY <{source_graph}> TO <{ontology_copy}>")
        for symbol, value in sorted(changes.items()):
            client.update(f"""
                PREFIX cg: <{iri.CG}>
                DELETE {{ GRAPH <{ontology_copy}> {{ cg:{symbol} cg:value ?old }} }}
                INSERT {{ GRAPH <{ontology_copy}> {{ cg:{symbol} cg:value {value} }} }}
                WHERE  {{ GRAPH <{ontology_copy}> {{ cg:{symbol} cg:value ?old }} }}""")
        rules.run(client, facts_graph=facts_graph, out_graph=derived_copy,
                  ontology_graph=ontology_copy)
        before = _verdict_map(client, facts_graph, derived_graph)
        after = _verdict_map(client, facts_graph, derived_copy)
    finally:
        client.drop_graph(derived_copy)
        client.drop_graph(ontology_copy)

    changed = []
    for key in sorted(set(before) | set(after)):
        h_id, target = key
        was = before.get(key)
        now = after.get(key)
        if (was or {}).get("outcome") == (now or {}).get("outcome"):
            continue
        changed.append({
            "hId": h_id, "target": target,
            "scope": (now or was or {}).get("scope"),
            "before": (was or {}).get("outcome"),
            "after": (now or {}).get("outcome"),
            "values": (now or {}).get("values") or (was or {}).get("values") or {},
        })
    return {
        "partId": part_id,
        "thresholds": {symbol: {"was": known[symbol].get("value"), "now": value}
                       for symbol, value in sorted(changes.items())},
        "changed": changed,
        "counts": {
            "before": _outcome_tally(before),
            "after": _outcome_tally(after),
        },
        "temporary": True,
    }
