"""source/heuristics.yaml + source/kpi.yaml -> dist/rules/*.ru

One SPARQL Update per heuristic and per KPI derivation, plus two gate rules
that materialise NOT_EVALUABLE verdicts for features and relations in a
rule's domain that lack a required attribute value.

Every file uses three graph placeholders the runner substitutes:

    {ONTOLOGY}   the graph holding dist/cncgaide_nx.ttl (or a what-if copy)
    {FACTS}      the graph holding one part's facts
    {OUT}        the graph receiving verdicts and KPI results
"""
from __future__ import annotations

from common import RULES, sparql_prefixes, tbox, write_text

REQUIRED_GUARD = """  FILTER NOT EXISTS {{
    GRAPH <{{ONTOLOGY}}> {{ cg:{h} cg:requires ?rq . ?rq cg:onClass {cls} ; cg:attribute ?ra }}
    FILTER NOT EXISTS {{ GRAPH <{{FACTS}}> {{ {subject} ?ra ?rv }} }}
  }}
"""


def indent(text: str, spaces: int = 2) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.rstrip("\n").splitlines()) + "\n"


def threshold_bindings(symbols) -> str:
    lines = []
    for symbol in symbols or ():
        record = tbox.thresholds()[symbol]
        if "members" not in record:
            lines.append(f"cg:{symbol} cg:value ?{symbol} .")
    return " ".join(lines)


def value_triples(values) -> str:
    return "".join(f'      cg:value [ a cg:Value ; cg:name "{name}" ; cg:value ?v_{name} ] ;\n' for name in values or ())


def threshold_triples(symbols) -> str:
    out = ""
    for symbol in symbols or ():
        record = tbox.thresholds()[symbol]
        if "members" in record:
            out += f"      cg:usedThreshold [ cg:threshold cg:{symbol} ] ;\n"
        else:
            out += f"      cg:usedThreshold [ cg:threshold cg:{symbol} ; cg:value ?{symbol} ] ;\n"
    return out


def feature_rule(h_id: str, record: dict) -> str:
    return f"""{sparql_prefixes()}
INSERT {{
  GRAPH <{{OUT}}> {{
    ?verdict a cg:Verdict ;
      cg:heuristic cg:{h_id} ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
{threshold_triples(record.get("usesThresholds"))}{value_triples(record.get("values"))}      cg:scope "feature" .
  }}
}}
WHERE {{
  GRAPH <{{ONTOLOGY}}> {{ cg:{h_id} cg:appliesTo ?cls . {threshold_bindings(record.get("usesThresholds"))} }}
  GRAPH <{{FACTS}}> {{ ?f a ?cls ; cg:partOf ?part . }}
{REQUIRED_GUARD.format(h=h_id, cls="?cls", subject="?f")}{indent(record["condition"])}  BIND(IRI(CONCAT(STR(?f), "/verdict/{h_id}")) AS ?verdict)
}}
"""


def pair_rule(h_id: str, record: dict) -> str:
    rel = record["relationType"]
    return f"""{sparql_prefixes()}
INSERT {{
  GRAPH <{{OUT}}> {{
    ?verdict a cg:Verdict ;
      cg:heuristic cg:{h_id} ;
      cg:target ?rel ;
      cg:targetA ?a ;
      cg:targetB ?b ;
      cg:partOf ?part ;
      cg:outcome ?outcome ;
{threshold_triples(record.get("usesThresholds"))}{value_triples(record.get("values"))}      cg:scope "pair" .
  }}
}}
WHERE {{
  GRAPH <{{ONTOLOGY}}> {{ cg:{h_id} cg:appliesTo ?clsA , ?clsB . {threshold_bindings(record.get("usesThresholds"))} }}
  GRAPH <{{FACTS}}> {{
    ?rel a cg:FeatureRelation ; cg:relationType cg:{rel} ; cg:from ?a ; cg:to ?b ; cg:partOf ?part .
    ?a a ?clsA . ?b a ?clsB .
  }}
{REQUIRED_GUARD.format(h=h_id, cls="?clsA", subject="?a")}{REQUIRED_GUARD.format(h=h_id, cls="?clsB", subject="?b")}{indent(record["condition"])}  BIND(IRI(CONCAT(STR(?rel), "/verdict/{h_id}")) AS ?verdict)
}}
"""


GATE_FEATURE = """{prefixes}
INSERT {{
  GRAPH <{{OUT}}> {{
    ?verdict a cg:Verdict ;
      cg:heuristic ?h ;
      cg:target ?f ;
      cg:partOf ?part ;
      cg:outcome cg:NOT_EVALUABLE ;
      cg:gap [ cg:attribute ?attr ; cg:reason ?reason ] ;
      cg:scope "feature" .
  }}
}}
WHERE {{
  GRAPH <{{ONTOLOGY}}> {{
    ?h a cg:Heuristic ; cg:scope "feature" ; cg:appliesTo ?cls ; cg:requires ?rq .
    ?rq cg:onClass ?cls ; cg:attribute ?attr .
  }}
  GRAPH <{{FACTS}}> {{ ?f a ?cls ; cg:partOf ?part }}
  FILTER NOT EXISTS {{ GRAPH <{{FACTS}}> {{ ?f ?attr ?any }} }}
  OPTIONAL {{ GRAPH <{{FACTS}}> {{ ?f cg:attributeGap ?g . ?g cg:attribute ?attr ; cg:reason ?r1 }} }}
  OPTIONAL {{ GRAPH <{{FACTS}}> {{ ?f cg:measurementRefusal ?m . ?m cg:quantity ?attr ; cg:reason ?r2 }} }}
  BIND(COALESCE(?r1, ?r2, "the feature carries no value for this attribute") AS ?reason)
  BIND(IRI(CONCAT(STR(?f), "/verdict/", STRAFTER(STR(?h), "#"))) AS ?verdict)
}}
"""

GATE_PAIR = """{prefixes}
INSERT {{
  GRAPH <{{OUT}}> {{
    ?verdict a cg:Verdict ;
      cg:heuristic ?h ;
      cg:target ?rel ;
      cg:targetA ?a ;
      cg:targetB ?b ;
      cg:partOf ?part ;
      cg:outcome cg:NOT_EVALUABLE ;
      cg:gap [ cg:onFeature ?x ; cg:attribute ?attr ; cg:reason ?reason ] ;
      cg:scope "pair" .
  }}
}}
WHERE {{
  GRAPH <{{ONTOLOGY}}> {{
    ?h a cg:Heuristic ; cg:scope "pair" ; cg:relationType ?rt ; cg:appliesTo ?clsA , ?clsB .
  }}
  GRAPH <{{FACTS}}> {{
    ?rel a cg:FeatureRelation ; cg:relationType ?rt ; cg:from ?a ; cg:to ?b ; cg:partOf ?part .
    ?a a ?clsA . ?b a ?clsB .
  }}
  {{ GRAPH <{{FACTS}}> {{ ?rel cg:from ?x . ?x a ?xcls }} }} UNION {{ GRAPH <{{FACTS}}> {{ ?rel cg:to ?x . ?x a ?xcls }} }}
  GRAPH <{{ONTOLOGY}}> {{ ?h cg:requires ?rq . ?rq cg:onClass ?xcls ; cg:attribute ?attr }}
  FILTER NOT EXISTS {{ GRAPH <{{FACTS}}> {{ ?x ?attr ?any }} }}
  OPTIONAL {{ GRAPH <{{FACTS}}> {{ ?x cg:attributeGap ?g . ?g cg:attribute ?attr ; cg:reason ?r1 }} }}
  OPTIONAL {{ GRAPH <{{FACTS}}> {{ ?x cg:measurementRefusal ?m . ?m cg:quantity ?attr ; cg:reason ?r2 }} }}
  BIND(COALESCE(?r1, ?r2, "the feature carries no value for this attribute") AS ?reason)
  BIND(IRI(CONCAT(STR(?rel), "/verdict/", STRAFTER(STR(?h), "#"))) AS ?verdict)
}}
"""


def kpi_rule(derivation: dict) -> str:
    kpi_type = derivation["kpiType"]
    unit = tbox.kpi_types()[kpi_type]["unit"]
    return f"""{sparql_prefixes()}
INSERT {{
  GRAPH <{{OUT}}> {{
    ?result a cg:KPIResult ;
      cg:kpiType cg:{kpi_type} ;
      cg:kpiOfFeature ?f ;
      cg:partOf ?part ;
      cg:kpiValue ?value ;
      cg:kpiUnit "{unit}" ;
      cg:derivation cg:{derivation["id"]} .
  }}
}}
WHERE {{
  GRAPH <{{ONTOLOGY}}> {{ cg:{derivation["id"]} cg:appliesTo ?cls . }}
  GRAPH <{{FACTS}}> {{ ?f a ?cls ; cg:partOf ?part . }}
{indent(derivation["sparql"])}  FILTER(BOUND(?value))
  BIND(IRI(CONCAT(STR(?f), "/kpi/{kpi_type}")) AS ?result)
}}
"""


def main() -> None:
    RULES.mkdir(parents=True, exist_ok=True)
    for stale in RULES.glob("*.ru"):
        stale.unlink()
    written = []
    for h_id, record in tbox.definitions().items():
        text = pair_rule(h_id, record) if record["scope"] == "pair" else feature_rule(h_id, record)
        write_text(RULES / f"{h_id}.ru", text)
        written.append(h_id)
    write_text(RULES / "gate_feature.ru", GATE_FEATURE.format(prefixes=sparql_prefixes()))
    write_text(RULES / "gate_pair.ru", GATE_PAIR.format(prefixes=sparql_prefixes()))
    for derivation in tbox.kpi_derivations():
        write_text(RULES / f"{derivation['id']}.ru", kpi_rule(derivation))
        written.append(derivation["id"])
    order = ["gate_feature", "gate_pair"] + written
    write_text(RULES / "ORDER.txt", "\n".join(order) + "\n")
    print(f"rules: {len(order)} files")


if __name__ == "__main__":
    main()
