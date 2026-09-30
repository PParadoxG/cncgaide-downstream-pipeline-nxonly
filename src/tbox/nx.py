"""The ontology's YAML source, loaded once and answered from memory.

``ontology/nx_v1_1/source/*.yaml`` is the single definition of the system:
NX's classes and attributes, the pipeline's relations, derived quantities,
thresholds, heuristics, KPI vocabulary and display defaults.  Every other
module that needs a fact about the vocabulary asks this one.

Standard library plus ``yaml`` only, so the NX journal process (which has the
vendored pure-python yaml on its path) can read it too.
"""

from __future__ import annotations

import hashlib
import re
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import yaml

ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "ontology" / "nx_v1_1"
SOURCE_DIR = ONTOLOGY_DIR / "source"
DIST_DIR = ONTOLOGY_DIR / "dist"

FILES = {
    "classes": SOURCE_DIR / "classes.yaml",
    "attributes": SOURCE_DIR / "attributes.yaml",
    "relations": SOURCE_DIR / "relations.yaml",
    "derived": SOURCE_DIR / "derived.yaml",
    "thresholds": SOURCE_DIR / "thresholds.yaml",
    "heuristics": SOURCE_DIR / "heuristics.yaml",
    "kpi": SOURCE_DIR / "kpi.yaml",
    "display": SOURCE_DIR / "display.yaml",
    "scope": SOURCE_DIR / "recognition_scope.yaml",
}

ONTOLOGY_VERSION = "1.1"
NX = "https://cncgaide.org/ontology/nx/1.1#"
CG = "https://cncgaide.org/ontology/nx/1.1/pipeline#"
PARTS = "https://cncgaide.org/parts/"
GRAPHS = "https://cncgaide.org/graph/"

_DIAMETER_K = re.compile(r"^DIAMETER_(\d+)$")
_DEPTH_K = re.compile(r"^DEPTH_(\d+)$")


def _load(name: str) -> dict:
    return yaml.safe_load(FILES[name].read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else ""


@lru_cache(maxsize=1)
def source_digest() -> str:
    """One digest over every source file, in a fixed order."""
    h = hashlib.sha256()
    for key in sorted(FILES):
        h.update(key.encode())
        h.update(FILES[key].read_bytes() if FILES[key].is_file() else b"")
    return h.hexdigest()[:16]


@lru_cache(maxsize=1)
def build_digest() -> str:
    """One digest over the build scripts that turn the source into dist/."""
    h = hashlib.sha256()
    for path in sorted((ONTOLOGY_DIR / "build").glob("*.py")):
        if path.name.startswith("_") or path.name in ("bootstrap_from_nx.py", "gen_page.py"):
            continue
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


@lru_cache(maxsize=1)
def ontology_digest() -> str:
    """Identifies one built ontology: its source and the build that produced it."""
    return hashlib.sha256((source_digest() + build_digest()).encode()).hexdigest()[:16]


def source_version() -> dict:
    return {f"{key}YamlSha256": digest(path) for key, path in sorted(FILES.items())}


# ------------------------------------------------------------------ classes

@lru_cache(maxsize=1)
def _classes() -> dict:
    classes = _load("classes")
    attributes = _load("attributes")
    by_name = {entry["name"]: entry for entry in classes["classes"]}
    root_runtime: set[str] = set()
    observed_runtime: dict[str, set[str]] = {}
    for item in attributes["attributes"]:
        if item["declaredIn"] != "runtime":
            continue
        on = item.get("declaredOn", "root")
        if on == "root":
            root_runtime.add(item["name"])
        else:
            for owner in on:
                observed_runtime.setdefault(owner, set()).add(item["name"])

    def chain(name: str) -> tuple[str, ...]:
        walk: list[str] = []
        cursor = name
        while cursor and cursor in by_name and cursor not in walk:
            walk.append(cursor)
            cursor = by_name[cursor]["parent"]
        return tuple(walk)

    ancestry = {name: chain(name) for name in by_name}
    effective = {}
    for name, walk in ancestry.items():
        names = set(root_runtime)
        for step in walk:
            names |= set(by_name[step]["attributes"])
            names |= observed_runtime.get(step, set())
        effective[name] = tuple(sorted(names))
    return {
        "head": classes["head"],
        "byName": by_name,
        "ancestry": ancestry,
        "effective": effective,
        "attributes": {item["name"]: item for item in attributes["attributes"]},
        "attributesHead": attributes["head"],
    }


def classes_head() -> dict:
    return _classes()["head"]


def class_names() -> tuple[str, ...]:
    return tuple(sorted(_classes()["byName"]))


def class_record(name: str) -> dict | None:
    return _classes()["byName"].get(name)


def ancestry(name: str) -> tuple[str, ...]:
    return _classes()["ancestry"].get(name, ())


def parent(name: str) -> str | None:
    record = class_record(name)
    return record["parent"] if record else None


def is_abstract(name: str) -> bool:
    record = class_record(name)
    return bool(record and record["abstract"])


def label(name: str) -> str | None:
    record = class_record(name)
    return record.get("label") if record else None


def in_family(name: str, family: str) -> bool:
    return family in _classes()["ancestry"].get(name, ())


def recognisable_classes() -> tuple[str, ...]:
    return tuple(sorted(n for n, e in _classes()["byName"].items() if e.get("recognisable")))


def effective_attributes(name: str) -> tuple[str, ...]:
    return _classes()["effective"].get(name, ())


def declares(name: str, attribute: str) -> bool:
    return any(fnmatchcase(candidate, attribute) for candidate in effective_attributes(name))


def attribute_record(name: str) -> dict | None:
    return _classes()["attributes"].get(name)


def attribute_names() -> tuple[str, ...]:
    return tuple(sorted(_classes()["attributes"]))


def expand_pattern(pattern: str, *, recognisable_only: bool = True) -> tuple[str, ...]:
    """Class names matching one appliesTo pattern (a name or a glob)."""
    pool = recognisable_classes() if recognisable_only else class_names()
    return tuple(name for name in pool if fnmatchcase(name, pattern))


def expand_patterns(patterns, *, recognisable_only: bool = True) -> tuple[str, ...]:
    out: list[str] = []
    for pattern in patterns or ():
        for name in expand_pattern(pattern, recognisable_only=recognisable_only):
            if name not in out:
                out.append(name)
    return tuple(sorted(out))


# ------------------------------------------------------------------- ladder

def section_count(feature_type: str) -> int:
    indexes = [int(m.group(1)) for m in (_DIAMETER_K.match(n) for n in effective_attributes(feature_type)) if m]
    return max(indexes) if indexes else 0


def sections(feature_type: str) -> tuple[dict, ...]:
    """``({index, diameterAttribute, depthFromAttribute|None, depthToAttribute}, ...)``.

    ``DEPTH_k`` is cumulative from the entry; the last section ends at
    ``DEPTH``.  Empty when the class declares no ``DIAMETER_k``.
    """
    count = section_count(feature_type)
    if not count:
        return ()
    declared = set(effective_attributes(feature_type))
    if "DEPTH" not in declared:
        return ()
    boundaries: list[str | None] = [None]
    for index in range(1, count):
        name = f"DEPTH_{index}"
        if name not in declared:
            return ()
        boundaries.append(name)
    boundaries.append("DEPTH")
    return tuple(
        {"index": index, "diameterAttribute": f"DIAMETER_{index}",
         "depthFromAttribute": boundaries[index - 1], "depthToAttribute": boundaries[index]}
        for index in range(1, count + 1)
    )


def expand_attribute_pattern(feature_type: str, pattern: str) -> tuple[str, ...]:
    """Concrete attribute names one usesAttributes entry means on one class."""
    if pattern == "DIAMETER_k":
        return tuple(f"DIAMETER_{i}" for i in range(1, section_count(feature_type) + 1))
    if pattern == "DEPTH_k":
        return tuple(s["depthFromAttribute"] for s in sections(feature_type) if s["depthFromAttribute"])
    if pattern == "DIAMETER_n":
        count = section_count(feature_type)
        return (f"DIAMETER_{count}",) if count else ()
    return (pattern,)


# ----------------------------------------------------------- pipeline terms

@lru_cache(maxsize=1)
def relations() -> dict:
    return _load("relations")


def relation_types() -> dict[str, dict]:
    return {entry["label"]: entry for entry in relations()["types"]}


@lru_cache(maxsize=1)
def derived() -> dict:
    return _load("derived")


def derived_attributes() -> dict[str, dict]:
    return {entry["name"]: entry for entry in derived()["quantities"]}


def derived_domain(name: str) -> tuple[str, ...]:
    record = derived_attributes().get(name) or {}
    return tuple(record.get("appliesTo") or ())


@lru_cache(maxsize=1)
def thresholds() -> dict[str, dict]:
    return {entry["symbol"]: entry for entry in _load("thresholds")["thresholds"]}


def threshold_value(symbol: str):
    record = thresholds()[symbol]
    return record["members"] if "members" in record else record["value"]


@lru_cache(maxsize=1)
def heuristics() -> dict:
    return _load("heuristics")


def definitions() -> dict[str, dict]:
    return {entry["id"]: entry for entry in heuristics()["heuristics"]}


def heuristic_domain(h_id: str) -> tuple[str, ...]:
    """The recognisable classes a rule applies to: its patterns, restricted to
    classes that declare every attribute the rule uses (derived quantities
    are attached by the rule, not by the class, and never restrict)."""
    rule = definitions()[h_id]
    derived_names = set(derived_attributes())
    out = []
    for name in expand_patterns(rule.get("appliesTo")):
        if is_abstract(name):
            continue
        ok = True
        for pattern in rule.get("usesAttributes") or ():
            if pattern in derived_names:
                continue
            concrete = expand_attribute_pattern(name, pattern)
            if pattern in ("DIAMETER_k", "DEPTH_k", "DIAMETER_n"):
                if not sections(name):
                    ok = False
                    break
            elif not concrete or not all(declares(name, c) for c in concrete):
                ok = False
                break
        if ok:
            out.append(name)
    return tuple(out)


def required_attributes(h_id: str, feature_type: str) -> tuple[str, ...]:
    """Concrete attribute (or derived quantity) names the rule reads on one class."""
    rule = definitions()[h_id]
    names: list[str] = []
    for pattern in rule.get("usesAttributes") or ():
        for concrete in expand_attribute_pattern(feature_type, pattern):
            if concrete not in names:
                names.append(concrete)
    return tuple(names)


def used_attributes_by_class() -> dict[str, list[str]]:
    """``{class: NX attribute names some rule reads}`` for every recognisable class."""
    derived_names = set(derived_attributes())
    used: dict[str, set[str]] = {name: set() for name in recognisable_classes() if not is_abstract(name)}
    for h_id in definitions():
        for name in heuristic_domain(h_id):
            used.setdefault(name, set()).update(set(required_attributes(h_id, name)) - derived_names)
    return {name: sorted(values) for name, values in sorted(used.items())}


@lru_cache(maxsize=1)
def kpi() -> dict:
    return _load("kpi")


def kpi_types() -> dict[str, dict]:
    return {entry["id"]: entry for entry in kpi()["types"]}


def kpi_derivations() -> list[dict]:
    return list(kpi().get("derivations") or [])


def kpi_derivation_domain(derivation: dict) -> tuple[str, ...]:
    out = []
    for name in expand_patterns(derivation.get("appliesTo")):
        if is_abstract(name):
            continue
        ok = True
        for p in derivation.get("usesAttributes") or ():
            if p in ("DIAMETER_k", "DEPTH_k", "DIAMETER_n"):
                ok = ok and bool(sections(name))
            else:
                ok = ok and all(declares(name, c) for c in expand_attribute_pattern(name, p))
        if ok:
            out.append(name)
    return tuple(out)


@lru_cache(maxsize=1)
def display() -> dict:
    return _load("display")


def background_types() -> tuple[str, ...]:
    return tuple(display().get("backgroundTypes") or ())


def is_hidden_by_default(feature_type: str) -> bool:
    if feature_type in background_types():
        return True
    return any(fnmatchcase(feature_type, p) for p in display().get("hiddenByDefaultPatterns") or ())


def feature_color(feature_type: str) -> str | None:
    for pattern, color in (display().get("featureColors") or {}).items():
        if fnmatchcase(feature_type, pattern):
            return color
    return None


def relation_color(edge_type: str) -> str | None:
    return (display().get("relationColors") or {}).get(edge_type)


@lru_cache(maxsize=1)
def scope() -> dict:
    return _load("scope")


# -------------------------------------------------------------------- units
#
# NX declares a unit *kind* for an attribute - Length, Angle or Area, as
# customization_base.xml writes it, copied into attributes.yaml as ``unit`` -
# and the symbol a kind is printed with depends on the part: a length is in
# the part's units, ``BasePart.Units`` as NX names it (recorded on the part as
# ``cg:lengthUnit``), an area is that length squared, and NX hands every angle
# over in degrees whatever the part's units.  The symbols are the ones the
# source writes for its own quantities (``mm`` and ``deg`` in derived.yaml,
# relations.yaml and thresholds.yaml; ``mm3`` in kpi.yaml).  A length unit
# this table does not name gives a length and an area no symbol at all:
# nothing is guessed.

LENGTH_SYMBOLS = {"MILLIMETERS": "mm", "INCHES": "in"}
ANGLE_SYMBOL = "deg"


def unit_symbols(length_unit: str | None) -> dict[str, str]:
    """``{NX unit kind: symbol}`` for a part whose length unit NX names *length_unit*."""
    symbols = {"Angle": ANGLE_SYMBOL}
    length = LENGTH_SYMBOLS.get(length_unit or "")
    if length:
        symbols["Length"] = length
        symbols["Area"] = length + "2"
    return symbols


def declared_units() -> tuple[tuple[str, str, str], ...]:
    """Every unit the source declares, as ``(name, unit, source)``.

    *source* is ``attributes`` - the unit is an NX unit kind, resolved per
    part by :func:`units` - or ``derived``, ``relations`` or ``thresholds``,
    whose unit is the symbol the source writes.  A null unit is no row.

    An NX attribute is read by its main declaration, the ``unit`` of its
    entry: the one most of the classes that declare it make.  The ones fewer
    classes make are listed under ``otherDeclarations`` and are not consulted.
    Two attributes are declared with two units that way - ANGLE_BOTTOM_CHAMFER
    and ANGLE_TOP_CHAMFER, Angle and, on fewer classes, no unit - and both
    read as Angle.
    """
    rows: list[tuple[str, str, str]] = []
    for name, record in sorted(_classes()["attributes"].items()):
        if record.get("unit"):
            rows.append((name, record["unit"], "attributes"))
    for name, record in sorted(derived_attributes().items()):
        if record.get("unit"):
            rows.append((name, record["unit"], "derived"))
    for _label, entry in sorted(relation_types().items()):
        for prop in entry.get("properties") or ():
            if prop.get("unit"):
                rows.append((prop["name"], prop["unit"], "relations"))
    for symbol, record in sorted(thresholds().items()):
        if record.get("unit"):
            rows.append((symbol, record["unit"], "thresholds"))
    return tuple(rows)


def units(length_unit: str | None) -> dict[str, str]:
    """``{name: unit}`` for one part: every name the source declares a unit for.

    NX attributes are resolved against the part's *length_unit*; derived
    quantities, relation properties and thresholds carry the unit their
    source writes.  A name the source declares with two different units is
    left out rather than given one of them (the tests hold that none is).
    """
    symbols = unit_symbols(length_unit)
    out: dict[str, str] = {}
    clashing: set[str] = set()
    for name, unit, source in declared_units():
        text = symbols.get(unit) if source == "attributes" else unit
        if not text:
            continue
        if out.setdefault(name, text) != text:
            clashing.add(name)
    return {name: text for name, text in sorted(out.items()) if name not in clashing}
