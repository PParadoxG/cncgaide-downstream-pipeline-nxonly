"""Start, stop and locate the Fuseki server.

The distribution is unpacked under ``install/fuseki/`` by
``install/fuseki_install.py``; the TDB2 database lives under ``runs/tdb2``.
The service configuration is generated at start time so the database path
is always this checkout's.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from kg.fuseki import Fuseki

FUSEKI_DIR_GLOB = "apache-jena-fuseki-*"
PORT = 3030
DATASET = "nx"

CONFIG_TEMPLATE = """PREFIX :        <#>
PREFIX fuseki:  <http://jena.apache.org/fuseki#>
PREFIX rdf:     <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs:    <http://www.w3.org/2000/01/rdf-schema#>
PREFIX tdb2:    <http://jena.apache.org/2016/tdb#>
PREFIX ja:      <http://jena.hpl.hp.com/2005/11/Assembler#>

[] rdf:type fuseki:Server ;
   fuseki:services ( :service ) .

:service rdf:type fuseki:Service ;
    fuseki:name "{dataset}" ;
    fuseki:endpoint [ fuseki:operation fuseki:query ] ;
    fuseki:endpoint [ fuseki:operation fuseki:query ;  fuseki:name "query" ] ;
    fuseki:endpoint [ fuseki:operation fuseki:update ; fuseki:name "update" ] ;
    fuseki:endpoint [ fuseki:operation fuseki:gsp-rw ; fuseki:name "data" ] ;
    fuseki:endpoint [ fuseki:operation fuseki:shacl ;  fuseki:name "shacl" ] ;
    fuseki:dataset :dataset .

:dataset rdf:type tdb2:DatasetTDB2 ;
    tdb2:location "{location}" .
"""


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def fuseki_home(root: Path | None = None) -> Path | None:
    root = root or project_root()
    override = os.environ.get("CNCGAIDE_FUSEKI_HOME")
    if override and (Path(override) / "fuseki-server.jar").is_file():
        return Path(override)
    candidates = sorted((root / "install" / "fuseki").glob(FUSEKI_DIR_GLOB))
    for candidate in reversed(candidates):
        if (candidate / "fuseki-server.jar").is_file():
            return candidate
    return None


JDK_GLOBS = (
    r"C:/Program Files/Microsoft/jdk-*",
    r"C:/Program Files/Eclipse Adoptium/jdk-*",
    r"C:/Program Files/Java/jdk-*",
    r"C:/Program Files/Zulu/zulu-*",
    r"C:/Program Files/Amazon Corretto/jdk*",
)


def java_executable() -> str | None:
    """A Java 21+ executable: CNCGAIDE_JAVA, JAVA_HOME, the usual Windows JDK
    folders (newest first), then whatever ``java`` is on the PATH."""
    exe = "java.exe" if os.name == "nt" else "java"
    override = os.environ.get("CNCGAIDE_JAVA")
    if override and Path(override).is_file():
        return override
    candidates: list[str] = []
    home = os.environ.get("JAVA_HOME")
    if home and (Path(home) / "bin" / exe).is_file():
        candidates.append(str(Path(home) / "bin" / exe))
    if os.name == "nt":
        found = []
        for pattern in JDK_GLOBS:
            base = Path(pattern).parent
            if base.is_dir():
                found += [p for p in base.glob(Path(pattern).name) if (p / "bin" / exe).is_file()]
        candidates += [str(p / "bin" / exe) for p in sorted(found, key=lambda p: p.name, reverse=True)]
    on_path = shutil.which("java")
    if on_path:
        candidates.append(on_path)
    for candidate in candidates:
        major = java_major_version(candidate)
        if major is not None and major >= 21:
            return candidate
    return candidates[0] if candidates else None


def java_major_version(java: str) -> int | None:
    try:
        out = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stderr or "") + (out.stdout or "")
    for token in text.replace('"', " ").split():
        head = token.split(".")[0]
        if head.isdigit():
            major = int(head)
            if major == 1 and "." in token:
                return int(token.split(".")[1])
            return major
    return None


def runs_dir(root: Path | None = None) -> Path:
    return (root or project_root()) / "runs"


def write_config(root: Path | None = None) -> Path:
    root = root or project_root()
    location = (runs_dir(root) / "tdb2").resolve()
    location.mkdir(parents=True, exist_ok=True)
    config_dir = runs_dir(root) / "fuseki"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = config_dir / "config.ttl"
    config.write_text(CONFIG_TEMPLATE.format(dataset=DATASET, location=location.as_posix()),
                      encoding="utf-8", newline="\n")
    return config


def pid_file(root: Path | None = None) -> Path:
    return runs_dir(root) / "fuseki" / "fuseki.pid"


def client(port: int = PORT) -> Fuseki:
    return Fuseki(base=f"http://localhost:{port}", dataset=DATASET)


def status(root: Path | None = None, port: int = PORT) -> dict:
    home = fuseki_home(root)
    java = java_executable()
    return {
        "fusekiHome": str(home) if home else None,
        "java": java,
        "javaMajor": java_major_version(java) if java else None,
        "running": client(port).ping(),
        "pid": pid_file(root).read_text().strip() if pid_file(root).is_file() else None,
        "endpoint": f"http://localhost:{port}/{DATASET}",
    }


def start(root: Path | None = None, port: int = PORT, *, wait: float = 60.0) -> dict:
    root = root or project_root()
    if client(port).ping():
        return {"started": False, "reason": "already running", **status(root, port)}
    home = fuseki_home(root)
    if home is None:
        raise RuntimeError("Fuseki is not installed under install/fuseki; run install/fuseki_install.py")
    java = java_executable()
    if java is None:
        raise RuntimeError("no java executable found; install a JDK 21 or set JAVA_HOME")
    major = java_major_version(java)
    if major is not None and major < 21:
        raise RuntimeError(f"java {major} found; Fuseki 6 needs Java 21 or later")
    config = write_config(root)
    log_dir = runs_dir(root) / "fuseki"
    log = open(log_dir / "fuseki.log", "a", encoding="utf-8")
    creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [java, "-Xmx2g", "-jar", str(home / "fuseki-server.jar"), "--config", str(config), "--port", str(port)],
        cwd=str(home), stdout=log, stderr=subprocess.STDOUT, creationflags=creation,
        env={**os.environ, "FUSEKI_BASE": str((log_dir / "base").resolve())},
    )
    pid_file(root).write_text(str(process.pid), encoding="utf-8")
    deadline = time.time() + wait
    while time.time() < deadline:
        if client(port).ping():
            return {"started": True, "pid": process.pid, **status(root, port)}
        if process.poll() is not None:
            raise RuntimeError(f"Fuseki exited with code {process.returncode}; see {log_dir / 'fuseki.log'}")
        time.sleep(0.5)
    raise RuntimeError(f"Fuseki did not answer on port {port} within {wait}s; see {log_dir / 'fuseki.log'}")


def stop(root: Path | None = None) -> dict:
    root = root or project_root()
    path = pid_file(root)
    if not path.is_file():
        return {"stopped": False, "reason": "no pid file"}
    pid = path.read_text().strip()
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(int(pid), 15)
        except ProcessLookupError:
            pass
    path.unlink(missing_ok=True)
    return {"stopped": True, "pid": pid}


def ensure_running(root: Path | None = None, port: int = PORT) -> Fuseki:
    c = client(port)
    if not c.ping():
        start(root, port)
    return c


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    print({"start": start, "stop": stop}.get(action, status)())
