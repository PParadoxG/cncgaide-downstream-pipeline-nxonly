"""source/*.yaml -> dist/cncgaide_nx_structure.html (the ontology, readable).

One static file: the definitions travel in an embedded JSON block and the page
renders them in the browser.  No network, no build step, no stylesheet or font
from anywhere else; opening the file is enough.

It shows what the ontology declares and nothing else: the class tree with each
class's attributes and ladder sections, the attribute table, the relation
types, the derived quantities, the thresholds, the rules with their expanded
domains and their conditions, and the KPI vocabulary.  Nothing is generated
that is not in the source, and no time of generation is printed, so the file is
a function of the source alone.
"""
from __future__ import annotations

import json

from common import DIST, ONTOLOGY_IRI, tbox, write_text

PAGE_FILE = "cncgaide_nx_structure.html"


# --------------------------------------------------------------------- data

def attribute_table() -> tuple[list[list], dict[str, int]]:
    """Every attribute once, and the index a class refers to it by."""
    rows = []
    index = {}
    for name in tbox.attribute_names():
        record = tbox.attribute_record(name)
        index[name] = len(rows)
        rows.append([name, record.get("dataType"), record.get("unit"), record.get("subType"),
                     record["declaredIn"], 1 if record.get("apiReadable") else 0])
    return rows, index


def class_table(index: dict[str, int]) -> list[dict]:
    out = []
    for name in tbox.class_names():
        record = tbox.class_record(name)
        own = sorted(index[a] for a in record["attributes"] if a in index)
        inherited = sorted(index[a] for a in tbox.effective_attributes(name)
                           if a in index and index[a] not in set(own))
        entry = {
            "name": name,
            "parent": record["parent"],
            "abstract": 1 if record["abstract"] else 0,
            "recognisable": 1 if record.get("recognisable") else 0,
            "label": record.get("label") or None,
            "own": own,
            "inherited": inherited,
        }
        sections = tbox.sections(name)
        if sections:
            entry["sections"] = [[s["index"], s["diameterAttribute"], s["depthFromAttribute"],
                                  s["depthToAttribute"]] for s in sections]
        out.append(entry)
    return out


def relation_table() -> list[dict]:
    out = []
    for label, record in tbox.relation_types().items():
        entry = {
            "label": label,
            "definition": record["definition"],
            "directed": 1 if record["directed"] else 0,
            "method": record["method"],
            "allowedPairs": [list(pair) for pair in record.get("allowedPairs") or []],
            "properties": [{"name": p["name"], "range": p["range"], "unit": p.get("unit"),
                            "definition": p["definition"]} for p in record.get("properties") or []],
        }
        terminal = record.get("terminal")
        if terminal:
            entry["terminal"] = {
                "class": terminal["class"],
                "definition": terminal["definition"],
                "fields": [{"name": f["name"], "range": f["range"], "definition": f["definition"]}
                           for f in terminal["fields"]],
            }
        out.append(entry)
    return out


def derived_table() -> list[dict]:
    proxies = {p["quantity"]: p for p in tbox.kpi().get("proxies") or []}
    out = []
    for name, record in tbox.derived_attributes().items():
        proxy = proxies.get(name)
        out.append({
            "name": name,
            "label": record["label"],
            "definition": record["definition"],
            "range": record["range"],
            "unit": record["unit"],
            "method": record["method"],
            "appliesTo": list(record["appliesTo"]),
            "classes": [c for c in tbox.expand_patterns(record["appliesTo"]) if not tbox.is_abstract(c)],
            "proxyFor": proxy["proxyFor"] if proxy else None,
            "proxyNote": proxy["definition"] if proxy else None,
        })
    return out


def threshold_table() -> list[dict]:
    out = []
    for symbol, record in tbox.thresholds().items():
        out.append({
            "symbol": symbol,
            "value": None if "members" in record else record["value"],
            "members": record.get("members"),
            "unit": record.get("unit"),
            "definition": record["definition"],
        })
    return out


def heuristic_table() -> list[dict]:
    out = []
    for h_id, record in tbox.definitions().items():
        domain = list(tbox.heuristic_domain(h_id))
        out.append({
            "id": h_id,
            "label": record["label"],
            "statement": record["statement"],
            "scope": record["scope"],
            "relationType": record.get("relationType"),
            "appliesTo": list(record.get("appliesTo") or []),
            "classes": domain,
            "usesAttributes": list(record.get("usesAttributes") or []),
            "usesRelations": list(record.get("usesRelations") or []),
            "usesThresholds": list(record.get("usesThresholds") or []),
            "affectsKpi": list(record.get("affectsKpi") or []),
            "values": list(record.get("values") or []),
            "requires": {cls: list(tbox.required_attributes(h_id, cls)) for cls in domain
                         if tbox.required_attributes(h_id, cls)},
            "condition": record["condition"].rstrip("\n"),
        })
    return out


def kpi_tables() -> tuple[list[dict], list[dict]]:
    types = [{"id": kpi_id, "label": record["label"], "definition": record["definition"],
              "unit": record["unit"], "kind": record["kind"]}
             for kpi_id, record in tbox.kpi_types().items()]
    derivations = [{"id": d["id"], "kpiType": d["kpiType"], "appliesTo": list(d.get("appliesTo") or []),
                    "classes": list(tbox.kpi_derivation_domain(d)),
                    "usesAttributes": list(d.get("usesAttributes") or []),
                    "formula": d["formula"], "sparql": d["sparql"].rstrip("\n")}
                   for d in tbox.kpi_derivations()]
    return types, derivations


def payload() -> dict:
    attributes, index = attribute_table()
    kpi_types, kpi_derivations = kpi_tables()
    classes = class_table(index)
    return {
        "ontology": {
            "iri": ONTOLOGY_IRI,
            "version": tbox.ONTOLOGY_VERSION,
            "sourceDigest": tbox.source_digest(),
            "ontologyDigest": tbox.ontology_digest(),
            "rootParent": tbox.classes_head()["rootParent"],
            "namespaces": {"nx": tbox.NX, "cg": tbox.CG},
        },
        "attributes": attributes,
        "classes": classes,
        "relations": relation_table(),
        "derived": derived_table(),
        "thresholds": threshold_table(),
        "heuristics": heuristic_table(),
        "kpiTypes": kpi_types,
        "kpiDerivations": kpi_derivations,
    }


# --------------------------------------------------------------------- page

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CNCgAIde NX feature ontology</title>
<style>
:root {
  --ink: #1b1f24; --dim: #5d6873; --faint: #8b949e; --line: #d8dee4;
  --bg: #ffffff; --panel: #f6f8fa; --accent: #1f5c9e; --accent-soft: #e8f0f9;
  --mono: ui-monospace, "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.55 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}
header.top { border-bottom: 1px solid var(--line); padding: 26px 32px 18px; }
header.top h1 { margin: 0 0 10px; font-size: 22px; font-weight: 600; letter-spacing: -0.01em; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 26px; font-size: 12.5px; color: var(--dim); }
.meta b { font-weight: 600; color: var(--ink); }
.meta code { font-family: var(--mono); font-size: 12px; }
nav.bar {
  position: sticky; top: 0; z-index: 5; background: var(--bg);
  border-bottom: 1px solid var(--line); padding: 10px 32px;
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px;
}
nav.bar a { color: var(--dim); text-decoration: none; font-size: 13px; }
nav.bar a:hover { color: var(--accent); }
nav.bar .spacer { flex: 1 1 auto; }
#search {
  width: 280px; max-width: 46vw; padding: 6px 10px; font: inherit; font-size: 13px;
  border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--ink);
}
#search:focus { outline: 2px solid var(--accent-soft); border-color: var(--accent); }
#hits { font-size: 12.5px; color: var(--faint); min-width: 8ch; }
main { padding: 8px 32px 80px; max-width: 1180px; }
section { margin: 34px 0 0; scroll-margin-top: 62px; }
section > h2 {
  font-size: 17px; font-weight: 600; margin: 0 0 4px;
  padding-bottom: 6px; border-bottom: 1px solid var(--line);
}
section > p.note { margin: 6px 0 14px; color: var(--dim); font-size: 13px; }
.item { margin: 0 0 10px; }
.item.hidden, .row.hidden, section.hidden { display: none; }
details { border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
details > summary {
  cursor: pointer; padding: 7px 11px; list-style: none; display: flex;
  flex-wrap: wrap; align-items: baseline; gap: 4px 10px;
}
details > summary::-webkit-details-marker { display: none; }
details > summary::before { content: "\\25B8"; color: var(--faint); margin-right: 3px; font-size: 11px; }
details[open] > summary::before { content: "\\25BE"; }
details > summary:hover { background: var(--panel); }
details > .body { padding: 4px 13px 13px 26px; border-top: 1px solid var(--line); }
details details { border: 0; border-top: 1px solid var(--line); border-radius: 0; }
.tree, .tree ul { list-style: none; margin: 0; padding: 0; }
.tree ul { margin-left: 15px; border-left: 1px solid var(--line); padding-left: 10px; }
.tree > li { margin-top: 5px; }
.tree li li { margin-top: 5px; }
.name { font-family: var(--mono); font-size: 13px; font-weight: 600; }
.nice { color: var(--dim); font-size: 13px; }
.tag {
  font-size: 10.5px; letter-spacing: 0.04em; text-transform: uppercase;
  border: 1px solid var(--line); border-radius: 10px; padding: 1px 7px; color: var(--dim);
}
.tag.on { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.count { font-size: 12px; color: var(--faint); }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 8px 0 2px; }
th, td { text-align: left; padding: 4px 10px 4px 0; vertical-align: top; border-bottom: 1px solid var(--line); }
th { font-weight: 600; color: var(--dim); font-size: 12px; white-space: nowrap; }
td.mono, th.mono { font-family: var(--mono); font-size: 12.5px; }
td.num { text-align: right; padding-right: 18px; }
h4 { margin: 14px 0 2px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--dim); }
.chips { display: flex; flex-wrap: wrap; gap: 5px; margin: 4px 0 2px; }
.chip {
  font-family: var(--mono); font-size: 12px; background: var(--panel);
  border: 1px solid var(--line); border-radius: 4px; padding: 1px 6px;
}
pre {
  margin: 6px 0 2px; padding: 10px 12px; background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; overflow-x: auto; font-family: var(--mono); font-size: 12.5px; line-height: 1.45;
}
p.def { margin: 4px 0; color: var(--ink); }
.empty { color: var(--faint); font-size: 13px; padding: 10px 0; }
</style>
</head>
<body>
<header class="top">
  <h1>CNCgAIde NX feature ontology</h1>
  <div class="meta" id="meta"></div>
</header>
<nav class="bar">
  <a href="#classes">Classes</a>
  <a href="#attributes">Attributes</a>
  <a href="#relations">Relations</a>
  <a href="#derived">Derived quantities</a>
  <a href="#thresholds">Thresholds</a>
  <a href="#heuristics">Rules</a>
  <a href="#kpi">KPI</a>
  <span class="spacer"></span>
  <input id="search" type="search" placeholder="Search classes, attributes, rules" autocomplete="off">
  <span id="hits"></span>
</nav>
<main id="main"></main>
<script type="application/json" id="ontology-data">__DATA__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("ontology-data").textContent);
const ATTR = DATA.attributes;
const BY_NAME = new Map(DATA.classes.map(c => [c.name, c]));
const CHILDREN = new Map();
for (const c of DATA.classes) {
  if (c.parent) { if (!CHILDREN.has(c.parent)) CHILDREN.set(c.parent, []); CHILDREN.get(c.parent).push(c.name); }
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
function span(cls, text) { return el("span", cls, text); }
function chips(values) {
  const box = el("div", "chips");
  if (!values || !values.length) { box.appendChild(span("empty", "none")); return box; }
  for (const v of values) box.appendChild(span("chip", v));
  return box;
}
function table(headers, rows, classes) {
  const t = el("table");
  const head = el("tr");
  headers.forEach((h, i) => { const th = el("th", (classes && classes[i]) || "", h); head.appendChild(th); });
  t.appendChild(el("thead")).appendChild(head);
  const body = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    row.forEach((cell, i) => tr.appendChild(el("td", (classes && classes[i]) || "",
      cell === null || cell === undefined || cell === "" ? "\\u2013" : cell)));
    body.appendChild(tr);
  }
  t.appendChild(body);
  return t;
}
function heading(text) { return el("h4", null, text); }
function paragraph(text) { return el("p", "def", text); }
function block(text) { return el("pre", null, text); }
function attributeRows(indices) {
  return indices.map(i => {
    const a = ATTR[i];
    return [a[0], a[1], a[2], a[3], a[4], a[5] ? "yes" : "no"];
  });
}
const ATTRIBUTE_HEADERS = ["Attribute", "Data type", "Unit", "Sub type", "Declared in", "Readable"];
const ATTRIBUTE_CLASSES = ["mono", "", "", "", "", ""];

// ------------------------------------------------------------------ classes
function classFacts(c) {
  const box = el("div", "body");
  if (c.label) { box.appendChild(heading("Label")); box.appendChild(paragraph(c.label)); }
  box.appendChild(heading("Position"));
  box.appendChild(paragraph(
    (c.parent ? "Subclass of " + c.parent : "Subclass of " + DATA.ontology.rootParent + ", outside the schema")
    + (c.abstract ? ", abstract" : ", concrete")
    + (c.recognisable ? ", recognisable" : ", not recognisable")));
  if (c.sections) {
    box.appendChild(heading("Ladder sections"));
    box.appendChild(table(["Section", "Diameter", "Depth from", "Depth to"],
      c.sections.map(s => [s[0], s[1], s[2], s[3]]), ["num", "mono", "mono", "mono"]));
  }
  box.appendChild(heading("Declares " + c.own.length + " attribute(s)"));
  if (c.own.length) box.appendChild(table(ATTRIBUTE_HEADERS, attributeRows(c.own), ATTRIBUTE_CLASSES));
  else box.appendChild(span("empty", "none"));
  if (c.inherited.length) {
    const inner = el("details");
    inner.appendChild(el("summary", null, "Carries " + c.inherited.length + " further attribute(s)"));
    const body = el("div", "body");
    body.appendChild(paragraph("Declared on an ancestor, or attached by the feature API at run time."));
    body.appendChild(table(ATTRIBUTE_HEADERS, attributeRows(c.inherited), ATTRIBUTE_CLASSES));
    inner.appendChild(body);
    box.appendChild(inner);
  }
  return box;
}
function classSummary(c) {
  const s = el("summary");
  s.appendChild(span("name", c.name));
  if (c.label) s.appendChild(span("nice", c.label));
  if (c.abstract) s.appendChild(span("tag", "abstract"));
  if (c.recognisable) s.appendChild(span("tag on", "recognisable"));
  if (c.sections) s.appendChild(span("tag", c.sections.length + " sections"));
  s.appendChild(span("count", c.own.length + " declared, " + c.inherited.length + " further"));
  return s;
}
function classNode(name, depth) {
  const c = BY_NAME.get(name);
  const li = el("li", "item node");
  li.dataset.search = searchKeyOfClass(c);
  const d = el("details");
  if (depth < 1) d.open = true;
  d.appendChild(classSummary(c));
  d.appendChild(classFacts(c));
  li.appendChild(d);
  const kids = (CHILDREN.get(name) || []).slice().sort();
  if (kids.length) {
    const ul = el("ul");
    for (const kid of kids) ul.appendChild(classNode(kid, depth + 1));
    li.appendChild(ul);
  }
  return li;
}
function searchKeyOfClass(c) {
  const names = c.own.concat(c.inherited).map(i => ATTR[i][0]);
  return (c.name + " " + (c.label || "") + " " + names.join(" ")).toLowerCase();
}
function classCard(c) {
  const li = el("li", "item");
  li.dataset.search = searchKeyOfClass(c);
  const d = el("details");
  d.appendChild(classSummary(c));
  d.appendChild(classFacts(c));
  li.appendChild(d);
  return li;
}
function renderClasses(query) {
  const host = el("ul", "tree");
  if (query) {
    const matches = DATA.classes.filter(c => searchKeyOfClass(c).includes(query));
    for (const c of matches) host.appendChild(classCard(c));
    if (!matches.length) host.appendChild(el("li", "empty", "no class matches"));
  } else {
    for (const c of DATA.classes) if (!c.parent) host.appendChild(classNode(c.name, 0));
  }
  return host;
}

// --------------------------------------------------------------- attributes
function renderAttributes() {
  const t = table(ATTRIBUTE_HEADERS, attributeRows(ATTR.map((_, i) => i)), ATTRIBUTE_CLASSES);
  for (let i = 0; i < ATTR.length; i++) {
    const tr = t.tBodies[0].rows[i];
    tr.className = "row";
    tr.dataset.search = (ATTR[i][0] + " " + (ATTR[i][1] || "") + " " + (ATTR[i][2] || "") + " " + ATTR[i][4]).toLowerCase();
  }
  return t;
}

// ---------------------------------------------------------------- relations
function renderRelations() {
  const host = el("div");
  for (const r of DATA.relations) {
    const item = el("div", "item");
    item.dataset.search = (r.label + " " + r.definition + " " +
      r.properties.map(p => p.name).join(" ")).toLowerCase();
    const d = el("details");
    const s = el("summary");
    s.appendChild(span("name", r.label));
    s.appendChild(span("tag", r.directed ? "directed" : "undirected"));
    s.appendChild(span("count", r.allowedPairs.length + " allowed pair(s)"));
    d.appendChild(s);
    const body = el("div", "body");
    body.appendChild(paragraph(r.definition));
    body.appendChild(heading("Method"));
    body.appendChild(paragraph(r.method));
    body.appendChild(heading("Allowed pairs"));
    body.appendChild(table(["First", "Second"], r.allowedPairs, ["mono", "mono"]));
    body.appendChild(heading("Properties"));
    if (r.properties.length) {
      body.appendChild(table(["Property", "Range", "Unit", "Definition"],
        r.properties.map(p => [p.name, p.range, p.unit, p.definition]), ["mono", "mono", "", ""]));
    } else { body.appendChild(span("empty", "none")); }
    if (r.terminal) {
      body.appendChild(heading("Terminal " + r.terminal["class"]));
      body.appendChild(paragraph(r.terminal.definition));
      body.appendChild(table(["Field", "Range", "Definition"],
        r.terminal.fields.map(f => [f.name, f.range, f.definition]), ["mono", "mono", ""]));
    }
    d.appendChild(body);
    item.appendChild(d);
    host.appendChild(item);
  }
  return host;
}

// ------------------------------------------------------------------ derived
function renderDerived() {
  const host = el("div");
  for (const q of DATA.derived) {
    const item = el("div", "item");
    item.dataset.search = (q.name + " " + q.label + " " + q.definition).toLowerCase();
    const d = el("details");
    const s = el("summary");
    s.appendChild(span("name", q.name));
    s.appendChild(span("nice", q.label));
    s.appendChild(span("tag", q.unit));
    s.appendChild(span("count", q.classes.length + " class(es)"));
    d.appendChild(s);
    const body = el("div", "body");
    body.appendChild(paragraph(q.definition));
    body.appendChild(heading("Range and unit"));
    body.appendChild(paragraph(q.range + ", " + q.unit));
    body.appendChild(heading("Method"));
    body.appendChild(paragraph(q.method));
    if (q.proxyFor) {
      body.appendChild(heading("Proxy for " + q.proxyFor));
      body.appendChild(paragraph(q.proxyNote));
    }
    body.appendChild(heading("Applies to"));
    body.appendChild(chips(q.appliesTo));
    body.appendChild(heading("Expanded domain"));
    body.appendChild(chips(q.classes));
    d.appendChild(body);
    item.appendChild(d);
    host.appendChild(item);
  }
  return host;
}

// --------------------------------------------------------------- thresholds
function renderThresholds() {
  const rows = DATA.thresholds.map(t => [
    t.symbol, t.members ? t.members.join(", ") : t.value, t.unit, t.definition]);
  const t = table(["Symbol", "Value", "Unit", "Definition"], rows, ["mono", "mono", "", ""]);
  DATA.thresholds.forEach((th, i) => {
    const tr = t.tBodies[0].rows[i];
    tr.className = "row";
    tr.dataset.search = (th.symbol + " " + th.definition).toLowerCase();
  });
  return t;
}

// --------------------------------------------------------------- heuristics
function renderHeuristics() {
  const host = el("div");
  for (const h of DATA.heuristics) {
    const item = el("div", "item");
    item.dataset.search = (h.id + " " + h.label + " " + h.statement + " " +
      h.classes.join(" ") + " " + h.usesAttributes.join(" ") + " " +
      h.usesThresholds.join(" ")).toLowerCase();
    const d = el("details");
    const s = el("summary");
    s.appendChild(span("name", h.id));
    s.appendChild(span("nice", h.label));
    s.appendChild(span("tag", h.scope));
    if (h.relationType) s.appendChild(span("tag", h.relationType));
    s.appendChild(span("count", h.classes.length + " class(es) in the domain"));
    d.appendChild(s);
    const body = el("div", "body");
    body.appendChild(paragraph(h.statement));
    body.appendChild(heading("Applies to"));
    body.appendChild(chips(h.appliesTo));
    body.appendChild(heading("Domain"));
    body.appendChild(chips(h.classes));
    body.appendChild(heading("Uses attributes"));
    body.appendChild(chips(h.usesAttributes));
    if (h.usesRelations.length) {
      body.appendChild(heading("Uses relations"));
      body.appendChild(chips(h.usesRelations));
    }
    body.appendChild(heading("Uses thresholds"));
    body.appendChild(chips(h.usesThresholds));
    body.appendChild(heading("Affects KPI"));
    body.appendChild(chips(h.affectsKpi));
    body.appendChild(heading("Publishes values"));
    body.appendChild(chips(h.values));
    const required = Object.keys(h.requires);
    if (required.length) {
      const inner = el("details");
      inner.appendChild(el("summary", null, "Required attributes per class (" + required.length + ")"));
      const inbox = el("div", "body");
      inbox.appendChild(table(["Class", "Required attributes"],
        required.map(c => [c, h.requires[c].join(", ")]), ["mono", "mono"]));
      inner.appendChild(inbox);
      body.appendChild(inner);
    }
    body.appendChild(heading("Condition"));
    body.appendChild(block(h.condition));
    d.appendChild(body);
    item.appendChild(d);
    host.appendChild(item);
  }
  return host;
}

// ---------------------------------------------------------------------- KPI
function renderKpi() {
  const host = el("div");
  const types = el("div", "item");
  types.dataset.search = DATA.kpiTypes.map(k => k.id + " " + k.label + " " + k.definition).join(" ").toLowerCase();
  const td = el("details");
  td.open = true;
  const ts = el("summary");
  ts.appendChild(span("name", "KPI types"));
  ts.appendChild(span("count", DATA.kpiTypes.length + " type(s)"));
  td.appendChild(ts);
  const tbody = el("div", "body");
  tbody.appendChild(table(["Type", "Label", "Unit", "Kind", "Definition"],
    DATA.kpiTypes.map(k => [k.id, k.label, k.unit, k.kind, k.definition]), ["mono", "", "", "", ""]));
  td.appendChild(tbody);
  types.appendChild(td);
  host.appendChild(types);

  for (const d of DATA.kpiDerivations) {
    const item = el("div", "item");
    item.dataset.search = (d.id + " " + d.kpiType + " " + d.formula + " " + d.classes.join(" ")).toLowerCase();
    const det = el("details");
    const s = el("summary");
    s.appendChild(span("name", d.id));
    s.appendChild(span("nice", d.kpiType));
    s.appendChild(span("count", d.classes.length + " class(es) in the domain"));
    det.appendChild(s);
    const body = el("div", "body");
    body.appendChild(heading("Formula"));
    body.appendChild(paragraph(d.formula));
    body.appendChild(heading("Applies to"));
    body.appendChild(chips(d.appliesTo));
    body.appendChild(heading("Domain"));
    body.appendChild(chips(d.classes));
    body.appendChild(heading("Uses attributes"));
    body.appendChild(chips(d.usesAttributes));
    body.appendChild(heading("Condition"));
    body.appendChild(block(d.sparql));
    det.appendChild(body);
    item.appendChild(det);
    host.appendChild(item);
  }
  return host;
}

// -------------------------------------------------------------------- shell
function section(id, title, note, content) {
  const s = el("section");
  s.id = id;
  s.appendChild(el("h2", null, title));
  if (note) s.appendChild(el("p", "note", note));
  s.appendChild(content);
  return s;
}
function renderMeta() {
  const host = document.getElementById("meta");
  const o = DATA.ontology;
  const pairs = [["Ontology", o.iri], ["Version", o.version],
                 ["sourceDigest", o.sourceDigest], ["ontologyDigest", o.ontologyDigest],
                 ["nx:", o.namespaces.nx], ["cg:", o.namespaces.cg]];
  for (const [key, value] of pairs) {
    const d = el("div");
    d.appendChild(el("b", null, key + " "));
    d.appendChild(el("code", null, value));
    host.appendChild(d);
  }
}
let classHost = null;
function renderAll(query) {
  const main = document.getElementById("main");
  main.textContent = "";
  classHost = renderClasses(query);
  const counts = {
    classes: DATA.classes.length, recognisable: DATA.classes.filter(c => c.recognisable).length,
    attributes: ATTR.length,
  };
  main.appendChild(section("classes", "Classes",
    counts.classes + " classes, " + counts.recognisable + " of them recognisable; the root parent outside the schema is "
    + DATA.ontology.rootParent + ".", classHost));
  main.appendChild(section("attributes", "Attributes",
    counts.attributes + " attributes; a readable attribute is one the feature API hands over.", renderAttributes()));
  main.appendChild(section("relations", "Relations",
    DATA.relations.length + " relation types between features.", renderRelations()));
  main.appendChild(section("derived", "Derived quantities",
    DATA.derived.length + " quantities measured by the geometry kernel.", renderDerived()));
  main.appendChild(section("thresholds", "Thresholds",
    DATA.thresholds.length + " named limits the rules compare against.", renderThresholds()));
  main.appendChild(section("heuristics", "Rules",
    DATA.heuristics.length + " rules, each with its domain and its condition.", renderHeuristics()));
  main.appendChild(section("kpi", "KPI",
    DATA.kpiTypes.length + " KPI types and " + DATA.kpiDerivations.length + " feature-level derivations.",
    renderKpi()));
}
function applyFilter(query) {
  let hits = 0;
  for (const s of document.querySelectorAll("main > section")) {
    let shown = 0;
    for (const node of s.querySelectorAll("[data-search]")) {
      const match = !query || node.dataset.search.includes(query);
      node.classList.toggle("hidden", !match);
      if (match) shown++;
    }
    s.classList.toggle("hidden", Boolean(query) && shown === 0);
    hits += shown;
  }
  document.getElementById("hits").textContent = query ? hits + " match(es)" : "";
}
let current = null;
function onSearch(value) {
  const query = value.trim().toLowerCase();
  if (query === current) return;
  current = query;
  renderAll(query);
  applyFilter(query);
}
renderMeta();
onSearch("");
document.getElementById("search").addEventListener("input", event => onSearch(event.target.value));
</script>
</body>
</html>
"""


def render(data: dict) -> str:
    text = json.dumps(data, ensure_ascii=True, separators=(",", ":"), sort_keys=False)
    # The block sits in a script element, so no character of it may start a tag.
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return TEMPLATE.replace("__DATA__", text)


def main() -> None:
    data = payload()
    write_text(DIST / PAGE_FILE, render(data))
    print(f"{PAGE_FILE}: {len(data['classes'])} classes, {len(data['attributes'])} attributes, "
          f"{len(data['heuristics'])} rules")


if __name__ == "__main__":
    main()
