"""A small client for the SPARQL 1.1 Protocol and the Graph Store Protocol.

Standard library only.  Nothing here is specific to Fuseki beyond the default
port and the ``/$/ping`` health endpoint.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://localhost:3030"
DEFAULT_DATASET = "nx"


class StoreError(RuntimeError):
    pass


class Fuseki:
    def __init__(self, base: str = DEFAULT_BASE, dataset: str = DEFAULT_DATASET, timeout: float = 600.0) -> None:
        self.base = base.rstrip("/")
        self.dataset = dataset
        self.timeout = timeout

    # ---------------------------------------------------------------- basics
    @property
    def endpoint(self) -> str:
        return f"{self.base}/{self.dataset}"

    def _request(self, url: str, data: bytes | None = None, *, method: str = "POST",
                 content_type: str | None = None, accept: str | None = None) -> bytes:
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type
        if accept:
            headers["Accept"] = accept
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:2000]
            raise StoreError(f"{method} {url} -> {error.code}: {detail}") from None
        except urllib.error.URLError as error:
            raise StoreError(f"{method} {url}: {error.reason}") from None

    def ping(self) -> bool:
        try:
            self._request(f"{self.base}/$/ping", method="GET")
            return True
        except StoreError:
            return False

    # ---------------------------------------------------------------- SPARQL
    def query(self, sparql: str) -> dict:
        raw = self._request(f"{self.endpoint}/query", sparql.encode("utf-8"),
                            content_type="application/sparql-query; charset=utf-8",
                            accept="application/sparql-results+json")
        return json.loads(raw.decode("utf-8"))

    def query_graph(self, sparql: str, accept: str = "text/turtle") -> str:
        raw = self._request(f"{self.endpoint}/query", sparql.encode("utf-8"),
                            content_type="application/sparql-query; charset=utf-8", accept=accept)
        return raw.decode("utf-8")

    def rows(self, sparql: str) -> list[dict]:
        """Bindings as ``{var: value-string}`` rows."""
        result = self.query(sparql)
        return [{k: v["value"] for k, v in binding.items()} for binding in result["results"]["bindings"]]

    def ask(self, sparql: str) -> bool:
        return bool(self.query(sparql).get("boolean"))

    def update(self, sparql: str) -> None:
        self._request(f"{self.endpoint}/update", sparql.encode("utf-8"),
                      content_type="application/sparql-update; charset=utf-8")

    # ------------------------------------------------------------ graph store
    def put_graph(self, graph: str, data: bytes | str, content_type: str = "text/turtle") -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        url = f"{self.endpoint}/data?graph={urllib.parse.quote(graph, safe='')}"
        self._request(url, data, method="PUT", content_type=f"{content_type}; charset=utf-8")

    def post_dataset(self, data: bytes | str, content_type: str = "application/trig") -> None:
        """Add quads (TriG / N-Quads) to the dataset; each quad lands in its own graph."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._request(f"{self.endpoint}/data", data, method="POST", content_type=f"{content_type}; charset=utf-8")

    def get_graph(self, graph: str, accept: str = "text/turtle") -> str:
        url = f"{self.endpoint}/data?graph={urllib.parse.quote(graph, safe='')}"
        return self._request(url, method="GET", accept=accept).decode("utf-8")

    def drop_graph(self, graph: str) -> None:
        self.update(f"DROP SILENT GRAPH <{graph}>")

    def graph_exists(self, graph: str) -> bool:
        return self.ask(f"ASK {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}")

    def graph_size(self, graph: str) -> int:
        rows = self.rows(f"SELECT (COUNT(*) AS ?n) WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}")
        return int(rows[0]["n"]) if rows else 0

    def graphs(self, prefix: str | None = None) -> list[str]:
        rows = self.rows("SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } } ORDER BY ?g")
        names = [row["g"] for row in rows]
        return [g for g in names if prefix is None or g.startswith(prefix)]

    # ------------------------------------------------------------------ SHACL
    def shacl(self, shapes_turtle: str, graph: str) -> str:
        """Validate one graph against shapes; returns the validation report as Turtle."""
        url = f"{self.endpoint}/shacl?graph={urllib.parse.quote(graph, safe='')}"
        raw = self._request(url, shapes_turtle.encode("utf-8"), content_type="text/turtle; charset=utf-8",
                            accept="text/turtle")
        return raw.decode("utf-8")
