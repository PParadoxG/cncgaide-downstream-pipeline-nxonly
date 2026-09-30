#!/usr/bin/env python
"""Did this installation compute the right answer, or merely run?

Those are different questions and only the second one is easy.  A store that
starts, a build that passes and a session that ends without an exception prove
that the machinery turns.  They prove nothing about the answer: a different NX
release recognises a different set of features, a half-loaded ontology drops
rules silently, and both leave every log line looking normal.

So this compares a finished run against a recorded observation of the same
sample part: how many triples each of its graphs holds, how many faces and
features, the features by class, the relations by type, the verdicts by rule
and outcome, and the KPI results by type.  The class histogram is the part
that earns its keep, because that is where a wrong NX or a wrong ontology
shows up first.

    python install/verify_install.py              build, sync, then check
    python install/verify_install.py --no-sync    check the store as it stands
    python install/verify_install.py --record     record the expectation

--record is for whoever prepares a release, not for whoever deploys one.  When
a check fails, recording over it is exactly the wrong move: the mismatch is the
finding.  Re-record only when the sample part or the recognition itself has
deliberately changed.

Nothing here is compared that a harmless change would move: content keys,
graph names and digests are read, never expected.  Only counts are.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTATION = Path(__file__).resolve().parent / "expected_install.json"
SAMPLE_PART = "STEPtest2"

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "nxline" / "vendor"))

from kg import iri, ontology, server, sync  # noqa: E402


# ------------------------------------------------------------------ the steps

def check_store() -> tuple[bool, list[str]]:
    state = server.status(ROOT)
    lines = []
    ok = True
    if not state["fusekiHome"]:
        lines.append("the store is not unpacked under install/fuseki; run install/fuseki_install.py")
        ok = False
    if not state["java"]:
        lines.append("no java was found; install a JDK 21 or later and set JAVA_HOME")
        ok = False
    elif state["javaMajor"] is not None and state["javaMajor"] < 21:
        lines.append(f"java {state['javaMajor']} was found; the store needs Java 21 or later")
        ok = False
    if ok:
        lines.append(f"java {state['javaMajor']} at {state['java']}")
        lines.append(f"endpoint {state['endpoint']}")
    return ok, lines


def check_build(run_build: bool) -> tuple[bool, list[str]]:
    if run_build:
        result = subprocess.run([sys.executable, str(ROOT / "run.py"), "build"],
                                capture_output=True, text=True)
        if result.returncode != 0:
            tail = (result.stdout or "") + (result.stderr or "")
            return False, ["the build failed:"] + tail.strip().splitlines()[-12:]
    try:
        ontology.require_built()
    except RuntimeError as error:
        return False, [str(error)]
    return True, [f"ontology digest {ontology.tbox.ontology_digest()}",
                  f"{len(ontology.rule_order())} rules in ORDER.txt"]


def check_sample(part_id: str) -> tuple[bool, list[str]]:
    candidate = step_file(part_id)
    if candidate is None:
        return False, [f"inputs/ holds no STEP file for {part_id}"]
    return True, [f"inputs/{candidate.name}, {candidate.stat().st_size} bytes"]


def run_sync() -> tuple[bool, list[str]]:
    result = subprocess.run([sys.executable, str(ROOT / "run.py"), "sync", "--input", "inputs"],
                            capture_output=True, text=True)
    tail = ((result.stdout or "") + (result.stderr or "")).strip().splitlines()
    if result.returncode != 0:
        return False, ["the sync did not finish:"] + tail[-15:]
    return True, tail[-6:]


# ------------------------------------------------------------- the observation

def step_file(part_id: str) -> Path | None:
    for suffix in sync.STEP_SUFFIXES:
        candidate = ROOT / "inputs" / f"{part_id}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def staleness(part_id: str, row: dict) -> list[str]:
    """Whether what the index calls current is still current.

    The index says what was computed, not what the code would compute now, so
    counts read straight out of the store can be one generation behind.  The
    two content keys say which.
    """
    path = step_file(part_id)
    if path is None:
        return []
    facts = sync.facts_key(sync.sha256_file(path))
    if row.get("factsKey") != facts:
        return ["the stored facts predate the current fact-producing code; a sync would run NX again"]
    if row.get("derivedKey") != sync.derived_key(facts):
        return ["the stored verdicts predate the current ontology; a sync would run the rules again"]
    return []


def graphs_of(client, part_id: str) -> tuple[dict, list[str]]:
    row = sync.index_rows(client).get(part_id)
    if row is None:
        return {}, [f"{part_id} is not in the index; run the sync"]
    notes = []
    if row.get("status") != "current":
        notes.append(f"the index calls {part_id} {row.get('status', 'unknown')}, not current")
    for key in ("factsGraph", "derivedGraph"):
        if not row.get(key):
            return {}, notes + [f"{part_id} has no {key}; run the sync"]
    return row, notes + staleness(part_id, row)


def observe(client, row: dict) -> dict:
    facts, derived = row["factsGraph"], row["derivedGraph"]
    prefix = f"PREFIX cg: <{iri.CG}>\n"

    def one(sparql: str) -> int:
        rows = client.rows(prefix + sparql)
        return int(rows[0]["n"]) if rows else 0

    def histogram(sparql: str) -> dict:
        return {row_["k"].rsplit("#", 1)[-1]: int(row_["n"]) for row_ in client.rows(prefix + sparql)}

    verdicts: dict[str, dict[str, int]] = {}
    for row_ in client.rows(prefix + f"""
        SELECT ?k ?o (COUNT(?v) AS ?n) WHERE {{
          GRAPH <{derived}> {{ ?v a cg:Verdict ; cg:heuristic ?k ; cg:outcome ?o }}
        }} GROUP BY ?k ?o"""):
        verdicts.setdefault(row_["k"].rsplit("#", 1)[-1], {})[row_["o"].rsplit("#", 1)[-1]] = int(row_["n"])

    return {
        "factsTriples": client.graph_size(facts),
        "derivedTriples": client.graph_size(derived),
        "faces": one(f"SELECT (COUNT(?f) AS ?n) WHERE {{ GRAPH <{facts}> {{ ?f a cg:Face }} }}"),
        "features": one(f"SELECT (COUNT(?f) AS ?n) WHERE {{ GRAPH <{facts}> {{ ?f cg:nodeId ?i }} }}"),
        "featureTypes": histogram(
            f"SELECT ?k (COUNT(?f) AS ?n) WHERE {{ GRAPH <{facts}> {{ ?f cg:nodeId ?i ; a ?k }} }} GROUP BY ?k"),
        "relations": histogram(
            f"SELECT ?k (COUNT(?r) AS ?n) WHERE {{ GRAPH <{facts}> "
            f"{{ ?r a cg:FeatureRelation ; cg:relationType ?k }} }} GROUP BY ?k"),
        "verdicts": {key: dict(sorted(value.items())) for key, value in sorted(verdicts.items())},
        "kpiResults": histogram(
            f"SELECT ?k (COUNT(?r) AS ?n) WHERE {{ GRAPH <{derived}> "
            f"{{ ?r a cg:KPIResult ; cg:kpiType ?k }} }} GROUP BY ?k"),
    }


def differences(expected, actual, path: str = "") -> list[str]:
    """Every difference, named, one line each."""
    if isinstance(expected, dict) or isinstance(actual, dict):
        expected = expected if isinstance(expected, dict) else {}
        actual = actual if isinstance(actual, dict) else {}
        out = []
        for key in sorted(set(expected) | set(actual)):
            out += differences(expected.get(key, 0), actual.get(key, 0),
                               f"{path} {key}".strip())
        return out
    if expected != actual:
        return [f"{path}: expected {expected}, got {actual}"]
    return []


# -------------------------------------------------------------------- the runs

def load_expectation() -> dict | None:
    try:
        return json.loads(EXPECTATION.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError as error:
        raise SystemExit(f"{EXPECTATION.name} is not valid JSON: {error}")


def do_record(client, part_id: str) -> int:
    row, notes = graphs_of(client, part_id)
    for note in notes:
        print(f"  note {note}")
    if not row:
        return 2
    seen = observe(client, row)
    payload = {
        "_comment": "Recorded by verify_install.py --record. Regenerate rather than edit: "
                    "these numbers are an observation, not a setting.",
        "part": part_id,
        "counts": seen,
    }
    with open(EXPECTATION, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"recorded {part_id} -> {EXPECTATION.name}")
    for key in ("factsTriples", "derivedTriples", "faces", "features"):
        print(f"  {key}: {seen[key]}")
    print(f"  featureTypes: {len(seen['featureTypes'])} class(es), "
          f"relations: {len(seen['relations'])} type(s), "
          f"verdicts: {len(seen['verdicts'])} rule(s), kpiResults: {len(seen['kpiResults'])} type(s)")
    return 0


def do_check(client, part_id: str, expectation: dict) -> int:
    row, notes = graphs_of(client, part_id)
    for note in notes:
        print(f"  note {note}")
    if not row:
        return 3
    seen = observe(client, row)
    expected = expectation.get("counts") or {}
    failures = []
    for key in ("factsTriples", "derivedTriples", "faces", "features",
                "featureTypes", "relations", "verdicts", "kpiResults"):
        problems = differences(expected.get(key, 0), seen.get(key, 0), key)
        if problems:
            failures += problems
            print(f"  DIFFERS {key}")
        else:
            value = seen[key]
            summary = value if isinstance(value, int) else f"{len(value)} entr(ies), {sum_of(value)} total"
            print(f"  ok      {key}: {summary}")
    print()
    if failures:
        print(f"MISMATCH - {len(failures)} difference(s) against {EXPECTATION.name}:")
        for failure in failures:
            print("  - " + failure)
        print()
        print("Do not adjust anything to make this pass.  The mismatch is the finding:")
        print("send this whole output to whoever gave you the repository.")
        return 1
    print(f"INSTALL VERIFIED - {part_id} answers exactly as recorded.")
    return 0


def sum_of(value) -> int:
    total = 0
    for item in value.values():
        total += item if isinstance(item, int) else sum(item.values())
    return total


def step(title: str, outcome: tuple[bool, list[str]]) -> bool:
    ok, lines = outcome
    print(f"{'ok  ' if ok else 'FAIL'}  {title}")
    for line in lines:
        print(f"        {line}")
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--part", default=None, metavar="ID",
                        help=f"the part to check (default: the recorded one, or {SAMPLE_PART})")
    parser.add_argument("--record", action="store_true",
                        help="record the expectation from the store (release preparation)")
    parser.add_argument("--no-build", action="store_true", help="do not rebuild the ontology first")
    parser.add_argument("--no-sync", action="store_true",
                        help="do not run the sync; check the store as it stands (no NX session)")
    args = parser.parse_args(argv)

    expectation = load_expectation()
    part_id = args.part or (expectation or {}).get("part") or SAMPLE_PART

    print("CNCgAIde NX - installation check")
    print()
    if not step("the store", check_store()):
        return 2
    if not step("the ontology", check_build(not args.no_build)):
        return 2
    if not step("the sample part", check_sample(part_id)):
        return 2
    if args.no_sync:
        print("skip  the sync (--no-sync): the store is checked as it stands")
    elif not step("the sync", run_sync()):
        return 2
    print()

    client = server.ensure_running(ROOT)
    if args.record:
        return do_record(client, part_id)
    if expectation is None:
        print(f"FAILED: {EXPECTATION.name} is missing.  This copy was packaged without its "
              "expected result; report that rather than working around it.")
        return 2
    print(f"the answer for {part_id}")
    return do_check(client, part_id, expectation)


if __name__ == "__main__":
    sys.exit(main())
