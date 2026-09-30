"""Pair result cache keyed by the two parts' facts keys, the cost
configuration and the semantics of the code that priced them.

One entry = one result (with its edit path) for an unordered pair of parts
under one configuration hash.  The key carries both parts' facts keys, so a
part the store rebuilt invalidates every pair it is in without anybody having
to clean up: a stale entry simply never matches again.  It carries the
semantics stamp for the same reason - the configuration hash is only the
eight weights, so a representation or cost-table change would otherwise be
served from entries computed before it.  Both live in the payload rather than
in the path, so a superseded entry is overwritten in place instead of leaving
an orphaned directory behind.

Preset configurations are persisted under
``runs/ged/pairs/<config hash>/<idA>__<idB>.json``; custom weight sets live in
memory only.  Everything under ``runs/`` is written by the system and is not
hand-edited.

Entries are stored in *sorted* orientation (``graph_id_a`` is the smaller
id); ``orient`` flips a payload to the orientation a caller asked for.  The
flip is exact: the solver computes both directions and averages them, so the
distance from b to a is the one from a to b with the two direction blocks
swapped.
"""

from __future__ import annotations

from collections import OrderedDict
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

from ged.result import GedBreakdown, GedResult
from ged.semantics import semantics_stamp


PAIRS_DIR = "pairs"
FEATURES_DIR = "features"

# How many pair results one process keeps in memory.  The cache key contains
# the configuration hash and the hash is a function of the eight weights, so
# every position of a page slider is a new key and nothing ever collides with
# what came before: without a bound the server's memory is linear in "how
# many weight vectors has anyone tried today".
MEMORY_ENTRIES = 512
#: The edit path is almost all of a payload, and only ``compare`` reads it -
#: one pair at a time.  Ranking keeps the light entries; the last few full
#: ones are kept beside them so that looking at the same pair twice is free.
FULL_ENTRIES = 8


class PartFeatureCache:
    """The two numbers the pre-filter needs, without projecting the part.

    A ranking whose every pair is already in the pair cache would still have
    to project every candidate, because the pre-filter asks each one for its
    class histogram and its ``L_ref``.  Those two are cheap to write down and
    are a function of the same things the pair cache is keyed on: the part's
    facts key and the semantics stamp of the tables that produced them.

    Written by the system, in the run directory, never hand-edited; a miss
    costs exactly the projection it was avoiding.
    """

    def __init__(self, cache_dir: str | Path, semantics: str) -> None:
        self.root = Path(cache_dir) / FEATURES_DIR
        self.semantics = semantics

    def path(self, part_id: str) -> Path:
        return self.root / f"{part_id}.json"

    def get(self, part_id: str, facts_key: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path(part_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("semantics") != self.semantics or payload.get("factsKey") != facts_key:
            return None
        histogram = payload.get("typeHistogram")
        l_ref = payload.get("lRef")
        if not isinstance(histogram, dict) or not isinstance(l_ref, (int, float)):
            return None
        return {"typeHistogram": {str(k): int(v) for k, v in histogram.items()},
                "lRef": float(l_ref)}

    def put(self, part_id: str, facts_key: str, histogram: dict[str, int], l_ref: float) -> None:
        _write_json(self.path(part_id), {
            "partId": part_id,
            "factsKey": facts_key,
            "semantics": self.semantics,
            "typeHistogram": dict(sorted(histogram.items())),
            "lRef": float(l_ref),
        })


def pair_order(id_a: str, id_b: str) -> tuple[str, str]:
    return (id_a, id_b) if id_a <= id_b else (id_b, id_a)


def orient(payload: dict[str, Any], id_a: str, id_b: str) -> dict[str, Any]:
    """A shallow copy of ``payload`` with ``a`` = ``id_a``, ``b`` = ``id_b``."""
    out = dict(payload)
    if out.get("graph_id_a") == id_a and out.get("graph_id_b") == id_b:
        return out
    if not (out.get("graph_id_a") == id_b and out.get("graph_id_b") == id_a):
        raise ValueError(f"payload is for {out.get('graph_id_a')}/{out.get('graph_id_b')}, not {id_a}/{id_b}")
    out["graph_id_a"], out["graph_id_b"] = id_a, id_b
    path = out.get("edit_path")
    if isinstance(path, dict):
        out["edit_path"] = {"a_to_b": path.get("b_to_a"), "b_to_a": path.get("a_to_b")}
    produced = out.get("producedAt")
    if isinstance(produced, dict):
        out["producedAt"] = {"a": produced.get("b"), "b": produced.get("a")}
    return out


def _breakdown_is_readable(breakdown: Any) -> bool:
    """Can ``result_from_payload`` still build a breakdown from this?

    "Is it a dict" is not the same question: the constructor raises on a key
    it does not know, so one entry written by a version with an extra cost
    channel would turn every ranking touching that pair into an error whose
    text never mentions the cache.  A file this reader cannot use is a miss,
    and a miss is recomputed and overwritten in place.
    """
    if not isinstance(breakdown, dict):
        return False
    return set(breakdown) == set(GedBreakdown.__dataclass_fields__)


def result_from_payload(payload: dict[str, Any]) -> GedResult:
    """Rebuild the typed result from a cached payload (in its own orientation)."""
    config = payload.get("config")
    name = config.get("name") if isinstance(config, dict) else str(config)
    return GedResult(
        graph_id_a=str(payload["graph_id_a"]),
        graph_id_b=str(payload["graph_id_b"]),
        raw_cost=float(payload["raw_cost"]),
        upper_bound=float(payload["upper_bound"]),
        normalized_distance=float(payload["normalized_distance"]),
        similarity_percent=float(payload["similarity_percent"]),
        breakdown=GedBreakdown(**{k: float(v) for k, v in payload["breakdown"].items()}),
        edit_path=dict(payload.get("edit_path") or {}),
        config_name=str(name),
    )


class PairCache:
    def __init__(self, cache_dir: str | Path, *, semantics: str | None = None) -> None:
        self.root = Path(cache_dir) / PAIRS_DIR
        self.semantics = semantics if semantics is not None else semantics_stamp()
        # Two bounded LRUs: everything, without its edit path, and the last
        # few complete payloads.  See MEMORY_ENTRIES / FULL_ENTRIES above.
        self._memory: "OrderedDict[tuple, dict[str, Any]]" = OrderedDict()
        self._full: "OrderedDict[tuple, dict[str, Any]]" = OrderedDict()
        self._unusable: set[str] = set()
        self._lock = threading.Lock()

    # -- keys -----------------------------------------------------------------

    @staticmethod
    def key(config_hash: str, id_a: str, id_b: str, facts_a: str | None,
            facts_b: str | None, semantics: str = "") -> tuple:
        first, second = pair_order(id_a, id_b)
        fa, fb = (facts_a, facts_b) if first == id_a else (facts_b, facts_a)
        return (config_hash, semantics, first, second, fa or "", fb or "")

    def path(self, config_hash: str, id_a: str, id_b: str) -> Path:
        first, second = pair_order(id_a, id_b)
        return self.root / config_hash / f"{first}__{second}.json"

    # -- read / write ---------------------------------------------------------

    def get(self, config_hash: str, id_a: str, id_b: str, facts_a: str | None,
            facts_b: str | None, *, with_edit_path: bool = False) -> dict[str, Any] | None:
        """The stored payload in sorted orientation, or None (miss, stale, corrupt).

        ``with_edit_path`` is what ``compare`` needs and ``rank`` does not.
        The light in-memory entry cannot answer it, so such a call falls
        through to the file - and, for a weight set that was never persisted,
        to a miss, which is a recomputation of one pair and the same number.
        """
        key = self.key(config_hash, id_a, id_b, facts_a, facts_b, self.semantics)
        with self._lock:
            store = self._full if with_edit_path else self._memory
            hit = store.get(key)
            if hit is not None:
                store.move_to_end(key)
        if hit is not None:
            return hit
        path = self.path(config_hash, id_a, id_b)
        payload = self._read(path)
        if payload is None:
            return None
        if not self._matches(payload, key):
            self._note_unusable(path, payload)
            return None
        self._remember(key, payload)
        return payload

    def put(self, config_hash: str, id_a: str, id_b: str, facts_a: str | None,
            facts_b: str | None, payload: dict[str, Any], *,
            persist: bool = True) -> dict[str, Any]:
        """Store ``payload`` (any orientation); returns it in sorted orientation.

        The cache stamps the entry with its own semantics: the writer does not
        get to claim a version the reader would then trust.
        """
        first, second = pair_order(id_a, id_b)
        stored = orient(payload, first, second)
        stored["semantics"] = self.semantics
        key = self.key(config_hash, id_a, id_b, facts_a, facts_b, self.semantics)
        self._remember(key, stored)
        if persist:
            self._write(self.path(config_hash, id_a, id_b), stored)
        return stored

    def clear_memory(self) -> None:
        with self._lock:
            self._memory.clear()
            self._full.clear()

    def memory_size(self) -> tuple[int, int]:
        """``(light entries, full entries)`` - what this process is holding."""
        with self._lock:
            return len(self._memory), len(self._full)

    # -- helpers --------------------------------------------------------------

    def _remember(self, key: tuple, payload: dict[str, Any]) -> None:
        """Keep it, bounded, and without repeating the edit path everywhere."""
        light = {name: value for name, value in payload.items() if name != "edit_path"}
        with self._lock:
            self._memory[key] = light
            self._memory.move_to_end(key)
            while len(self._memory) > MEMORY_ENTRIES:
                self._memory.popitem(last=False)
            if "edit_path" in payload:
                self._full[key] = payload
                self._full.move_to_end(key)
                while len(self._full) > FULL_ENTRIES:
                    self._full.popitem(last=False)

    def _note_unusable(self, path: Path, payload: dict[str, Any]) -> None:
        """Say once, per file, that a readable entry could not be used.

        A stale facts key or a superseded semantics stamp is the design
        working and says nothing; a *breakdown this reader cannot build* means
        the file was written by different code, and the operator should hear
        it once rather than wonder why nothing is ever cached.
        """
        if _breakdown_is_readable(payload.get("breakdown")):
            return
        name = str(path)
        with self._lock:
            if name in self._unusable:
                return
            self._unusable.add(name)
        print(f"[ged] ignoring a pair cache entry this version cannot read "
              f"(unexpected breakdown keys): {path.name}", file=sys.stderr)

    @staticmethod
    def _matches(payload: dict[str, Any], key: tuple) -> bool:
        config_hash, semantics, first, second, fa, fb = key
        config = payload.get("config")
        stored_hash = config.get("hash") if isinstance(config, dict) else None
        produced = payload.get("producedAt") or {}
        return (
            stored_hash == config_hash
            and str(payload.get("semantics") or "") == semantics
            and payload.get("graph_id_a") == first
            and payload.get("graph_id_b") == second
            and (produced.get("a") or "") == fa
            and (produced.get("b") or "") == fb
            and _breakdown_is_readable(payload.get("breakdown"))
        )

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        _write_json(path, payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic, fsynced, and silent about a disk that will not take it.

    A cache that cannot be written is a slower cache, not an error.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
