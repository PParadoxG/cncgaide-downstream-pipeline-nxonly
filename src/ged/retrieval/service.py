"""Similarity service: the one object the command line and the web server both call.

It owns nothing the distance does not already have - it only wires together
the projection (``ged.contract``), the ranking (``retrieval.query``), the
solver (``ged.solver``), the cost presets (``ged.cost.presets``) and the pair
cache (``retrieval.cache``) over the store, and returns dictionaries ready to
be written as JSON.  Because the command line and the endpoint go through the
same method, the two cannot drift apart.

Which parts exist and which are current is read from the index graph.  A part
is versioned by its ``factsKey``: the key is a function of the STEP file, the
installed NX schema and the code that produced the facts, so a part the store
rebuilt invalidates every cached distance it is in, and one that did not
rebuild keeps them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
import time
from typing import Any, Iterable

from ged.contract.projection import ProjectionAudit, load_part
from ged.contract.facts import PartAbsent, index_rows, read_part
from ged.contract.representation import NX
from ged.contract.schema import GedGraph
from ged.cost.config import CostConfig
from ged.cost.presets import (DEFAULT_PRESET, MICRO_EDIT_COST, WEIGHT_SPECS,
                              list_presets, resolve_config)
from ged.result import GedResult, result_labels
from ged.retrieval.cache import PairCache, PartFeatureCache, orient, result_from_payload
from ged.retrieval.query import rank as rank_graphs
from ged.semantics import semantics_stamp
from ged.solver.bp import ged


#: The index status a part must carry for its facts and verdicts to be current.
CURRENT = "current"


class PartNotFound(LookupError):
    """No such part in the store."""


class ProjectionFailed(RuntimeError):
    """The part exists but cannot be projected to a comparable graph."""


@dataclass(frozen=True)
class PartRef:
    part_id: str
    facts_key: str
    status: str | None


class _Candidate:
    """One part as the ranking sees it before anybody solves a pair.

    The pre-filter asks a candidate three things - its id, its class
    histogram and its ``L_ref`` - and those are all a warm ranking ever needs,
    because every pair comes back from the cache.  The projected graph is
    behind ``materialise`` and is only built for a pair that has to be solved.
    """

    __slots__ = ("_service", "_ref", "graph_id", "l_ref", "_histogram", "_graph")

    def __init__(self, service: "SimilarityService", ref: PartRef, l_ref: float,
                 histogram: dict[str, int], graph: GedGraph | None = None) -> None:
        self._service = service
        self._ref = ref
        self.graph_id = ref.part_id
        self.l_ref = float(l_ref)
        self._histogram = dict(histogram)
        self._graph = graph

    def type_histogram(self) -> dict[str, int]:
        return dict(self._histogram)

    def materialise(self) -> GedGraph:
        if self._graph is None:
            self._graph = self._service.graph(self._ref)
        return self._graph


def _config_block(info: dict[str, Any]) -> dict[str, Any]:
    """``{name, hash, weights, preset}`` - the same description ``configs``
    and ``rank`` return for a configuration."""
    return {
        "name": info["name"],
        "hash": info["hash"],
        "weights": dict(info["weights"]),
        "preset": bool(info.get("preset")),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SimilarityService:
    def __init__(self, client, *, cache_dir: str | Path, cache: PairCache | None = None) -> None:
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.representation = NX
        self.cache = cache or PairCache(self.cache_dir, semantics=semantics_stamp())
        self.features = PartFeatureCache(self.cache_dir, self.cache.semantics)
        self._graphs: dict[str, tuple[str, GedGraph]] = {}  # part_id -> (facts key, graph)
        # What each projection had to leave out, kept beside the graph it
        # belongs to, so a relation the representation could not place does
        # not simply vanish between the store and the page.
        self._audits: dict[str, tuple[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def _resolve(self, config_name, weights):
        return resolve_config(config_name, weights, representation=self.representation)

    def resolve(self, config_name=None, weights=None) -> dict[str, Any]:
        """``{name, hash, weights, preset}`` of a configuration, without
        computing a single pair: how the page shows the hash while a slider
        moves.  Raises ``KeyError`` / ``ValueError`` for an unknown preset or
        weight."""
        _, info = self._resolve(config_name, weights or {})
        return _config_block(info)

    # ------------------------------------------------------------ configs

    def configs(self) -> dict[str, Any]:
        return {
            "configs": list_presets(),
            "default": DEFAULT_PRESET,
            "weights": {key: dict(spec) for key, spec in WEIGHT_SPECS.items()},
            "line": self.representation.name,
            "representation": self.representation.name,
            "microEditCost": MICRO_EDIT_COST,
            "labels": result_labels(),
        }

    # -------------------------------------------------------------- parts

    def ref(self, part_id: str, *, rows=None) -> PartRef:
        """Version stamp and status of one part; PartNotFound if absent.

        ``rows`` is an index listing the caller already has, so a ranking over
        the whole store asks the index once rather than once per candidate.
        """
        try:
            row = (rows if rows is not None else index_rows(self.client))[part_id]
        except (KeyError, PartAbsent):
            raise PartNotFound(f"{part_id}: not in the store") from None
        return PartRef(part_id, row.facts_key, row.status)

    def part_ids(self) -> list[str]:
        """Every current part of the store, sorted."""
        return sorted(part_id for part_id, row in index_rows(self.client).items()
                      if row.status == CURRENT)

    def candidate(self, ref: PartRef) -> _Candidate:
        """``ref`` as the pre-filter sees it, projecting only if it must."""
        self._require_built(ref)
        with self._lock:
            hit = self._graphs.get(ref.part_id)
        if hit is not None and hit[0] == ref.facts_key:
            graph = hit[1]
            return _Candidate(self, ref, graph.l_ref, graph.type_histogram(), graph)
        stored = self.features.get(ref.part_id, ref.facts_key)
        if stored is not None:
            return _Candidate(self, ref, stored["lRef"], stored["typeHistogram"])
        graph = self.graph(ref)
        self.features.put(ref.part_id, ref.facts_key, graph.type_histogram(), graph.l_ref)
        return _Candidate(self, ref, graph.l_ref, graph.type_histogram(), graph)

    def _require_built(self, ref: PartRef) -> None:
        if ref.status != CURRENT:
            raise ProjectionFailed(f"{ref.part_id}: index status {ref.status}")

    def graph(self, ref: PartRef) -> GedGraph:
        """The projected graph of ``ref`` (cached per version)."""
        self._require_built(ref)
        with self._lock:
            hit = self._graphs.get(ref.part_id)
            if hit is not None and hit[0] == ref.facts_key:
                return hit[1]
        audit = ProjectionAudit()
        try:
            graph = load_part(self.client, ref.part_id, graph_id=ref.part_id,
                              representation=self.representation, audit=audit)
        except Exception as error:  # noqa: BLE001 - the reason travels to the caller
            # The type and the part, never the message: this string ends up in
            # an HTTP response body.  The whole exception is logged where the
            # server can see it.
            print(f"[ged] projection failed for {ref.part_id}: "
                  f"{type(error).__name__}: {error}", file=sys.stderr)
            raise ProjectionFailed(f"{ref.part_id}: {type(error).__name__}") from error
        with self._lock:
            self._graphs[ref.part_id] = (ref.facts_key, graph)
            self._audits[ref.part_id] = (ref.facts_key, {
                "edgesDropped": dict(audit.edges_dropped),
                "unknownRelationTypes": list(audit.unknown_relation_types),
                "unknownLeafTypes": list(audit.unknown_leaf_types),
            })
        return graph

    def projection_block(self, part_ids: Iterable[str]) -> dict[str, Any]:
        """What the projections behind this answer had to leave out.

        Purely additive, and it states its own coverage: a part answered from
        the stored feature file or from a cached pair was never projected in
        this call, so nothing is known about it here and it is listed rather
        than reported as zero.  ``edgesDropped`` is the total over the parts
        that were projected, by reason.
        """
        wanted = list(dict.fromkeys(part_ids))
        totals: dict[str, int] = {}
        by_part: dict[str, dict[str, int]] = {}
        not_projected: list[str] = []
        with self._lock:
            for part_id in wanted:
                entry = self._audits.get(part_id)
                if entry is None:
                    not_projected.append(part_id)
                    continue
                dropped = entry[1]["edgesDropped"]
                if dropped:
                    by_part[part_id] = dict(dropped)
                for reason, count in dropped.items():
                    totals[reason] = totals.get(reason, 0) + int(count)
        return {
            "edgesDropped": dict(sorted(totals.items())),
            "byPart": {key: by_part[key] for key in sorted(by_part)},
            "notProjectedInThisCall": not_projected,
        }

    # ------------------------------------------------------------ results

    def _lookup(self, info: dict[str, Any], a: PartRef, b: PartRef, *,
                with_edit_path: bool = False) -> dict[str, Any] | None:
        payload = self.cache.get(info["hash"], a.part_id, b.part_id, a.facts_key, b.facts_key,
                                 with_edit_path=with_edit_path)
        return None if payload is None else orient(payload, a.part_id, b.part_id)

    def _store(self, result: GedResult, info: dict[str, Any], a: PartRef, b: PartRef) -> dict[str, Any]:
        payload = result.to_dict(include_edit_path=True)
        payload["config"] = _config_block(info)
        payload["line"] = self.representation.name
        payload["representation"] = self.representation.name
        payload["producedAt"] = {"a": a.facts_key, "b": b.facts_key}
        payload["computedAt"] = _utc_now()
        # Only preset configurations are worth a file on disk; a custom weight
        # set is an experiment and lives in memory for the life of the server.
        stored = self.cache.put(
            info["hash"], a.part_id, b.part_id, a.facts_key, b.facts_key, payload,
            persist=bool(info.get("preset")),
        )
        return orient(stored, a.part_id, b.part_id)

    def compare(self, id_a: str, id_b: str, *, config_name: str | None = None,
                weights: dict[str, object] | None = None) -> dict[str, Any]:
        """The full pair result (with edit path), oriented ``a`` -> ``b``."""
        config, info = self._resolve(config_name, weights)
        ref_a, ref_b = self.ref(id_a), self.ref(id_b)
        graph_a, graph_b = self.graph(ref_a), self.graph(ref_b)
        started = time.perf_counter()
        # The compare page is the edit path, so this is the one caller that
        # asks the cache for it.
        payload = self._lookup(info, ref_a, ref_b, with_edit_path=True)
        cached = payload is not None
        if payload is None:
            payload = self._store(ged(graph_a, graph_b, config), info, ref_a, ref_b)
        # The cache key is the configuration hash, so the description is the
        # same whichever side wrote the file.
        payload["config"] = _config_block(info)
        payload["line"] = self.representation.name
        payload["representation"] = self.representation.name
        payload["cached"] = cached
        payload["projection"] = self.projection_block([id_a, id_b])
        payload["timingMs"] = round((time.perf_counter() - started) * 1000.0, 1)
        return payload

    def rank(self, query_id: str, *, config_name: str | None = None,
             weights: dict[str, object] | None = None,
             candidate_ids: Iterable[str] | None = None,
             top: int | None = None,
             prefilter_keep: int | None = None) -> dict[str, Any]:
        """Ranking of ``query_id`` against the candidates (default: every
        other current part of the store)."""
        started = time.perf_counter()
        config, info = self._resolve(config_name, weights)
        rows = index_rows(self.client)
        query_ref = self.ref(query_id, rows=rows)
        query = self.candidate(query_ref)

        ids = (list(candidate_ids) if candidate_ids is not None
               else sorted(p for p, row in rows.items() if row.status == CURRENT))
        refs: dict[str, PartRef] = {query_id: query_ref}
        graphs: list[_Candidate] = []
        failed: dict[str, str] = {}
        for part_id in ids:
            if part_id == query_id:
                continue
            try:
                ref = self.ref(part_id, rows=rows)
                graphs.append(self.candidate(ref))
                refs[part_id] = ref
            except (PartNotFound, ProjectionFailed) as error:
                failed[part_id] = str(error)

        hits: set[str] = set()

        def solve(left: _Candidate, right: _Candidate, cfg: CostConfig) -> GedResult:
            ref_l, ref_r = refs[left.graph_id], refs[right.graph_id]
            payload = self._lookup(info, ref_l, ref_r)
            if payload is not None:
                hits.add(right.graph_id)
                return result_from_payload(payload)
            # Only here does a graph have to exist.
            result = ged(left.materialise(), right.materialise(), cfg)
            self._store(result, info, ref_l, ref_r)
            return result

        ranked = rank_graphs(
            query, graphs, config=config, top=top, prefilter_keep=prefilter_keep, solve=solve,
        )
        rows = []
        for position, item in enumerate(ranked, 1):
            result = item.result
            rows.append({
                "rank": position,
                "partId": item.graph_id,
                "distance": result.normalized_distance,
                "similarity": result.similarity_percent,
                "rawCost": result.raw_cost,
                "upperBound": result.upper_bound,
                "breakdown": result.to_dict(include_edit_path=False)["breakdown"],
                "prefilterScore": item.prefilter_score,
                "cached": item.graph_id in hits,
                "producedAt": refs[item.graph_id].facts_key,
            })
        return {
            "query": query_id,
            "queryProducedAt": query_ref.facts_key,
            "line": self.representation.name,
            "representation": self.representation.name,
            "config": info,
            "corpus": {"loaded": 1 + len(graphs), "failed": failed},
            "candidates": len(graphs),
            "top": top,
            "prefilterKeep": prefilter_keep,
            "ranked": rows,
            "projection": self.projection_block(
                [query_id] + [item.graph_id for item in graphs]),
            "timingMs": round((time.perf_counter() - started) * 1000.0, 1),
        }
