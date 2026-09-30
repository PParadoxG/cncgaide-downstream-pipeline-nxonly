"""The ``ged`` command: presets, one pair, one ranking.

``add_parser`` hangs the verbs off the top-level command table and ``main``
runs the one that was chosen.  Both the command line and the web endpoint go
through ``SimilarityService``, so what is printed here with ``--json`` is
what the endpoint answers.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "runs" / "ged"


def add_parser(subparsers) -> None:
    ged = subparsers.add_parser("ged", help="graph edit distance between parts in the store")
    commands = ged.add_subparsers(dest="ged_command")

    def cost_options(command) -> None:
        command.add_argument("--config", default=None, metavar="NAME",
                             help="cost preset (see `ged configs`; default v0_default)")
        command.add_argument("--weights", default=None, metavar="K=V,...",
                             help="override single weights on top of the preset, "
                                  "e.g. W_REL=0.8,C_DEL=1 (or a JSON object)")

    configs = commands.add_parser("configs", help="list the cost presets with their hashes")
    configs.add_argument("--json", action="store_true")

    compare = commands.add_parser("compare", help="distance between two parts")
    compare.add_argument("part_a")
    compare.add_argument("part_b")
    compare.add_argument("--edit-path", action="store_true", help="print the full edit path as JSON")
    cost_options(compare)

    rank = commands.add_parser("rank", help="rank every part of the store against a query part")
    rank.add_argument("--query", required=True)
    rank.add_argument("--top", type=int, default=0, help="show only the best N (0 = all)")
    rank.add_argument("--prefilter-keep", type=int, default=0,
                      help="run the distance only on the N best pre-filter candidates (0 = all)")
    rank.add_argument("--candidates", nargs="+", metavar="ID", default=None,
                      help="restrict the candidates to these parts")
    rank.add_argument("--json", action="store_true",
                      help="print exactly what the similarity endpoint returns")
    cost_options(rank)

    ged.set_defaults(func=main, parser=ged)


def _service():
    from kg import server
    from ged.retrieval.service import SimilarityService

    return SimilarityService(server.ensure_running(ROOT), cache_dir=CACHE_DIR)


def main(args) -> int:
    from ged.cost.presets import WEIGHT_SPECS, cli_weights, list_presets, parse_weights

    command = getattr(args, "ged_command", None)

    if command == "configs":
        presets = list_presets()
        if args.json:
            print(json.dumps({"configs": presets, "weights": WEIGHT_SPECS},
                             ensure_ascii=False, indent=2))
            return 0
        for preset in presets:
            print(f"{preset['name']:16s} {preset['hash']}  {cli_weights(preset['weights'])}")
        print("weights: " + ", ".join(f"{key} [{spec['min']:g}..{spec['max']:g}]"
                                      for key, spec in WEIGHT_SPECS.items()))
        return 0

    if command not in ("compare", "rank"):
        args.parser.print_help()
        return 0

    try:
        weights = parse_weights(args.weights)
    except (KeyError, ValueError) as error:
        print(f"[ged] {error}")
        return 2

    from ged.retrieval.service import PartNotFound, ProjectionFailed

    service = _service()

    if command == "compare":
        try:
            payload = service.compare(args.part_a, args.part_b,
                                      config_name=args.config, weights=weights)
        except (KeyError, ValueError) as error:
            print(f"[ged] {error}")
            return 2
        except (PartNotFound, ProjectionFailed) as error:
            print(f"[ged] not loaded: {error}")
            return 2
        if not args.edit_path:
            payload.pop("edit_path", None)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    try:
        payload = service.rank(
            args.query,
            config_name=args.config,
            weights=weights,
            candidate_ids=args.candidates,
            top=args.top or None,
            prefilter_keep=args.prefilter_keep or None,
        )
    except (KeyError, ValueError) as error:
        print(f"[ged] {error}")
        return 2
    except (PartNotFound, ProjectionFailed) as error:
        print(f"[ged] query {args.query} not available ({error})")
        return 2
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    corpus = payload["corpus"]
    config = payload["config"]
    print(f"[ged] query {args.query}: {payload['candidates']} candidates "
          f"({corpus['loaded']} loaded, {len(corpus['failed'])} failed)  "
          f"config {config['name']} #{config['hash']}  {payload['timingMs']:.0f} ms")
    for row in payload["ranked"]:
        b = row["breakdown"]
        cached = "  (cached)" if row["cached"] else ""
        print(f"{row['rank']:3d}. {row['partId']:50s} d={row['distance']:.6f} "
              f"sim={row['similarity']:7.3f}%  node={b['node_cost']:.3f} "
              f"edge={b['edge_cost']:.3f} fixed={b['fixed_cost']:.4f} "
              f"scale={b['scale_cost']:.4f}  prefilter={row['prefilterScore']:.3f}{cached}")
    for part_id, reason in corpus["failed"].items():
        print(f"     failed: {part_id}: {reason}")
    return 0
