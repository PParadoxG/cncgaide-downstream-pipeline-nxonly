"""Bring the store up to date with ``inputs/``.

For every STEP file the planner computes two content keys:

* the **facts key** - the STEP's sha256, the installed NX schema's sha256 and
  a digest of the code that produces facts.  A different key means the NX
  session has to run again for this part.
* the **derived key** - the facts key plus the built ontology's digest (source
  and build scripts) and the rule runner's digest.  A different key means only the rules have to run
  again, which takes seconds and needs no NX.

What is current is read from the index graph; nothing is decided from files.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from kg import iri, ontology, rules
from kg.fuseki import Fuseki
from tbox import nx as tbox

STEP_SUFFIXES = (".step", ".stp", ".STEP", ".STP")


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(paths) -> str:
    digest = hashlib.sha256()
    for base in paths:
        base = Path(base)
        files = sorted(p for p in base.rglob("*.py")) if base.is_dir() else [base]
        for path in files:
            if "__pycache__" in path.parts or "vendor" in path.parts:
                continue
            digest.update(path.relative_to(project_root()).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def pipeline_digest() -> str:
    src = project_root() / "src"
    return _tree_digest([src / "nxline", src / "relations", src / "contract", src / "topology",
                         src / "core", src / "kg" / "facts.py", src / "kg" / "iri.py"])


def rules_digest() -> str:
    return _tree_digest([project_root() / "src" / "kg" / "rules.py"])


def schema_sha256() -> str:
    """The installed customization_base.xml, or the one the ontology was built from."""
    try:
        import nx_location
        path = nx_location.nx_root() / "UGII" / "customization_base.xml"
        if path.is_file():
            return sha256_file(path)
    except Exception:  # noqa: BLE001
        pass
    return tbox.classes_head()["source"][0]["sha256"]


def facts_key(step_sha: str) -> str:
    return f"{step_sha[:12]}-{schema_sha256()[:8]}-{pipeline_digest()[:8]}"


def derived_key(facts: str) -> str:
    return f"{facts}-{tbox.ontology_digest()[:8]}-{rules_digest()[:8]}"


def part_id_of(path: Path) -> str:
    return path.stem


def list_inputs(input_dir: Path) -> list[Path]:
    return sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix in STEP_SUFFIXES)


@dataclass
class PlanItem:
    part_id: str
    step_path: Path | None
    source_sha: str | None
    facts_key: str | None
    derived_key: str | None
    current_facts_key: str | None
    current_derived_key: str | None
    current_facts_graph: str | None
    current_derived_graph: str | None
    action: str  # build | rules | current | remove
    notes: list[str] = field(default_factory=list)

    @property
    def facts_graph(self) -> str:
        return iri.facts_graph(self.part_id, self.facts_key)

    @property
    def derived_graph(self) -> str:
        return iri.derived_graph(self.part_id, self.derived_key)


def index_rows(client: Fuseki) -> dict[str, dict]:
    rows = client.rows(f"""
        PREFIX cg: <{iri.CG}>
        SELECT ?part ?partId ?factsKey ?derivedKey ?factsGraph ?derivedGraph ?sourceStep ?status WHERE {{
          GRAPH <{iri.INDEX_GRAPH}> {{
            ?part cg:partId ?partId .
            OPTIONAL {{ ?part cg:factsKey ?factsKey }}
            OPTIONAL {{ ?part cg:derivedKey ?derivedKey }}
            OPTIONAL {{ ?part cg:factsGraph ?factsGraph }}
            OPTIONAL {{ ?part cg:derivedGraph ?derivedGraph }}
            OPTIONAL {{ ?part cg:sourceStep ?sourceStep }}
            OPTIONAL {{ ?part cg:status ?status }}
          }}
        }}""")
    return {row["partId"]: row for row in rows}


def plan(client: Fuseki, input_dir: Path, *, force_all: bool = False, keep_missing: bool = False) -> list[PlanItem]:
    index = index_rows(client)
    items: list[PlanItem] = []
    seen = set()
    for step in list_inputs(input_dir):
        part_id = part_id_of(step)
        seen.add(part_id)
        sha = sha256_file(step)
        fk = facts_key(sha)
        dk = derived_key(fk)
        current = index.get(part_id, {})
        if force_all or current.get("factsKey") != fk:
            action = "build"
        elif current.get("derivedKey") != dk:
            action = "rules"
        else:
            action = "current"
        items.append(PlanItem(part_id, step, sha, fk, dk, current.get("factsKey"), current.get("derivedKey"),
                              current.get("factsGraph"), current.get("derivedGraph"), action))
    for part_id, current in sorted(index.items()):
        if part_id in seen:
            continue
        items.append(PlanItem(part_id, None, None, None, None, current.get("factsKey"), current.get("derivedKey"),
                              current.get("factsGraph"), current.get("derivedGraph"),
                              "keep" if keep_missing else "remove", ["source STEP is gone"]))
    return items


def _index_update(client: Fuseki, item: PlanItem, *, status: str, detail: str = "") -> None:
    p = f"<{iri.part(item.part_id)}>"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    triples = [f'{p} a <{iri.CG}Part>', f'{p} <{iri.CG}partId> "{item.part_id}"',
               f'{p} <{iri.CG}status> "{status}"', f'{p} <{iri.CG}updatedAt> "{now}"^^<{iri.XSD}dateTime>']
    if item.step_path is not None:
        rel = item.step_path.as_posix()
        try:
            rel = item.step_path.resolve().relative_to(project_root().resolve()).as_posix()
        except ValueError:
            pass
        triples.append(f'{p} <{iri.CG}sourceStep> "{rel}"')
        triples.append(f'{p} <{iri.CG}sourceSha256> "{item.source_sha}"')
    if item.facts_key and status in ("facts", "current", "rulesFailed"):
        triples.append(f'{p} <{iri.CG}factsKey> "{item.facts_key}"')
        triples.append(f'{p} <{iri.CG}factsGraph> <{item.facts_graph}>')
    if item.derived_key and status == "current":
        triples.append(f'{p} <{iri.CG}derivedKey> "{item.derived_key}"')
        triples.append(f'{p} <{iri.CG}derivedGraph> <{item.derived_graph}>')
    if detail:
        escaped = detail.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        triples.append(f'{p} <{iri.CG}detail> "{escaped}"')
    client.update(f"""
        DELETE WHERE {{ GRAPH <{iri.INDEX_GRAPH}> {{ {p} ?p ?o }} }} ;
        INSERT DATA {{ GRAPH <{iri.INDEX_GRAPH}> {{ {' . '.join(triples)} . }} }}""")


def remove_part(client: Fuseki, item: PlanItem, *, drop_graphs: bool = True) -> None:
    if drop_graphs:
        for graph in (item.current_facts_graph, item.current_derived_graph):
            if graph:
                client.drop_graph(graph)
    client.update(f"DELETE WHERE {{ GRAPH <{iri.INDEX_GRAPH}> {{ <{iri.part(item.part_id)}> ?p ?o }} }}")
    mesh_dir = project_root() / "runs" / "mesh" / item.part_id
    if mesh_dir.is_dir():
        shutil.rmtree(mesh_dir, ignore_errors=True)


def execute(client: Fuseki, items: list[PlanItem], *, root: Path | None = None, run_rules: bool = True,
            log=print) -> dict:
    root = root or project_root()
    ontology.ensure_loaded(client)
    report = {"built": [], "rules": [], "removed": [], "blocked": None, "errors": {}}

    to_build = [item for item in items if item.action == "build"]
    if to_build:
        from nxline.driver import run_nx_line
        jobs = []
        for item in to_build:
            facts_path = root / "runs" / "facts" / item.part_id / f"{item.facts_key}.trig"
            jobs.append({"partId": item.part_id, "stepPath": str(item.step_path),
                         "sourceStep": item.step_path.as_posix(), "sourceSha256": item.source_sha,
                         "factsPath": str(facts_path), "factsGraph": item.facts_graph, "factsKey": item.facts_key,
                         "meshDir": str(root / "runs" / "mesh" / item.part_id)})
        log(f"nx: building {len(jobs)} part(s) in one session")
        outcome = run_nx_line(root, jobs)
        if outcome["status"] == "blocked":
            report["blocked"] = outcome["detail"]
            log(f"nx: blocked - {outcome['detail'][:200]}")
            for item in to_build:
                _index_update(client, item, status="blocked", detail=outcome["detail"][:500])
            to_build = []
        for item in to_build:
            summary = outcome["parts"].get(item.part_id) or {"status": "error", "error": outcome.get("detail", "")}
            if summary.get("status") != "success":
                report["errors"][item.part_id] = summary.get("error", "")
                _index_update(client, item, status="error", detail=str(summary.get("error", ""))[:800])
                log(f"nx: {item.part_id} error - {str(summary.get('error', ''))[:160]}")
                continue
            facts_path = root / "runs" / "facts" / item.part_id / f"{item.facts_key}.trig"
            for graph in (item.current_facts_graph, item.current_derived_graph):
                if graph and graph != item.facts_graph:
                    client.drop_graph(graph)
            client.drop_graph(item.facts_graph)
            client.post_dataset(facts_path.read_bytes(), "application/trig")
            item.current_facts_graph = item.facts_graph
            _index_update(client, item, status="facts")
            report["built"].append(item.part_id)
            item.action = "rules"
            log(f"nx: {item.part_id} facts loaded ({summary['entry']['tripleCount']} triples)")

    if run_rules:
        for item in items:
            if item.action != "rules":
                continue
            if item.current_derived_graph and item.current_derived_graph != item.derived_graph:
                client.drop_graph(item.current_derived_graph)
            result = rules.run(client, facts_graph=item.facts_graph, out_graph=item.derived_graph)
            _index_update(client, item, status="current")
            report["rules"].append({"partId": item.part_id, **result["counts"]})
            log(f"rules: {item.part_id} {result['counts']}")

    for item in items:
        if item.action == "remove":
            remove_part(client, item)
            report["removed"].append(item.part_id)
            log(f"removed {item.part_id}")
    return report
