"""Checks on the source and on what was generated from it.

  V1  every class parent is a class in the file; every class attribute is a declared attribute
  V2  the class tree and attribute declarations match the installed customization_base.xml (skipped without NX)
  V3  every threshold a heuristic uses exists; every KPI a heuristic affects exists; every relation type it uses exists
  V4  every heuristic pattern expands to at least one recognisable class
  V5  every condition binds ?outcome and every published value, and parses as part of a SPARQL Update
  V6  every KPI derivation names a declared KPI type and parses
  V7  no CJK characters anywhere under ontology/nx_v1_1, the built page included
  V8  dist/cncgaide_nx.ttl and dist/shapes.ttl parse and dist/rules/ORDER.txt lists existing files
  V9  dist/ is byte for byte what the current source and build scripts produce
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from rdflib import Graph
from rdflib.plugins.sparql.parser import parseUpdate

from common import DIST, HERE, ONTOLOGY, ROOT, RULES, SRC, tbox

GENERATORS = ("gen_tbox.py", "gen_rules.py", "gen_shapes.py", "gen_page.py")

CJK = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in ((0x3400, 0x9FFF), (0xF900, 0xFAFF), (0x3000, 0x303F), (0xFF00, 0xFFEF))) + "]")


def regenerate(target: Path) -> str | None:
    """Run every generator again into ``target``; the failure, or None.

    The generators write wherever CNCGAIDE_DIST says, so a second copy can be
    made without any of them knowing it is being checked.
    """
    env = {**os.environ, "CNCGAIDE_DIST": str(target),
           "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"}
    for step in GENERATORS:
        script = HERE / step
        if not script.is_file():
            continue
        result = subprocess.run([sys.executable, str(script)], cwd=str(ROOT), env=env,
                                capture_output=True, text=True)
        if result.returncode != 0:
            return f"{step} exited with {result.returncode}: {(result.stderr or '').strip()[:300]}"
    return None


def tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def nx_root() -> Path | None:
    sys.path.insert(0, str(SRC))
    import nx_location
    root = nx_location.nx_root()
    return root if (root / "UGII" / "customization_base.xml").is_file() else None


def check() -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    names = set(tbox.class_names())
    attrs = set(tbox.attribute_names())
    for name in names:
        record = tbox.class_record(name)
        if record["parent"] and record["parent"] not in names:
            errors.append(f"V1 {name}: parent {record['parent']} is not a class")
        for attribute in record["attributes"]:
            if attribute not in attrs:
                errors.append(f"V1 {name}: attribute {attribute} is not declared")
    notes.append(f"V1: {len(names)} classes, {len(attrs)} attributes")

    root = nx_root()
    if root is None:
        notes.append("V2: skipped, customization_base.xml is not on this machine")
    else:
        schema = {}
        for _, el in ET.iterparse(str(root / "UGII" / "customization_base.xml"), events=("end",)):
            if el.tag == "Class" and el.get("Package") == "feature":
                parent = el.get("Parent") or ""
                schema[el.get("Name")] = {
                    "parent": parent.split(".", 1)[1] if parent.startswith("feature.") else None,
                    "abstract": el.get("Abstract") == "true",
                    "label": el.get("NiceName") if el.get("NiceName") != el.get("Name") else None,
                    "fields": sorted(f.get("Name") for f in el.iter("Field")),
                }
                el.clear()
        for name in sorted(names):
            record = tbox.class_record(name)
            declared = schema.get(name)
            if declared is None:
                errors.append(f"V2 {name}: not declared in the XML")
                continue
            expected_parent = declared["parent"] if declared["parent"] in schema else None
            if record["parent"] != expected_parent:
                errors.append(f"V2 {name}: parent yaml={record['parent']} xml={expected_parent}")
            if bool(record["abstract"]) != declared["abstract"]:
                errors.append(f"V2 {name}: abstract differs")
            if record.get("label") != declared["label"]:
                errors.append(f"V2 {name}: label yaml={record.get('label')!r} xml={declared['label']!r}")
            if sorted(record["attributes"]) != declared["fields"]:
                errors.append(f"V2 {name}: attributes differ from the XML")
        notes.append(f"V2: {len(names)} classes reconciled with customization_base.xml")

    thresholds = set(tbox.thresholds())
    kpis = set(tbox.kpi_types())
    for kpi_id, record in tbox.kpi_types().items():
        if record.get("worseWhen") not in ("higher", "lower"):
            errors.append(f"V3 {kpi_id}: worseWhen must be higher or lower")
    relations = set(tbox.relation_types())
    for h_id, record in tbox.definitions().items():
        for symbol in record.get("usesThresholds") or []:
            if symbol not in thresholds:
                errors.append(f"V3 {h_id}: threshold {symbol} is not declared")
        for kpi_id in record.get("affectsKpi") or []:
            if kpi_id not in kpis:
                errors.append(f"V3 {h_id}: KPI {kpi_id} is not declared")
        for rel in record.get("usesRelations") or []:
            if rel not in relations:
                errors.append(f"V3 {h_id}: relation {rel} is not declared")
        if record["scope"] == "pair" and record.get("relationType") not in relations:
            errors.append(f"V3 {h_id}: pair rule without a declared relationType")
        for pattern in record.get("appliesTo") or []:
            if not tbox.expand_pattern(pattern):
                errors.append(f"V4 {h_id}: pattern {pattern} matches no recognisable class")
        if not tbox.heuristic_domain(h_id):
            errors.append(f"V4 {h_id}: empty domain after the attribute gate")
        condition = record["condition"]
        if "?outcome" not in condition:
            errors.append(f"V5 {h_id}: condition does not bind ?outcome")
        for value in record.get("values") or []:
            if f"?v_{value}" not in condition:
                errors.append(f"V5 {h_id}: condition does not bind ?v_{value}")
        for symbol in re.findall(r"\?(t_\w+|tol_\w+)", condition):
            if symbol not in (record.get("usesThresholds") or []):
                errors.append(f"V5 {h_id}: condition reads ?{symbol} without declaring it")
        rule_path = RULES / f"{h_id}.ru"
        if rule_path.is_file():
            try:
                parseUpdate(_substitute(rule_path.read_text(encoding="utf-8")))
            except Exception as error:  # noqa: BLE001
                errors.append(f"V5 {h_id}: generated rule does not parse: {str(error)[:200]}")
    notes.append(f"V3-V5: {len(tbox.definitions())} heuristics checked")

    for derivation in tbox.kpi_derivations():
        if derivation["kpiType"] not in kpis:
            errors.append(f"V6 {derivation['id']}: KPI type {derivation['kpiType']} is not declared")
        if not tbox.kpi_derivation_domain(derivation):
            errors.append(f"V6 {derivation['id']}: empty domain")
        rule_path = RULES / f"{derivation['id']}.ru"
        if rule_path.is_file():
            try:
                parseUpdate(_substitute(rule_path.read_text(encoding="utf-8")))
            except Exception as error:  # noqa: BLE001
                errors.append(f"V6 {derivation['id']}: generated rule does not parse: {str(error)[:200]}")
    for gate in ("gate_feature", "gate_pair"):
        path = RULES / f"{gate}.ru"
        if path.is_file():
            try:
                parseUpdate(_substitute(path.read_text(encoding="utf-8")))
            except Exception as error:  # noqa: BLE001
                errors.append(f"V6 {gate}: does not parse: {str(error)[:200]}")
    notes.append(f"V6: {len(tbox.kpi_derivations())} KPI derivations checked")

    hits = 0
    for path in ONTOLOGY.rglob("*"):
        if path.is_file() and path.suffix in (".yaml", ".ttl", ".ru", ".py", ".md", ".txt", ".html"):
            hits += len(CJK.findall(path.read_text(encoding="utf-8", errors="ignore")))
    if hits:
        errors.append(f"V7 {hits} CJK character(s) under ontology/nx_v1_1")
    notes.append("V7: no CJK characters")

    for name in ("cncgaide_nx.ttl", "shapes.ttl"):
        path = DIST / name
        if not path.is_file():
            errors.append(f"V8 dist/{name} is missing")
            continue
        try:
            Graph().parse(str(path), format="turtle")
        except Exception as error:  # noqa: BLE001
            errors.append(f"V8 dist/{name} does not parse: {str(error)[:200]}")
    order = RULES / "ORDER.txt"
    if order.is_file():
        for line in order.read_text(encoding="utf-8").split():
            if not (RULES / f"{line}.ru").is_file():
                errors.append(f"V8 rules/ORDER.txt names a missing file {line}")
    else:
        errors.append("V8 rules/ORDER.txt is missing")
    notes.append("V8: dist parses")

    with tempfile.TemporaryDirectory(prefix="cncgaide-dist-") as temporary:
        target = Path(temporary)
        failure = regenerate(target)
        if failure:
            errors.append(f"V9 the build could not be run a second time: {failure}")
        else:
            here, again = tree(DIST), tree(target)
            for name in sorted(set(here) | set(again)):
                if name not in again:
                    errors.append(f"V9 dist/{name} is not produced by the build; it is left over")
                elif name not in here:
                    errors.append(f"V9 dist/{name} is missing from dist")
                elif here[name] != again[name]:
                    errors.append(f"V9 dist/{name} is not what the build produces")
            notes.append(f"V9: {len(here)} generated file(s) reproduce byte for byte")
    return errors, notes


def _substitute(text: str) -> str:
    return (text.replace("{ONTOLOGY}", "urn:x-check:ontology")
                .replace("{FACTS}", "urn:x-check:facts")
                .replace("{OUT}", "urn:x-check:out"))


def main() -> None:
    errors, notes = check()
    report = ["# Validation report", ""]
    report += [f"- {note}" for note in notes]
    if errors:
        report += ["", "## Errors", ""] + [f"- {error}" for error in errors]
    (ONTOLOGY / "docs").mkdir(exist_ok=True)
    (ONTOLOGY / "docs" / "validation_report.md").write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    for note in notes:
        print("ok  ", note)
    for error in errors:
        print("FAIL", error)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
