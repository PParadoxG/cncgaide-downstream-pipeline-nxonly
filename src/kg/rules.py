"""Execute the generated SPARQL Update rules for one part."""

from __future__ import annotations

import time

from kg import iri, ontology
from kg.fuseki import Fuseki

PLACEHOLDERS = ("{ONTOLOGY}", "{FACTS}", "{OUT}")


def substitute(text: str, *, ontology_graph: str, facts_graph: str, out_graph: str) -> str:
    return (text.replace("{ONTOLOGY}", ontology_graph)
                .replace("{FACTS}", facts_graph)
                .replace("{OUT}", out_graph))


def run(client: Fuseki, *, facts_graph: str, out_graph: str, ontology_graph: str | None = None,
        names: list[str] | None = None) -> dict:
    """Drop ``out_graph``, run every rule in ORDER.txt, answer the outcome counts."""
    ontology_graph = ontology_graph or ontology.ontology_graph()
    client.drop_graph(out_graph)
    timings = {}
    for name in names or ontology.rule_order():
        started = time.perf_counter()
        client.update(substitute(ontology.rule_text(name), ontology_graph=ontology_graph,
                                 facts_graph=facts_graph, out_graph=out_graph))
        timings[name] = round(time.perf_counter() - started, 3)
    return {"outGraph": out_graph, "counts": outcome_counts(client, out_graph), "timings": timings}


def outcome_counts(client: Fuseki, out_graph: str) -> dict:
    rows = client.rows(f"""
        PREFIX cg: <{iri.CG}>
        SELECT ?outcome (COUNT(?v) AS ?n) WHERE {{
          GRAPH <{out_graph}> {{ ?v a cg:Verdict ; cg:outcome ?outcome }}
        }} GROUP BY ?outcome""")
    counts = {row["outcome"].rsplit("#", 1)[-1]: int(row["n"]) for row in rows}
    kpi = client.rows(f"""
        PREFIX cg: <{iri.CG}>
        SELECT (COUNT(?k) AS ?n) WHERE {{ GRAPH <{out_graph}> {{ ?k a cg:KPIResult }} }}""")
    counts["kpiResults"] = int(kpi[0]["n"]) if kpi else 0
    return counts


def not_applicable_counts(client: Fuseki, *, facts_graph: str, out_graph: str,
                          ontology_graph: str | None = None) -> dict:
    """Per rule: features in the domain that received no verdict at all."""
    ontology_graph = ontology_graph or ontology.ontology_graph()
    rows = client.rows(f"""
        PREFIX cg: <{iri.CG}>
        SELECT ?h (COUNT(?f) AS ?n) WHERE {{
          GRAPH <{ontology_graph}> {{ ?h a cg:Heuristic ; cg:scope "feature" ; cg:appliesTo ?cls }}
          GRAPH <{facts_graph}> {{ ?f a ?cls }}
          FILTER NOT EXISTS {{ GRAPH <{out_graph}> {{ ?v cg:heuristic ?h ; cg:target ?f }} }}
        }} GROUP BY ?h ORDER BY ?h""")
    return {row["h"].rsplit("#", 1)[-1]: int(row["n"]) for row in rows}
