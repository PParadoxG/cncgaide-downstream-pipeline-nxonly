"""The NX journal: one session, many parts, facts out as TriG.

Runs under ``run_journal.exe``.  For each part: open the translated ``.prt``,
fill the PartModel from the NX kernel, run NX's own feature recognition
(one Parametric round, the Find Features dialog's factory defaults), project
NX's answer onto feature nodes, measure the derived quantities and the
relations while the kernel is alive, and write everything as one named
graph in a TriG file.  Nothing else is written besides the per-part summary
the driver reads back.

Job file (env ``CNCGAIDE_NX_JOB``)::

    {"projectRoot": ..., "runToken": ...,
     "parts": [{"partId", "prt", "factsPath", "factsGraph", "factsKey",
                "sourceStep", "sourceSha256", "summary", "meshDir"}]}

``run_journal.exe`` ignores PYTHONPATH, so this file wires ``src`` and the
vendored pure-python yaml from its own location.  The import hook below makes
sure the open-source CAD kernel is never imported here: NX is the only
geometry in this process.
"""

import json
import os
import sys
import traceback


class _NoOcc:
    def find_spec(self, name, path=None, target=None):
        if name == "OCC" or name.startswith("OCC."):
            raise ImportError("the NX journal forbids importing " + name)
        return None


sys.meta_path.insert(0, _NoOcc())

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "vendor"))
sys.path.insert(0, os.path.dirname(_HERE))

import NXOpen  # noqa: E402
import NXOpen.CAM  # noqa: E402
import NXOpen.UF  # noqa: E402


def process_part(session, uf, job, first_part, environment):
    from collections import Counter

    from contract import refusals
    from kg import facts
    from nxline import derive, journal_native, native
    from nxline.kernel import NxKernelServices
    from nxline.partmodel import build_partmodel
    from relations import run_relations
    from relations.nx.registry import NxRelationRegistry

    part_id = job["partId"]
    summary = {"partId": part_id, "status": "success", "runToken": job.get("runToken")}
    work = None
    try:
        part, _ = session.Parts.OpenActiveDisplay(job["prt"], NXOpen.DisplayPartOption.AllowAdditional)
        work = session.Parts.Work
        if first_part:
            session.CreateCamSession()
            try:
                session.CAMSession.SpecifyConfiguration("${UGII_CAM_CONFIG_DIR}cam_general")
            except Exception as error:  # noqa: BLE001
                summary["camConfigurationProblem"] = "%s: %s" % (type(error).__name__, error)
        bodies = [b for b in work.Bodies]
        solids = [candidate for candidate in bodies if candidate.IsSolidBody]
        if len(solids) > 1:
            summary["status"] = "error"
            summary["error"] = refusals.multi_body_unsupported(len(solids))
            summary["bodyCount"] = len(solids)
            return summary
        body = solids[0] if solids else bodies[0]

        model, cad_faces = build_partmodel(
            uf, work, body,
            source_file=os.path.basename(job.get("sourceStep", job["prt"])),
            part_name=part_id,
            part_units_enum=getattr(NXOpen.BasePart, "Units", None))
        face_id_by_tag = {face.Tag: "face_%d" % index for index, face in enumerate(cad_faces)}

        raw = journal_native.extract(work, bodies, environment)
        nodes, diagnostics = native.project(part_id, raw, face_id_by_tag, model=model)
        kernel = NxKernelServices(uf, work, body, cad_faces, model)
        derived_summary = derive.derive_nodes(model, nodes, kernel)
        edges, relation_diagnostics = run_relations(model, nodes, kernel=kernel, registry=NxRelationRegistry)

        triples = facts.build(
            part_id, model, nodes, edges, diagnostics,
            relation_diagnostics=relation_diagnostics, derived_summary=derived_summary,
            source={"sourceStep": job.get("sourceStep"), "sourceSha256": job.get("sourceSha256"),
                    "factsKey": job.get("factsKey"), "factsGraph": job.get("factsGraph")})
        count = facts.write_trig(job["factsPath"], job["factsGraph"], triples)

        mesh_dir = job.get("meshDir")
        if mesh_dir:
            try:
                from nxline.mesh import write_mesh
                summary["mesh"] = write_mesh(mesh_dir, part_id, kernel, model, nodes)
            except ImportError:
                summary["mesh"] = None

        claimed = {face_id for node in nodes for face_id in node.partmodelFaceIds}
        summary["entry"] = {
            "partId": part_id,
            "sourceStep": job.get("sourceStep"),
            "faceCount": len(model.faces),
            "claimedFaceCount": len(claimed),
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "tripleCount": count,
            "featureCounts": dict(sorted(Counter(node.featureType for node in nodes).items())),
            "relationCounts": relation_diagnostics["relationCounts"],
            "derived": derived_summary,
        }
    except Exception:  # noqa: BLE001
        summary["status"] = "error"
        summary["error"] = traceback.format_exc()[-2000:]
    finally:
        try:
            if work is not None:
                work.Close(NXOpen.BasePartCloseWholeTree.TrueValue,
                           NXOpen.BasePartCloseModified.CloseModified, None)
        except Exception:  # noqa: BLE001
            pass
    summary["occModules"] = sorted(name for name in sys.modules if name == "OCC" or name.startswith("OCC."))
    return summary


def describe_environment(session=None):
    environment = {
        "ugiiLang": _nx_environment(session, "UGII_LANG") or os.environ.get("UGII_LANG") or "",
        "nxVersion": _nx_environment(session, "UGII_VERSION") or "",
        "nxReleaseNumber": "",
    }
    if session is not None:
        try:
            environment["nxReleaseNumber"] = str(session.ReleaseNumber or "")
        except Exception as error:  # noqa: BLE001
            environment["nxReleaseNumberError"] = "%s: %s" % (type(error).__name__, error)
    return environment


def _nx_environment(session, name):
    if session is None:
        return ""
    try:
        return str(session.GetEnvironmentVariableValue(name) or "")
    except Exception:  # noqa: BLE001
        return ""


def main():
    with open(os.environ["CNCGAIDE_NX_JOB"], "r", encoding="utf-8") as handle:
        jobfile = json.load(handle)
    session = NXOpen.Session.GetSession()
    uf = NXOpen.UF.UFSession.GetUFSession()
    environment = describe_environment(session)
    for index, job in enumerate(jobfile["parts"]):
        print("[%d/%d] %s" % (index + 1, len(jobfile["parts"]), job["partId"]))
        summary = process_part(session, uf, job, index == 0, environment)
        out_path = job["summary"]
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        try:
            payload = json.dumps(summary, indent=1, ensure_ascii=False)
        except (TypeError, ValueError) as error:
            summary = {"partId": job["partId"], "status": "error", "runToken": job.get("runToken"),
                       "error": "the summary could not be serialised: %s: %s" % (type(error).__name__, error)}
            payload = json.dumps(summary, indent=1, ensure_ascii=False)
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(payload)
        print("  ->", summary["status"])
    print("journal done")


if __name__ == "__main__":
    main()
