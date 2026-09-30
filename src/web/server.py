"""The local server behind the web interface.

Three mounts and one API, standard library only:

    /                        the page set under ``src/web/static``
    /ontology.html           the ontology's structure page, generated into
                             ``ontology/nx_v1_1/dist`` by the build
    /api/...                 JSON, assembled from the store by ``assemble``
    /api/part/<id>/mesh.*    the tessellation files under ``runs/mesh/<id>``

Every number the page shows is read from the store when it is asked for;
nothing is cached and no result file is read.  The mesh is the exception the
data contract names: it is binary, it is large, and it is written once by the
NX journal.

Read endpoints answer always.  The ones that change something - upload, sync,
remove, the settings and shutdown - run only when the server was started with
the write API on, and only for a request carrying the custom header, which a
cross-origin page cannot set without a preflight this server never answers.

Drafting a query (``POST /api/draft-query``) sends the question to an external
language model (:mod:`web.llm`); it touches neither the store nor a file, but
it spends the owner's API credit, so it accepts a JSON body only - a content
type a cross-origin page cannot send without the same preflight.  The API key
is read from ``settings.json`` (:mod:`web.settings`) and never answered.

A part bundle carries the two content keys the store made it from
(``factsKey``, ``derivedKey``).  The page sends them back on the mesh request
as ``If-Match``; a bundle and a mesh from different builds are refused with
409 rather than drawn together.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import socketserver
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from kg import server as store_server
from web import assemble, llm, settings
from web.jobs import MAX_UPLOAD_BYTES, JobRunner, valid_part_id, valid_step_name

WRITE_HEADER = "X-CNCgAIde-Write"
SHUTDOWN_HEADER = "X-CNCgAIde-Shutdown"
ASSET_ROOT = Path(__file__).resolve().parent / "static"
ASSET_DIRS = ("web", "vendor")
ASSET_PAGE_SUFFIXES = (".html",)
ONTOLOGY_PAGE = ("ontology", "nx_v1_1", "dist", "cncgaide_nx_structure.html")
# The tab icon: the brand's house glyph, answered for the browser's own
# ``/favicon.ico`` request so no page logs a miss.
FAVICON = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
           b'<path d="M2.5 8.2 8 3.2l5.5 5v5.3h-3.6V9.9H6.1v3.6H2.5z" fill="none" stroke="#3355cc" '
           b'stroke-width="1.5" stroke-linejoin="round"/></svg>')
MAX_JSON_BODY_BYTES = 256 * 1024
QUERY_TIMEOUT = 30.0

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".bin": "application/octet-stream",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class BodyTooLarge(ValueError):
    """The request declared more body than the endpoint will read."""


class Request:
    """What a handler may look at.  Built from the HTTP request, or by a test."""

    def __init__(self, method: str, path: str, *, query: dict | None = None,
                 headers: dict | None = None, body: bytes = b"", reader=None,
                 content_length: int | None = None) -> None:
        self.method = method.upper()
        self.path = path
        self.query = dict(query or {})
        self.headers = {str(key).lower(): value for key, value in (headers or {}).items()}
        self._body = body
        self._reader = reader
        self.content_length = len(body) if content_length is None else int(content_length)

    def header(self, name: str, default=None):
        return self.headers.get(name.lower(), default)

    def read(self, size: int) -> bytes:
        if self._reader is not None:
            return self._reader(size)
        chunk, self._body = self._body[:size], self._body[size:]
        return chunk

    def json(self, max_bytes: int = MAX_JSON_BODY_BYTES) -> dict:
        if self.content_length <= 0:
            return {}
        if self.content_length > max_bytes:
            raise BodyTooLarge(f"body larger than {max_bytes} bytes")
        raw = self.read(self.content_length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            raise ValueError("body is not valid JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("body must be a JSON object")
        return payload


# ---------------------------------------------------------------------- api

class Api:
    """The handlers.  Each answers ``(status code, payload)``."""

    def __init__(self, root: Path, *, input_path: str = "inputs",
                 runner: JobRunner | None = None, presence=None) -> None:
        self.root = Path(root).resolve()
        self.input_path = input_path
        self.runner = runner
        self.presence = presence
        self._client = None
        self._client_lock = threading.Lock()
        self._similarity = None
        self._similarity_lock = threading.Lock()

    # -- the store ----------------------------------------------------------

    @property
    def input_dir(self) -> Path:
        candidate = Path(self.input_path)
        return candidate if candidate.is_absolute() else self.root / self.input_path

    def client(self):
        with self._client_lock:
            if self._client is None:
                self._client = store_server.client()
            return self._client

    def _store(self, call):
        """Run one read against the store, naming a store that is not there."""
        from kg.fuseki import StoreError

        client = self.client()
        try:
            return 200, call(client)
        except assemble.PartNotFound as error:
            return 404, {"error": str(error)}
        except assemble.OntologyNotLoaded as error:
            return 409, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}
        except StoreError as error:
            if not client.ping():
                return 503, {"error": "the store is not answering; start it with: python run.py fuseki start"}
            return 502, {"error": str(error)[:2000]}
        except Exception as error:  # noqa: BLE001 - the text, never the traceback
            return 500, {"error": f"{type(error).__name__}: {error}"}

    # -- reads --------------------------------------------------------------

    def status(self, request: Request) -> tuple[int, dict]:
        client = self.client()
        running = client.ping()
        state = ({"current": None, "queue": [], "recent": [], "disabled": True}
                 if self.runner is None else self.runner.status())
        return 200, {
            "store": {"running": running, "endpoint": client.endpoint},
            "writeApi": self.runner is not None,
            "inputPath": self.input_path,
            "pid": os.getpid(),
            "llm": llm.availability(self.root),
            **state,
        }

    def index(self, request: Request) -> tuple[int, dict]:
        code, payload = self._store(lambda client: assemble.index(client, self.input_dir))
        if code == 200:
            for row in payload["parts"]:
                row["job"] = self.runner.job_for(row["partId"]) if self.runner is not None else None
        return code, payload

    def heuristics(self, request: Request) -> tuple[int, dict]:
        return self._store(assemble.heuristics)

    def kpi(self, request: Request) -> tuple[int, dict]:
        return self._store(assemble.kpi_table)

    def vocabulary(self, request: Request) -> tuple[int, dict]:
        return 200, assemble.vocabulary()

    def part(self, request: Request, part_id: str) -> tuple[int, dict]:
        part_id = unquote(part_id)
        if not valid_part_id(part_id):
            return 400, {"error": "invalid part id"}
        return self._store(lambda client: assemble.part(client, part_id))

    def cq(self, request: Request) -> tuple[int, dict]:
        return 200, assemble.competency_questions(self.root)

    def plan(self, request: Request) -> tuple[int, dict]:
        force_all = request.query.get("all") in ("1", "true", "yes")
        return self._store(lambda client: assemble.plan(client, self.input_dir, force_all=force_all))

    def jobs(self, request: Request) -> tuple[int, dict]:
        """The queue, and the digest of the index graph the page compares.

        ``state`` is ``disabled`` on a server started without the write API;
        ``indexDigest`` changes whenever a sync - from here or from a
        terminal - replaced something in the index graph.
        """
        if self.runner is None:
            payload = {"state": "disabled", "exitCode": None, "log": [],
                       "current": None, "queue": [], "recent": [], "disabled": True}
        else:
            payload = self.runner.status()
        try:
            payload["indexDigest"] = assemble.index_digest(assemble.index_rows(self.client()))
        except Exception:  # noqa: BLE001 - a store that is away just says nothing here
            payload["indexDigest"] = None
        return 200, payload

    # -- query --------------------------------------------------------------

    def query(self, request: Request) -> tuple[int, dict]:
        try:
            body = request.json()
        except BodyTooLarge as error:
            return 413, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}
        sparql = body.get("sparql")
        if not isinstance(sparql, str) or not sparql.strip():
            return 400, {"error": "sparql is required"}
        keyword = assemble.update_keyword(sparql)
        if keyword:
            return 400, {"error": f"this endpoint is read-only; the request uses {keyword}"}
        return self._store(lambda client: assemble.query(client, sparql, timeout=QUERY_TIMEOUT))

    # -- drafting a query ---------------------------------------------------

    def draft_query(self, request: Request) -> tuple[int, dict]:
        """A draft of a query for a question in plain English; nothing runs."""
        if not str(request.header("Content-Type", "")).lower().startswith("application/json"):
            return 415, {"error": "the body must be JSON (Content-Type: application/json)"}
        try:
            body = request.json()
        except BodyTooLarge as error:
            return 413, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}
        try:
            return 200, llm.draft(body.get("question"), root=self.root)
        except llm.DraftError as error:
            return error.status, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}

    # -- settings -----------------------------------------------------------

    def get_settings(self, request: Request) -> tuple[int, dict]:
        """The settings with the API key masked; the key itself is never answered."""
        try:
            return 200, settings.public_view(self.root)
        except settings.SettingsError as error:
            return 500, {"error": str(error)}

    def post_settings(self, request: Request) -> tuple[int, dict]:
        """Change the fields the body names: ``{"llm": {"apiKey"?, "baseUrl"?, "model"?}}``."""
        try:
            body = request.json()
        except BodyTooLarge as error:
            return 413, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}
        unknown = sorted(set(body) - {"llm"})
        if unknown:
            return 400, {"error": f"unknown setting(s): {', '.join(unknown)}"}
        try:
            settings.update_llm(self.root, body.get("llm", {}))
            return 200, settings.public_view(self.root)
        except settings.SettingsWriteError as error:
            return 500, {"error": str(error)}
        except settings.SettingsError as error:
            return 400, {"error": str(error)}

    # -- similarity ---------------------------------------------------------

    def similarity(self):
        with self._similarity_lock:
            if self._similarity is None:
                from ged.retrieval.service import SimilarityService

                self._similarity = SimilarityService(self.client(), cache_dir=self.root / "runs" / "ged")
            return self._similarity

    def _similarity_call(self, call) -> tuple[int, dict]:
        try:
            service = self.similarity()
        except ImportError:
            return 503, {"error": "similarity service unavailable"}
        try:
            return 200, call(service)
        except ImportError:
            return 503, {"error": "similarity service unavailable"}
        except KeyError as error:
            return 400, {"error": str(error).strip("'\"")}
        except ValueError as error:
            return 400, {"error": str(error)}
        except LookupError as error:
            return 404, {"error": str(error)}
        except Exception as error:  # noqa: BLE001 - the text, never the traceback
            # "this part is not in the corpus" is the caller's mistake, not the
            # server's, whichever exception class the service spells it with.
            # Matched by name so the web layer keeps importing nothing of the
            # similarity package beyond its entry point.
            name = type(error).__name__
            if name in ("PartNotFound", "ProjectionFailed"):
                return 404, {"error": f"{name}: {error}"}
            return 500, {"error": f"{name}: {error}"}

    def similarity_configs(self, request: Request) -> tuple[int, dict]:
        """Presets and weight specs - and, given ``config`` / ``weights``, the
        description of that configuration under ``resolved``."""
        wants = any(key in request.query for key in ("config", "weights"))
        try:
            config_name, weights = _cost_params(request)
        except ValueError as error:
            return 400, {"error": str(error)}

        def answer(service):
            payload = service.configs()
            if wants:
                payload["resolved"] = service.resolve(config_name, weights)
            return payload

        return self._similarity_call(answer)

    def similarity_rank(self, request: Request) -> tuple[int, dict]:
        try:
            query = _part_id_param(request, "query")
            config_name, weights = _cost_params(request)
            candidates = _id_list_param(request, "candidates")
            top = _count_param(request, "top")
            prefilter = _count_param(request, "prefilter")
        except ValueError as error:
            return 400, {"error": str(error)}
        return self._similarity_call(lambda service: service.rank(
            query, config_name=config_name, weights=weights, candidate_ids=candidates,
            top=top, prefilter_keep=prefilter))

    def similarity_compare(self, request: Request) -> tuple[int, dict]:
        try:
            part_a = _part_id_param(request, "a")
            part_b = _part_id_param(request, "b")
            config_name, weights = _cost_params(request)
        except ValueError as error:
            return 400, {"error": str(error)}
        return self._similarity_call(
            lambda service: service.compare(part_a, part_b, config_name=config_name, weights=weights))

    # -- writes -------------------------------------------------------------

    def upload(self, request: Request) -> tuple[int, dict]:
        name = request.query.get("name")
        if not valid_step_name(name):
            return 400, {"error": "name must be a bare file name ending in .step or .stp"}
        length = request.content_length
        if length <= 0:
            return 400, {"error": "empty body"}
        if length > MAX_UPLOAD_BYTES:
            return 413, {"error": f"file larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"}
        input_dir = self.input_dir
        input_dir.mkdir(parents=True, exist_ok=True)
        target = input_dir / name
        overwrite = request.query.get("overwrite") in ("1", "true", "yes")
        if target.exists() and not overwrite:
            return 409, {"error": f"{name} already exists; pass overwrite=1 to replace it",
                         "partId": target.stem}
        temporary = target.with_name(target.name + ".tmp")
        remaining = length
        try:
            with temporary.open("wb") as handle:
                while remaining > 0:
                    chunk = request.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    handle.write(chunk)
                    remaining -= len(chunk)
            if remaining > 0:
                temporary.unlink(missing_ok=True)
                return 400, {"error": "body shorter than Content-Length"}
            os.replace(temporary, target)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            return 500, {"error": f"could not store the file: {error}"}
        part_id = target.stem
        code, payload = self._store(lambda client: assemble.plan(client, input_dir))
        plan = [row for row in payload.get("plan", []) if row["partId"] == part_id] if code == 200 else []
        return 202, {"partId": part_id, "file": target.as_posix(), "plan": plan}

    def sync(self, request: Request) -> tuple[int, dict]:
        try:
            body = request.json() if request.content_length else {}
        except BodyTooLarge as error:
            return 413, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}
        parts = body.get("parts") or []
        if not isinstance(parts, list) or any(not valid_part_id(item) for item in parts):
            return 400, {"error": "parts must be a list of part ids"}
        if self.runner.running:
            return 409, {"error": "a job is already running", **self.runner.status()}
        force_all = bool(body.get("all"))
        arguments = {"parts": parts, "all": force_all, "dryRun": bool(body.get("dryRun"))}
        if not parts:
            # Which rows the job will touch, as the planner sees it now, so
            # the page can mark those rows and leave the others alone.
            code, payload = self._store(
                lambda client: assemble.plan(client, self.input_dir, force_all=force_all))
            if code == 200:
                arguments["touches"] = [row["partId"] for row in payload["plan"]
                                        if row["action"] not in ("current", "keep")]
        job = self.runner.submit("sync", arguments)
        return 202, {"jobId": job.jobId, **self.runner.status()}

    def remove(self, request: Request) -> tuple[int, dict]:
        try:
            body = request.json()
        except BodyTooLarge as error:
            return 413, {"error": str(error)}
        except ValueError as error:
            return 400, {"error": str(error)}
        part_id = body.get("partId")
        if not valid_part_id(part_id):
            return 400, {"error": "partId is required"}
        if self.runner.running:
            return 409, {"error": "a job is already running", **self.runner.status()}
        job = self.runner.submit("remove", {"partId": part_id,
                                            "deleteSource": bool(body.get("deleteSource"))})
        return 202, {"jobId": job.jobId, **self.runner.status()}

    def shutdown(self, request: Request) -> tuple[int, dict]:
        # A header a cross-origin page cannot set: a server anybody can stop
        # is one that stops while somebody is reading it.
        if request.header(SHUTDOWN_HEADER) is None:
            return 403, {"error": f"missing {SHUTDOWN_HEADER} header"}
        if self.presence is None:
            return 503, {"error": "this server cannot be stopped from here"}
        self.presence.request_stop("asked to stop by another process")
        return 202, {"stopping": True}


ROUTES: list[tuple[str, re.Pattern, str, bool]] = [
    ("GET", re.compile(r"^/api/status/?$"), "status", False),
    ("GET", re.compile(r"^/api/index/?$"), "index", False),
    ("GET", re.compile(r"^/api/heuristics/?$"), "heuristics", False),
    ("GET", re.compile(r"^/api/kpi/?$"), "kpi", False),
    ("GET", re.compile(r"^/api/vocabulary/?$"), "vocabulary", False),
    ("GET", re.compile(r"^/api/cq/?$"), "cq", False),
    ("GET", re.compile(r"^/api/plan/?$"), "plan", False),
    ("GET", re.compile(r"^/api/jobs/?$"), "jobs", False),
    ("POST", re.compile(r"^/api/query/?$"), "query", False),
    ("POST", re.compile(r"^/api/draft-query/?$"), "draft_query", False),
    ("GET", re.compile(r"^/api/settings/?$"), "get_settings", False),
    ("POST", re.compile(r"^/api/settings/?$"), "post_settings", True),
    ("GET", re.compile(r"^/api/similarity/configs/?$"), "similarity_configs", False),
    ("GET", re.compile(r"^/api/similarity/rank/?$"), "similarity_rank", False),
    ("GET", re.compile(r"^/api/similarity/compare/?$"), "similarity_compare", False),
    ("POST", re.compile(r"^/api/upload/?$"), "upload", True),
    ("POST", re.compile(r"^/api/sync/?$"), "sync", True),
    ("POST", re.compile(r"^/api/remove/?$"), "remove", True),
    ("POST", re.compile(r"^/api/shutdown/?$"), "shutdown", False),
    ("GET", re.compile(r"^/api/part/([^/]+)/?$"), "part", False),
]

MESH_ROUTE = re.compile(r"^/api/part/([^/]+)/(mesh\.json|mesh\.bin)$")


# ------------------------------------------------------- query parameters

def _part_id_param(request: Request, name: str) -> str:
    value = request.query.get(name)
    if not value:
        raise ValueError(f"{name} is required")
    if not valid_part_id(value):
        raise ValueError(f"{name}: invalid part id")
    return value


def _id_list_param(request: Request, name: str) -> list[str] | None:
    raw = request.query.get(name)
    if raw is None or not raw.strip():
        return None
    ids = [item.strip() for item in raw.split(",") if item.strip()]
    for item in ids:
        if not valid_part_id(item):
            raise ValueError(f"{name}: invalid part id {item!r}")
    return ids


def _count_param(request: Request, name: str) -> int | None:
    raw = request.query.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name}: expected an integer, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"{name}: must be >= 0")
    return value or None


def _cost_params(request: Request) -> tuple[str | None, dict]:
    config_name = request.query.get("config") or None
    if config_name is not None and not re.match(r"^[A-Za-z0-9_.-]{1,64}$", config_name):
        raise ValueError("config: invalid preset name")
    weights: dict = {}
    raw = request.query.get("weights")
    if raw:
        for item in raw.split(","):
            if not item.strip():
                continue
            key, separator, value = item.partition("=")
            if not separator:
                raise ValueError("weights: expected K=V pairs")
            try:
                weights[key.strip()] = float(value)
            except ValueError:
                raise ValueError(f"weights: {key.strip()} is not a number") from None
    return config_name, weights


def dispatch(api: Api, request: Request) -> tuple[int, dict] | None:
    """Route one API request; ``None`` means "not an API path"."""
    for method, pattern, name, is_write in ROUTES:
        match = pattern.match(request.path)
        if not match or method != request.method:
            continue
        if is_write:
            if api.runner is None:
                return 403, {"error": "the write API is off (started with --no-write-api)"}
            if request.header(WRITE_HEADER) is None:
                return 403, {"error": f"missing {WRITE_HEADER} header"}
        return getattr(api, name)(request, *match.groups())
    if request.path.startswith("/api/") and not MESH_ROUTE.match(request.path):
        known = any(pattern.match(request.path) for _, pattern, _, _ in ROUTES)
        return (405, {"error": "method not allowed"}) if known else (404, {"error": "not found"})
    return None


# ------------------------------------------------------------------ handler

def _safe_join(root: Path, relative: str) -> Path | None:
    try:
        candidate = (root / relative).resolve()
        candidate.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return candidate


def _asset_path(relative: str) -> Path | None:
    """The file behind a ``/`` request, or None if the page does not publish it."""
    if not relative:
        return None
    head, separator, _rest = relative.replace("\\", "/").partition("/")
    if separator:
        return _safe_join(ASSET_ROOT, relative) if head in ASSET_DIRS else None
    return _safe_join(ASSET_ROOT, head) if head.endswith(ASSET_PAGE_SUFFIXES) else None


def _asset_etag(payload: bytes) -> str:
    import hashlib

    return f'"{hashlib.sha256(payload).hexdigest()[:32]}"'


def mesh_etag(part_id: str, facts_key: str | None) -> str:
    """The validator a mesh answers with: the build that produced it."""
    return f'W/"{part_id}:{facts_key or "unknown"}"'


def if_match_satisfied(header: str, etag: str) -> bool:
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate == "*" or candidate == etag or candidate == etag.replace('W/', ''):
            return True
    return False


def _make_handler(api: Api, presence: "_Presence"):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):  # noqa: N802 - stdlib naming
            self._handle("GET")

        def do_POST(self):  # noqa: N802
            self._handle("POST")

        def _handle(self, method: str) -> None:
            """Answer, whatever happens: a handler that falls through leaves
            the client with nothing at all and a traceback on the console."""
            try:
                self._route(method)
            except Exception as error:  # noqa: BLE001 - a status code, never a traceback
                try:
                    self._json(500, {"error": type(error).__name__})
                except Exception:  # noqa: BLE001 - the socket is already gone
                    self.close_connection = True

        def _route(self, method: str) -> None:
            presence.touch()
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = {key: values[0] for key, values in parse_qs(parsed.query).items() if values}
            length = int(self.headers.get("Content-Length") or 0)
            consumed = {"n": 0}

            def reader(size: int) -> bytes:
                size = min(size, length - consumed["n"])
                if size <= 0:
                    return b""
                chunk = self.rfile.read(size)
                consumed["n"] += len(chunk)
                return chunk

            request = Request(method, path, query=query, headers=dict(self.headers.items()),
                              reader=reader, content_length=length)
            routed = dispatch(api, request)
            if routed is not None:
                code, payload = routed
                if consumed["n"] < length:
                    if length - consumed["n"] <= 1 << 20:
                        while consumed["n"] < length and reader(1 << 16):
                            pass
                    else:
                        self.close_connection = True
                self._json(code, payload)
                return

            if method != "GET":
                self.send_error(404, "not found")
                return

            mesh = MESH_ROUTE.match(path)
            if mesh:
                self._mesh(unquote(mesh.group(1)), mesh.group(2))
                return

            if path == "/favicon.ico":
                self._bytes(200, FAVICON, "image/svg+xml", cache="max-age=86400")
                return

            if path == "/ontology.html":
                target = api.root.joinpath(*ONTOLOGY_PAGE)
                if not target.is_file():
                    self.send_error(404, "the ontology page is written by: python run.py build")
                    return
            else:
                target = _asset_path(path.lstrip("/") or "index.html")
            if target is None or not target.is_file():
                self.send_error(404, "not found")
                return
            payload = target.read_bytes()
            etag = _asset_etag(payload)
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._bytes(200, payload, CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream"),
                        etag=etag, cache="no-cache")

        def _mesh(self, part_id: str, name: str) -> None:
            if not valid_part_id(part_id):
                self._json(400, {"error": "invalid part id"})
                return
            path = api.root / "runs" / "mesh" / part_id / name
            if not path.is_file():
                self._json(404, {"error": f"no mesh for {part_id}; it is written when the part is built"})
                return
            # The bundle carries the facts key; the page demands the same one
            # here, so a bundle and a mesh from two builds are never drawn as
            # one part.
            demanded = self.headers.get("If-Match")
            etag = mesh_etag(part_id, self.headers.get("X-Facts-Key") or _facts_key(api, part_id))
            if demanded is not None and not if_match_satisfied(demanded, etag):
                self._json(409, {"error": "the mesh on disk is not from the build this page is reading",
                                 "etag": etag})
                return
            self._bytes(200, path.read_bytes(),
                        CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream"),
                        etag=etag, cache="no-store")

        def _bytes(self, code: int, payload: bytes, content_type: str, *, etag=None, cache="no-store") -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", cache)
            if etag:
                self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(payload)

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # only complain about misses
            if "404" in (fmt % args):
                super().log_message(fmt, *args)

    return Handler


def _facts_key(api: Api, part_id: str) -> str | None:
    try:
        for row in assemble.index_rows(api.client()):
            if row["partId"] == part_id:
                return row.get("factsKey")
    except Exception:  # noqa: BLE001 - a validator, not a reason to fail the mesh
        return None
    return None


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False


class _Presence:
    """This server's last-request clock and its stop switch."""

    def __init__(self) -> None:
        self._last = time.time()
        self._lock = threading.Lock()
        self._stop_reason: str | None = None
        self._server: _Server | None = None

    def bind(self, server: "_Server") -> None:
        self._server = server

    def touch(self) -> None:
        with self._lock:
            self._last = time.time()

    @property
    def idle_seconds(self) -> float:
        with self._lock:
            return time.time() - self._last

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def request_stop(self, reason: str) -> None:
        self._stop_reason = reason
        if self._server is not None:
            threading.Thread(target=self._server.shutdown, daemon=True).start()


def _idle_watchdog(presence: _Presence, timeout: float) -> None:
    while presence.stop_reason is None:
        remaining = timeout - presence.idle_seconds
        if remaining <= 0:
            presence.request_stop(f"idle for {timeout:.0f}s")
            return
        time.sleep(min(30.0, max(1.0, remaining)))


def lock_dir(root: Path) -> Path:
    return Path(root) / "runs" / "web"


def write_lock(root: Path, port: int) -> None:
    """Say who holds this port, so another terminal can name it or stop it."""
    directory = lock_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"port-{port}.json").write_text(
        json.dumps({"port": port, "pid": os.getpid(), "root": Path(root).as_posix(),
                    "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}),
        encoding="utf-8", newline="\n")


def clear_lock(root: Path, port: int) -> None:
    (lock_dir(root) / f"port-{port}.json").unlink(missing_ok=True)


def probe(port: int, timeout: float = 2.0) -> dict | None:
    """What answers on this port, if anything of ours does."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def stop(port: int, timeout: float = 10.0) -> tuple[bool, str]:
    """Ask the server on *port* to stop; answer whether it did."""
    import urllib.error
    import urllib.request

    if probe(port) is None:
        return False, f"nothing of ours answers on port {port}"
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}",
                                     method="POST", headers={SHUTDOWN_HEADER: "1"})
    try:
        urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as error:
        return False, f"the server refused to stop: HTTP {error.code}"
    except (urllib.error.URLError, OSError) as error:
        return False, f"the server did not answer: {error}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if probe(port, timeout=1.0) is None:
            return True, f"stopped the server on port {port}"
        time.sleep(0.25)
    return False, f"the server on port {port} is still answering"


def serve(root: str | Path, *, port: int = 8765, open_browser: bool = True,
          allow_write: bool = True, input_path: str = "inputs",
          idle_timeout: float | None = None) -> int:
    root = Path(root).resolve()
    presence = _Presence()
    runner = JobRunner(root, input_path=input_path) if allow_write else None
    api = Api(root, input_path=input_path, runner=runner, presence=presence)

    if idle_timeout is None:
        idle_timeout = 0.0 if open_browser else 1800.0

    try:
        httpd = _Server(("127.0.0.1", port), _make_handler(api, presence))
    except OSError as error:
        print(f"[web] port {port} is not free: {error}")
        print(f"[web] stop the server holding it, or start this one with --port <other>")
        return 1

    presence.bind(httpd)
    write_lock(root, port)
    with httpd:
        url = f"http://127.0.0.1:{port}/index.html"
        print(f"[web] pages  {ASSET_ROOT}")
        print(f"[web] store  {api.client().endpoint}"
              f"{'' if api.client().ping() else '  (not answering: python run.py fuseki start)'}")
        print(f"[web] meshes {root / 'runs' / 'mesh'}")
        print(f"[web] write API {'on' if runner else 'off'}   inputs {input_path}")
        if idle_timeout and idle_timeout > 0:
            threading.Thread(target=_idle_watchdog, args=(presence, float(idle_timeout)), daemon=True).start()
            print(f"[web] idle timeout {idle_timeout:.0f}s (--idle-timeout 0 disables)")
        print(f"[web] open   {url}   (Ctrl+C to stop)")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
            if presence.stop_reason:
                print(f"[web] stopped: {presence.stop_reason}")
        except KeyboardInterrupt:
            print("\n[web] stopped")
        finally:
            # A sync still running is still writing to the store, so it does
            # not get to outlive the server that started it.
            if runner is not None and runner.running:
                print("[web] stopping the running job...")
                if not runner.stop():
                    print("[web] the job did not stop; it may still be writing to the store")
            clear_lock(root, port)
    return 0
