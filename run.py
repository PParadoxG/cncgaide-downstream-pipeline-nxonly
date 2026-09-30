#!/usr/bin/env python
"""CNCgAIde NX command line.

    python run.py build                   rebuild the ontology, rules and shapes from ontology/nx_v1_1/source
    python run.py fuseki start|stop|status
    python run.py sync [--input inputs] [--dry-run] [--all] [--no-rules] [--keep-missing]
    python run.py rules [--part ID ...]   rerun the rules only
    python run.py status                  one line per part
    python run.py query "SELECT ..." | --file q.rq
    python run.py check [--part ID]       SHACL validation of the facts and derived graphs
    python run.py view [--port 8765]      serve the web interface
    python run.py whatif --part ID t_hole_ld=3   verdicts that would change; temporary graphs only
    python run.py ged configs|compare A B|rank --query X
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "nxline" / "vendor"))


def cmd_build(args) -> int:
    return subprocess.run([sys.executable, str(ROOT / "ontology" / "nx_v1_1" / "build" / "build_all.py")]).returncode


def cmd_fuseki(args) -> int:
    from kg import server
    action = {"start": server.start, "stop": server.stop, "status": server.status}[args.action]
    print(json.dumps(action(ROOT), indent=1))
    return 0


def _client():
    from kg import server
    return server.ensure_running(ROOT)


def cmd_sync(args) -> int:
    from kg import sync
    client = _client()
    items = sync.plan(client, ROOT / args.input, force_all=args.all, keep_missing=args.keep_missing)
    for item in items:
        print(f"{item.part_id:40s} {item.action:8s} facts={item.facts_key or '-'} derived={item.derived_key or '-'}")
    if args.dry_run:
        return 0
    report = sync.execute(client, items, root=ROOT, run_rules=not args.no_rules)
    print(json.dumps(report, indent=1, default=str))
    return 1 if report["errors"] or report["blocked"] else 0


def cmd_rules(args) -> int:
    from kg import sync
    client = _client()
    items = sync.plan(client, ROOT / args.input)
    for item in items:
        if args.part and item.part_id not in args.part:
            continue
        if item.action == "build":
            print(f"{item.part_id}: facts are not current; run sync first")
            continue
        item.action = "rules"
    selected = [item for item in items if item.action == "rules" and (not args.part or item.part_id in args.part)]
    report = sync.execute(client, selected, root=ROOT)
    print(json.dumps(report, indent=1, default=str))
    return 0


def cmd_whatif(args) -> int:
    from kg import whatif
    thresholds = {}
    for item in args.threshold:
        symbol, _, value = item.partition("=")
        if not value:
            print(f"expected SYMBOL=VALUE, got {item!r}")
            return 2
        thresholds[symbol] = float(value)
    result = whatif.whatif(_client(), args.part, thresholds)
    print(json.dumps(result, indent=1, default=str))
    return 0


def cmd_status(args) -> int:
    from kg import sync
    client = _client()
    for part_id, row in sorted(sync.index_rows(client).items()):
        print(f"{part_id:40s} {row.get('status', '?'):10s} facts={row.get('factsKey', '-')} "
              f"derived={row.get('derivedKey', '-')}")
    return 0


def cmd_query(args) -> int:
    client = _client()
    text = Path(args.file).read_text(encoding="utf-8") if args.file else args.sparql
    if not text:
        print("give a query string or --file")
        return 2
    from tbox import nx as tbox
    prefixes = f"PREFIX nx: <{tbox.NX}>\nPREFIX cg: <{tbox.CG}>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
    result = client.query(prefixes + text) if not text.lstrip().upper().startswith("PREFIX") else client.query(text)
    if args.json:
        print(json.dumps(result, indent=1))
        return 0
    if "boolean" in result:
        print(result["boolean"])
        return 0
    variables = result["head"]["vars"]
    print("\t".join(variables))
    for binding in result["results"]["bindings"]:
        print("\t".join(binding.get(v, {}).get("value", "") for v in variables))
    return 0


def cmd_check(args) -> int:
    from kg import ontology, sync
    client = _client()
    shapes = ontology.shapes_text()
    failures = 0
    for part_id, row in sorted(sync.index_rows(client).items()):
        if args.part and part_id not in args.part:
            continue
        for key in ("factsGraph", "derivedGraph"):
            graph = row.get(key)
            if not graph:
                continue
            report = client.shacl(shapes, graph)
            conforms = "sh:conforms  true" in report or 'sh:conforms true' in report
            print(f"{part_id:40s} {key:13s} {'conforms' if conforms else 'VIOLATIONS'}")
            if not conforms:
                failures += 1
                if args.verbose:
                    print(report)
    return 1 if failures else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("build", help="rebuild the ontology from its YAML source").set_defaults(func=cmd_build)

    fuseki = commands.add_parser("fuseki", help="control the store")
    fuseki.add_argument("action", choices=["start", "stop", "status"])
    fuseki.set_defaults(func=cmd_fuseki)

    sync = commands.add_parser("sync", help="bring the store up to date with the input directory")
    sync.add_argument("--input", default="inputs")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--all", action="store_true", help="rebuild every part")
    sync.add_argument("--no-rules", action="store_true")
    sync.add_argument("--keep-missing", action="store_true")
    sync.set_defaults(func=cmd_sync)

    rules = commands.add_parser("rules", help="rerun the rules on current facts")
    rules.add_argument("--input", default="inputs")
    rules.add_argument("--part", nargs="*")
    rules.set_defaults(func=cmd_rules)

    commands.add_parser("status", help="one line per part").set_defaults(func=cmd_status)

    whatif = commands.add_parser("whatif", help="rerun the rules on one part with changed threshold values; nothing is kept")
    whatif.add_argument("--part", required=True)
    whatif.add_argument("threshold", nargs="+", metavar="SYMBOL=VALUE")
    whatif.set_defaults(func=cmd_whatif)

    query = commands.add_parser("query", help="run a SPARQL query")
    query.add_argument("sparql", nargs="?")
    query.add_argument("--file")
    query.add_argument("--json", action="store_true")
    query.set_defaults(func=cmd_query)

    check = commands.add_parser("check", help="SHACL validation")
    check.add_argument("--part", nargs="*")
    check.add_argument("--verbose", action="store_true")
    check.set_defaults(func=cmd_check)

    from web import cli as web_cli
    web_cli.add_parser(commands)
    commands.choices["view"].set_defaults(root=ROOT)
    from ged import cli as ged_cli
    ged_cli.add_parser(commands)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
