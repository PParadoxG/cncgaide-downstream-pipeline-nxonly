"""Transcribe the installed NX feature schema into classes.yaml and attributes.yaml.

    python ontology/nx_v1_1/build/bootstrap_from_nx.py --nx-root E:/NX2506

Inputs, all read-only:

* ``<nx-root>/UGII/customization_base.xml`` - every ``Package="feature"`` class:
  name, parent, abstract flag, display name (NiceName) and the declared fields
  with DataType / Unit / SubType.
* ``<nx-root>/MACH/resource/machining_knowledge/machining_knowledge.xml`` - the
  recognition rules; a class is a rule target when a ``<FeatureClass>`` element
  names it.
* ``source/recognition_scope.yaml`` - what ``GetRegisteredFeatureTypes()``
  answers under the cam_general configuration.  It is an API answer recorded
  by a journal probe; no file NX ships contains it.
* ``build/runtime_unreadable.yaml`` - attribute names CAMFeature.Attributes
  enumerates on recognised features without declaring them in the schema and
  without handing over a value.

Scope: a class is in scope when it is registered and named by a recognition
rule; its ancestors inside the feature package are included so the tree stays
connected.  Every name, unit, parent and label is copied, none is invented.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "source"
sys.path.insert(0, str(HERE.parents[2] / "src" / "nxline" / "vendor"))
import yaml  # noqa: E402

# Attributes present on every recognised feature and declared by no schema
# class: name -> (dataType, unit).  Enumerated by CAMFeature.Attributes.
RUNTIME_ATTRIBUTES = {
    "X_POSITION": ("Double", "Length"),
    "Y_POSITION": ("Double", "Length"),
    "Z_POSITION": ("Double", "Length"),
    "X_ORIENTATION_D": ("Double", None),
    "Y_ORIENTATION_D": ("Double", None),
    "Z_ORIENTATION_D": ("Double", None),
    "X_ORIENTATION_L": ("Double", None),
    "Y_ORIENTATION_L": ("Double", None),
    "Z_ORIENTATION_L": ("Double", None),
    "SUBTYPE": ("Integer", None),
    "ISRECOGNIZEDFEATURE": ("Integer", None),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_schema(path: Path) -> dict:
    out: dict[str, dict] = {}
    for _, el in ET.iterparse(str(path), events=("end",)):
        if el.tag != "Class":
            continue
        if el.get("Package") != "feature":
            el.clear()
            continue
        parent = el.get("Parent") or ""
        fields = {}
        for f in el.iter("Field"):
            fields[f.get("Name")] = (f.get("DataType"), f.get("Unit"), f.get("SubType"))
        out[el.get("Name")] = {
            "parent": parent.split(".", 1)[1] if parent.startswith("feature.") else (parent or None),
            "abstract": el.get("Abstract") == "true",
            "label": el.get("NiceName") if el.get("NiceName") != el.get("Name") else None,
            "fields": fields,
        }
        el.clear()
    return out


def rule_targets(path: Path) -> set:
    out = set()
    for _, el in ET.iterparse(str(path), events=("end",)):
        if el.tag == "FeatureClass":
            value = (el.text or "").strip()
            out.add(value.split(".", 1)[1] if value.startswith("feature.") else value)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nx-root", required=True)
    ap.add_argument("--registered", default=str(SOURCE / "recognition_scope.yaml"))
    ap.add_argument("--runtime-unreadable", default=str(HERE / "runtime_unreadable.yaml"))
    args = ap.parse_args()
    root = Path(args.nx_root)
    schema_xml = root / "UGII" / "customization_base.xml"
    rules_xml = root / "MACH" / "resource" / "machining_knowledge" / "machining_knowledge.xml"
    schema = extract_schema(schema_xml)
    targets = rule_targets(rules_xml)
    registered = set(yaml.safe_load(Path(args.registered).read_text(encoding="utf-8"))["registeredTypes"])
    recognisable = sorted(registered & targets & set(schema))

    in_scope: set[str] = set()
    for name in recognisable:
        cursor = name
        while cursor and cursor in schema and cursor not in in_scope:
            in_scope.add(cursor)
            cursor = schema[cursor]["parent"]
    root_parent = None
    for name in in_scope:
        p = schema[name]["parent"]
        if p is not None and p not in schema:
            root_parent = p

    classes = []
    for name in sorted(in_scope):
        c = schema[name]
        parent = c["parent"] if c["parent"] in schema else None
        entry = {"name": name, "parent": parent, "abstract": c["abstract"],
                 "recognisable": name in recognisable}
        if c["label"]:
            entry["label"] = c["label"]
        entry["attributes"] = sorted(c["fields"])
        classes.append(entry)

    specs: dict[str, dict[tuple, int]] = {}
    for name in in_scope:
        for field, spec in schema[name]["fields"].items():
            specs.setdefault(field, {}).setdefault(spec, 0)
            specs[field][spec] += 1
    attributes = []
    for field in sorted(specs):
        ranked = sorted(specs[field].items(), key=lambda kv: (-kv[1], str(kv[0])))
        data_type, unit, sub_type = ranked[0][0]
        entry = {"name": field, "dataType": data_type, "unit": unit, "subType": sub_type,
                 "declaredIn": "schema", "apiReadable": data_type not in ("Face", "Class")}
        if len(ranked) > 1:
            entry["otherDeclarations"] = [
                {"dataType": s[0], "unit": s[1], "subType": s[2]} for s, _ in ranked[1:]]
        attributes.append(entry)
    for name, (data_type, unit) in sorted(RUNTIME_ATTRIBUTES.items()):
        attributes.append({"name": name, "dataType": data_type, "unit": unit, "subType": None,
                           "declaredIn": "runtime", "apiReadable": True, "declaredOn": "root"})
    unreadable_path = Path(args.runtime_unreadable)
    unreadable = yaml.safe_load(unreadable_path.read_text(encoding="utf-8")) if unreadable_path.exists() else {}
    for name, spec in sorted((unreadable or {}).items()):
        attributes.append({"name": name, "dataType": spec.get("dataType"), "unit": None,
                           "subType": None, "declaredIn": "runtime", "apiReadable": False,
                           "declaredOn": spec.get("declaredOn", "root")})
    attributes.sort(key=lambda a: a["name"])

    head = {
        "source": [
            {"path": "UGII/customization_base.xml", "bytes": schema_xml.stat().st_size,
             "sha256": sha256(schema_xml)},
            {"path": "MACH/resource/machining_knowledge/machining_knowledge.xml",
             "bytes": rules_xml.stat().st_size, "sha256": sha256(rules_xml)},
        ],
        "rootParent": root_parent,
        "counts": {"declaredInSchema": len(schema), "registered": len(registered),
                   "recognisable": len(recognisable), "classes": len(classes)},
    }
    dump = dict(sort_keys=False, allow_unicode=False, width=110)
    (SOURCE / "classes.yaml").write_text(
        yaml.safe_dump({"head": head, "classes": classes}, **dump), encoding="utf-8", newline="\n")
    (SOURCE / "attributes.yaml").write_text(
        yaml.safe_dump({"head": {"source": head["source"][:1],
                                 "counts": {"schema": len(specs),
                                            "runtime": len(attributes) - len(specs)}},
                        "attributes": attributes}, **dump), encoding="utf-8", newline="\n")
    print(f"classes {len(classes)} (recognisable {len(recognisable)}), attributes {len(attributes)}")


if __name__ == "__main__":
    main()
