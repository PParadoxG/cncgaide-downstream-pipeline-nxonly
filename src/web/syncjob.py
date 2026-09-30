"""The two jobs the page starts that the ``sync`` verb cannot express.

``python run.py sync`` works on the whole input directory.  The page also
asks for one part at a time - rebuild this part now, drop this part from the
store - and those run here, as a child process of the job runner, through
the same planner and the same executor the verb uses:

    python -m web.syncjob sync --parts P [P ...] [--all] [--dry-run] [--input inputs]
    python -m web.syncjob remove --part P [--delete-source] [--input inputs]

``sync --parts`` plans the whole directory and executes only the named
parts; ``--all`` rebuilds them even when their keys are current.  ``remove``
drops the part's graphs, its index entry and its mesh; with
``--delete-source`` the STEP file goes too, otherwise the next sync builds
the part again.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _client():
    from kg import server

    return server.ensure_running(ROOT)


def _input_dir(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def cmd_sync(args) -> int:
    from kg import sync

    client = _client()
    wanted = set(args.parts)
    items = [item for item in sync.plan(client, _input_dir(args.input), force_all=args.all)
             if item.part_id in wanted]
    for item in items:
        print(f"{item.part_id:40s} {item.action:8s} facts={item.facts_key or '-'} derived={item.derived_key or '-'}")
    missing = sorted(wanted - {item.part_id for item in items})
    for part_id in missing:
        print(f"{part_id}: neither in the input directory nor in the store")
    if args.dry_run or not items:
        return 1 if missing else 0
    report = sync.execute(client, items, root=ROOT)
    print(json.dumps(report, indent=1, default=str))
    return 1 if report["errors"] or report["blocked"] or missing else 0


def cmd_remove(args) -> int:
    from kg import sync

    client = _client()
    items = [item for item in sync.plan(client, _input_dir(args.input)) if item.part_id == args.part]
    if not items:
        print(f"{args.part}: neither in the input directory nor in the store")
        return 1
    item = items[0]
    if item.current_facts_key or item.current_derived_key or item.current_facts_graph:
        sync.remove_part(client, item)
        print(f"removed {item.part_id} from the store")
    else:
        print(f"{item.part_id}: not in the store")
    if args.delete_source and item.step_path is not None and Path(item.step_path).is_file():
        Path(item.step_path).unlink()
        print(f"deleted {Path(item.step_path).name} from the input directory")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m web.syncjob")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("sync")
    run.add_argument("--parts", nargs="+", required=True)
    run.add_argument("--all", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--input", default="inputs")
    run.set_defaults(func=cmd_sync)
    remove = commands.add_parser("remove")
    remove.add_argument("--part", required=True)
    remove.add_argument("--delete-source", action="store_true")
    remove.add_argument("--input", default="inputs")
    remove.set_defaults(func=cmd_remove)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "src" / "nxline" / "vendor"))
    sys.exit(main())
