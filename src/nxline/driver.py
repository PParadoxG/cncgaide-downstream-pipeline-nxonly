"""CPython driver for the NX journal: one NX session, many parts.

Translates the requested STEP files (cached by content under ``runs/prt``),
then runs ``journal.py`` once under ``run_journal.exe`` with every part in a
single job file.  It writes facts files and hands back per-part summaries;
loading the store and updating the index is the sync layer's job.

An unreachable licence comes back as ``blocked``: a statement about the
environment, never about a part.  Every summary read back must carry this
run's token, so a stale file can never stand in for an answer.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

from nxline import config
from nxline.config import looks_like_license_failure, nx_available
from nxline.translate import sweep_cache, translate

_JOURNAL = Path(__file__).resolve().parent / "journal.py"


def prt_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "runs" / "prt"


def run_nx_line(project_root: str | Path, jobs: list[dict], *, timeout: float = 3600.0) -> dict:
    """Build facts for *jobs* in one session.

    *jobs* is ``[{"partId", "stepPath", "sourceStep", "sourceSha256", "factsPath",
    "factsGraph", "factsKey", "meshDir"}]``.
    Returns ``{"status": "ok" | "blocked" | "error" | "nothing_to_run", "detail",
    "parts": {partId: summary}}``.
    """
    root = Path(project_root).resolve()
    outcome: dict = {"status": "ok", "detail": "", "parts": {}}
    if not nx_available():
        outcome["status"] = "blocked"
        outcome["detail"] = f"NX install not found under {config.NX_ROOT}"
        return outcome

    work = prt_dir(root)
    work.mkdir(parents=True, exist_ok=True)
    run_token = uuid.uuid4().hex
    journal_jobs = []
    for job in jobs:
        part_id = job["partId"]
        step_path = Path(job["stepPath"])
        translated = translate(step_path, work, part_id, source_label=job.get("sourceStep") or step_path.name)
        if translated["status"] == "blocked":
            outcome["status"] = "blocked"
            outcome["detail"] = translated["detail"]
            outcome["parts"][part_id] = {"status": "blocked", "error": translated["detail"]}
            return outcome
        if translated["status"] in ("ok", "cached"):
            journal_jobs.append({
                "partId": part_id,
                "prt": translated["prt"],
                "factsPath": str(job["factsPath"]),
                "factsGraph": job["factsGraph"],
                "factsKey": job["factsKey"],
                "sourceStep": job.get("sourceStep") or step_path.name,
                "sourceSha256": job.get("sourceSha256"),
                "meshDir": job.get("meshDir"),
                "summary": str(work / f"{part_id}.summary.json"),
                "runToken": run_token,
            })
        else:
            outcome["parts"][part_id] = {"status": translated["status"], "error": translated["detail"]}

    outcome["translationCache"] = sweep_cache(work, {job["partId"] for job in jobs})
    if not journal_jobs:
        outcome["status"] = "nothing_to_run"
        return outcome
    for job in journal_jobs:
        Path(job["summary"]).unlink(missing_ok=True)

    jobfile = {"projectRoot": str(root), "runToken": run_token, "parts": journal_jobs}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(jobfile, handle)
        jobfile_path = handle.name
    try:
        environment = dict(os.environ, CNCGAIDE_NX_JOB=jobfile_path)
        completed = subprocess.run(
            [str(config.RUN_JOURNAL), str(_JOURNAL)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=environment,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
    except subprocess.TimeoutExpired:
        detail = f"the NX session timed out after {timeout}s and was killed"
        outcome["status"] = "error"
        outcome["detail"] = detail
        for job in journal_jobs:
            outcome["parts"][job["partId"]] = {"status": "error", "error": detail}
        return outcome
    finally:
        try:
            os.unlink(jobfile_path)
        except OSError:
            pass

    outcome["journalTail"] = output.strip()[-600:]
    if looks_like_license_failure(output):
        outcome["status"] = "blocked"
        outcome["detail"] = output.strip()[-400:]
        return outcome

    for job in journal_jobs:
        part_id = job["partId"]
        path = Path(job["summary"])
        summary = None
        if path.is_file():
            try:
                summary = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                outcome["parts"][part_id] = {"status": "error", "error": f"unreadable summary: {error}"}
                continue
        if not isinstance(summary, dict) or summary.get("runToken") != run_token:
            outcome["parts"][part_id] = {
                "status": "error",
                "error": "the journal wrote no summary for this run; tail: " + output.strip()[-300:],
            }
            continue
        outcome["parts"][part_id] = summary
    return outcome
