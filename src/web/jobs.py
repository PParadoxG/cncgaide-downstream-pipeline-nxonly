"""One background job at a time, run as a subprocess.

A sync opens an NX session and holds a licence, so two of them at once is
not a slow answer but a broken one: the queue here is length-limited to
exactly that - one running job, the rest waiting.  The work runs in a child
process rather than in a thread, so a job that has to be abandoned can be
killed: ``python run.py sync ...`` for the whole input directory, the same
command a terminal would use, and ``python -m web.syncjob ...`` for the two
things that verb cannot say - rebuild these parts, remove this part.
"""

from __future__ import annotations

import itertools
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_LOG_LINES = 400

PART_ID = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
STEP_NAME = re.compile(r"^[A-Za-z0-9._-]{1,120}\.(step|stp|STEP|STP)$")


def valid_part_id(value) -> bool:
    return bool(value and isinstance(value, str) and PART_ID.match(value) and ".." not in value)


def valid_step_name(value) -> bool:
    return bool(value and isinstance(value, str) and STEP_NAME.match(value) and ".." not in value)


class Job:
    _ids = itertools.count(1)

    def __init__(self, kind: str, arguments: dict) -> None:
        self.jobId = f"job-{next(self._ids)}"
        self.kind = kind
        self.arguments = dict(arguments)
        self.state = "queued"
        self.queuedAt = time.time()
        self.startedAt = None
        self.finishedAt = None
        self.exitCode = None
        self.log: deque[str] = deque(maxlen=MAX_LOG_LINES)

    def describe(self) -> dict:
        return {
            "jobId": self.jobId, "kind": self.kind, "arguments": self.arguments,
            "state": self.state, "queuedAt": self.queuedAt, "startedAt": self.startedAt,
            "finishedAt": self.finishedAt, "exitCode": self.exitCode, "log": list(self.log),
        }


class JobRunner:
    """The queue, the worker thread and the child process."""

    def __init__(self, root: Path, input_path: str = "inputs") -> None:
        self.root = Path(root).resolve()
        self.input_path = input_path
        self._lock = threading.Lock()
        self._queue: deque[Job] = deque()
        self._recent: deque[Job] = deque(maxlen=20)
        self._current: Job | None = None
        self._process: subprocess.Popen | None = None
        self._worker: threading.Thread | None = None

    # ------------------------------------------------------------- submitting

    def submit(self, kind: str, arguments: dict) -> Job:
        job = Job(kind, arguments)
        with self._lock:
            self._queue.append(job)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, daemon=True)
                self._worker.start()
        return job

    @property
    def running(self) -> bool:
        with self._lock:
            return self._current is not None

    def status(self) -> dict:
        """The queue, plus the three words the page's poller reads first.

        ``state`` is ``running`` while a job runs and ``idle`` otherwise;
        ``exitCode`` and ``log`` are the running job's, or the last finished
        one's when nothing runs.
        """
        with self._lock:
            current = self._current.describe() if self._current else None
            recent = [job.describe() for job in reversed(self._recent)]
            last = current or (recent[0] if recent else None)
            return {
                "state": "running" if current else "idle",
                "exitCode": None if current or not last else last["exitCode"],
                "log": (last or {}).get("log", [])[-12:],
                "current": current,
                "queue": [job.describe() for job in self._queue],
                "recent": recent,
            }

    def job_for(self, part_id: str) -> dict | None:
        """The first running or waiting job that touches this part, if any."""
        with self._lock:
            pending = ([self._current] if self._current else []) + list(self._queue)
        for job in pending:
            arguments = job.arguments
            # ``touches`` is what the planner said a directory-wide sync would
            # change when it was queued; a named-parts sync touches its parts.
            parts = arguments.get("parts") or arguments.get("touches") or []
            if (job.kind == "remove" and arguments.get("partId") == part_id)                     or (job.kind == "sync" and not arguments.get("dryRun") and part_id in parts):
                return {"jobId": job.jobId, "kind": job.kind, "state": job.state,
                        "arguments": dict(arguments)}
        return None

    # --------------------------------------------------------------- running

    def _command(self, job: Job) -> list[str]:
        arguments = job.arguments
        if job.kind == "remove":
            command = [sys.executable, "-m", "web.syncjob", "remove", "--part", arguments["partId"]]
            if arguments.get("deleteSource"):
                command.append("--delete-source")
            return command + ["--input", self.input_path]
        parts = arguments.get("parts") or []
        if parts:
            command = [sys.executable, "-m", "web.syncjob", "sync", "--parts", *parts,
                       "--input", self.input_path]
        else:
            command = [sys.executable, str(self.root / "run.py"), "sync", "--input", self.input_path]
        if arguments.get("all"):
            command.append("--all")
        if arguments.get("dryRun"):
            command.append("--dry-run")
        return command

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._current = None
                    return
                job = self._queue.popleft()
                self._current = job
            self._run(job)
            with self._lock:
                self._current = None
                self._recent.append(job)

    def _run(self, job: Job) -> None:
        job.state = "running"
        job.startedAt = time.time()
        environment = dict(os.environ)
        environment["PYTHONUNBUFFERED"] = "1"
        # ``-m web.syncjob`` needs the source tree on the path before it runs.
        environment["PYTHONPATH"] = os.pathsep.join(
            [str(self.root / "src"), str(self.root / "src" / "nxline" / "vendor")]
            + ([environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else []))
        try:
            process = subprocess.Popen(
                self._command(job), cwd=str(self.root), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                env=environment)
        except OSError as error:
            job.state = "failed"
            job.exitCode = -1
            job.log.append(f"could not start: {error}")
            job.finishedAt = time.time()
            return
        with self._lock:
            self._process = process
        selected = set(job.arguments.get("parts") or [])
        for line in process.stdout:
            line = line.rstrip()
            if selected and _names_another_part(line, selected):
                continue
            job.log.append(line)
        process.wait()
        with self._lock:
            self._process = None
        job.exitCode = process.returncode
        job.state = "done" if process.returncode == 0 else "failed"
        job.finishedAt = time.time()

    def stop(self, timeout: float = 20.0) -> bool:
        with self._lock:
            process = self._process
        if process is None:
            return True
        process.terminate()
        try:
            process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            process.kill()
            return False


def _names_another_part(line: str, selected: set[str]) -> bool:
    """A plan line about a part this job did not ask for.

    ``sync`` prints one line per part before it does anything, which is the
    whole store; a job the page started for one upload should not report the
    other fifty-six.  Only those plan lines are dropped - anything that is
    not one goes through.
    """
    head = line.split(" ", 1)[0]
    return bool(head) and head not in selected and " current " in f" {line} "
