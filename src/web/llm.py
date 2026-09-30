"""Draft a SPARQL query from a question in plain English.

A language model behind any OpenAI-compatible chat completions endpoint
(the owner chooses which; DeepSeek is one) is given the graph model, the vocabulary and the preset
questions, and asked for one read-only query.  The draft goes into the
editor; nothing runs until the reader presses Run, which is the ordinary
``POST /api/query``.  The model never talks to the store and never sees a
result.

Configuration is :mod:`web.settings` - ``settings.json`` at the repository
root, overridden by ``CNCGAIDE_LLM_API_KEY`` / ``CNCGAIDE_LLM_BASE_URL`` /
``CNCGAIDE_LLM_MODEL`` when those are set.  Without all three - key, base
URL, model - the feature is not offered.  The key goes into the ``Authorization`` header of the request to
the model and nowhere else: not into a file this module writes, a log line,
an error message or an answer.

What the model says is checked, not repaired: the code fence is removed, the
text must not use an update keyword or ``SERVICE``, and its first keyword
after any ``PREFIX`` / ``BASE`` must be ``SELECT`` or ``ASK``.  A draft that
fails is refused with the reason; there is no retry.

Standard library only.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from web import settings

TIMEOUT = 60.0
TEMPERATURE = 0
# A reasoning model counts its thinking against this budget as well; the
# prompt is about 40 KB, so the budget leaves room to think and then answer.
MAX_TOKENS = 4000
MAX_QUESTION_CHARS = 2000
GRAPH_MODEL_DOC = ("src", "web", "graph_model.md")
# The sections of the graph model the model is shown, by heading.  A heading
# matches when it is the name, or the name followed by a comma
# ("Ontology graph, the parts rules read").
GRAPH_MODEL_SECTIONS = ("Namespaces", "Graphs", "Facts graph", "Derived graph", "Ontology graph")


# ------------------------------------------------------------------- errors

class DraftError(Exception):
    """A draft that could not be made.  ``status`` is the HTTP answer."""

    status = 500


class NotConfigured(DraftError):
    status = 503


class ModelUnreachable(DraftError):
    status = 502


class NoUsableQuery(DraftError):
    status = 422


class OutputBudgetExhausted(DraftError):
    """The model stopped at ``max_tokens`` before it wrote an answer."""

    status = 502


# ------------------------------------------------------------ configuration

def availability(root: str | Path, environ=None) -> dict:
    """``{"available": true, "model": ...}`` when key, base URL and model are
    all set; otherwise ``{"available": false, "error": "base URL not set; ..."}``."""
    try:
        effective = settings.llm_effective(root, environ)
    except settings.SettingsError as error:
        return {"available": False, "error": str(error)}
    gaps = settings.missing(effective)
    if gaps:
        return {"available": False, "error": "; ".join(gaps)}
    return {"available": True, "model": effective["model"]}


# ------------------------------------------------------------------ prompt

def graph_model_sections(text: str, names=GRAPH_MODEL_SECTIONS) -> str:
    """The named ``##`` sections of the graph model, verbatim, in order."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            current = next((name for name in names
                            if heading == name or heading.startswith(name + ",")), None)
            if current is not None:
                sections[current] = [line]
            continue
        if line.startswith("# "):
            current = None
            continue
        if current is not None:
            sections[current].append(line)
    missing = [name for name in names if name not in sections]
    if missing:
        raise ValueError(f"the graph model has no section named: {', '.join(missing)}")
    return "\n\n".join("\n".join(sections[name]).strip() for name in names)


RULES = """\
How to write the query:

1. Answer with exactly one read-only query: SELECT or ASK. Never UPDATE, INSERT,
   DELETE, LOAD, CLEAR, DROP, CREATE, COPY, MOVE, ADD or WITH, and never SERVICE.
2. Do not write PREFIX or BASE lines. The server declares cg:, nx:, rdf:, rdfs:,
   xsd:, skos: and owl: for you.
3. Name graphs only through the two placeholders, written inside angle brackets
   exactly as shown: GRAPH <{INDEX}> and GRAPH <{ONTOLOGY}>. The server replaces
   them. Never write a graph IRI with a digest or a key in it.
4. Reach a part's facts graph and derived graph through the index graph:
   GRAPH <{INDEX}> { ?part cg:partId ?partId ; cg:factsGraph ?fg ; cg:derivedGraph ?dg }
   and then GRAPH ?fg { ... } and GRAPH ?dg { ... }.
5. Every triple pattern must sit inside the GRAPH block of the graph that holds it;
   a pattern outside every GRAPH block reads the default graph, which is empty.
   A variable is bound in the GRAPH block where its triple pattern is.
6. FILTER, BIND and OPTIONAL must not use a variable that is only bound in a
   different GRAPH block. Inside a GRAPH block such a variable is still unbound, so
   the FILTER drops every row and the BIND yields nothing. This is the most common
   mistake. Put a FILTER or BIND that compares variables from two GRAPH blocks at
   the outer level, after both blocks.

   Wrong - ?limit is bound in the ontology block, but the FILTER sits in the facts block:
     GRAPH <{ONTOLOGY}> { cg:t_hole_ld cg:value ?limit }
     GRAPH ?fg { ?f nx:DEPTH ?depth ; nx:DIAMETER ?d . FILTER(?depth / ?d > ?limit) }

   Right - the FILTER is at the outer level, where both blocks have bound their variables:
     GRAPH <{ONTOLOGY}> { cg:t_hole_ld cg:value ?limit }
     GRAPH ?fg { ?f nx:DEPTH ?depth ; nx:DIAMETER ?d }
     FILTER(?depth / ?d > ?limit)

7. For a short display name of an IRI use BIND(STRAFTER(STR(?x), "#") AS ?name).
   The variable after AS, in a BIND or a SELECT expression, must be a new one:
   BIND(STRAFTER(STR(?h), "#") AS ?rule), never BIND(STRAFTER(STR(?h), "#") AS ?h).
8. Take every class, attribute, quantity, relation, threshold, rule and KPI name
   from the vocabulary below, spelled exactly as it is there; never make one up.
   A class together with its subclasses is
   GRAPH <{ONTOLOGY}> { ?cls rdfs:subClassOf* nx:SOME_CLASS } and then ?f a ?cls.
9. A verdict publishes several values under cg:value, each named by cg:name. When
   you read one, pin its name with a literal, or you get every value of the verdict:
   cg:value [ cg:name "web" ; cg:value ?web ]
10. Count or list relations by their type: ?r a cg:FeatureRelation ; cg:relationType ...
    The part's cg:relationCount summaries carry a cg:relationType as well.
    Count or list features through cg:nodeId: ?f cg:partOf ?part ; cg:nodeId ?nodeId.
    Faces and relations carry cg:partOf and a class too.
11. End with LIMIT 200 unless the question asks for a count, a single value, or a
    different limit.
12. If the store does not hold what the question asks about, do not invent names:
    answer with no code block and one sentence saying what is missing.

Answer format: one code block fenced with ```sparql, then one sentence saying what
the query returns."""


def system_prompt(graph_model_text: str, vocabulary: dict, examples: list[dict]) -> str:
    """The system message: the graph model, the vocabulary, the examples, the rules."""
    parts = [
        "You write SPARQL 1.1 queries against an Apache Jena Fuseki store of machining "
        "features that Siemens NX recognised in CAD parts, the design-rule verdicts "
        "computed on them and the KPI results derived from them. You only draft the "
        "query; you never see the store or any result.",
        "# The graph model\n\n" + graph_model_sections(graph_model_text),
        "# The vocabulary (JSON)\n\n" + json.dumps(vocabulary, ensure_ascii=True, separators=(",", ":")),
        "# Example questions and their queries\n\n" + "\n\n".join(
            f"Question: {example.get('question', '').strip()}\n```sparql\n{example.get('sparql', '').strip()}\n```"
            for example in examples),
        "# Rules\n\n" + RULES,
    ]
    return "\n\n".join(parts)


def build_messages(question: str, *, graph_model_text: str, vocabulary: dict,
                   examples: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt(graph_model_text, vocabulary, examples)},
        {"role": "user", "content": question.strip()},
    ]


def context(root: str | Path) -> dict:
    """The three inputs of the prompt, read now from the checkout."""
    from web import assemble

    root = Path(root)
    return {
        "graph_model_text": root.joinpath(*GRAPH_MODEL_DOC).read_text(encoding="utf-8"),
        "vocabulary": assemble.vocabulary(),
        "examples": assemble.competency_questions(root)["questions"],
    }


# ----------------------------------------------------------------- the reply

FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.DOTALL)
READ_FORMS = ("SELECT", "ASK")
QUERY_FORMS = READ_FORMS + ("CONSTRUCT", "DESCRIBE", "INSERT", "DELETE", "LOAD", "CLEAR", "DROP",
                            "CREATE", "COPY", "MOVE", "ADD", "WITH")
DECLARATION = re.compile(r"^\s*(?:PREFIX\s+[A-Za-z0-9_.-]*:\s*<[^>]*>|BASE\s*<[^>]*>)", re.IGNORECASE)
NOTE_CHARS = 500


def _one_line(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def first_keyword(sparql: str) -> str | None:
    """The first keyword after the ``PREFIX`` and ``BASE`` declarations."""
    from web import assemble

    text = assemble.strip_comments(sparql)
    while True:
        match = DECLARATION.match(text)
        if not match:
            break
        text = text[match.end():]
    word = re.match(r"\s*([A-Za-z]+)", text)
    return word.group(1).upper() if word else None


def check_query(sparql: str) -> str:
    """The query, if it is one read-only query; :class:`NoUsableQuery` otherwise."""
    from web import assemble

    sparql = sparql.strip()
    if not sparql:
        raise NoUsableQuery("the model did not return a usable query: the code block is empty")
    keyword = assemble.update_keyword(sparql)
    if keyword:
        raise NoUsableQuery(f"the model did not return a usable query: it uses {keyword}; "
                            "only SELECT and ASK are drafted")
    if re.search(r"(?<![?$:\w])SERVICE\b", assemble.strip_comments(sparql), re.IGNORECASE):
        raise NoUsableQuery("the model did not return a usable query: it uses SERVICE; "
                            "a drafted query reads this store only")
    first = first_keyword(sparql)
    if first not in READ_FORMS:
        raise NoUsableQuery("the model did not return a usable query: it starts with "
                            f"{first or 'nothing'}, not SELECT or ASK")
    return sparql


def parse_reply(text: str) -> tuple[str, str]:
    """``(sparql, note)`` from the model's answer, the fence removed."""
    text = (text or "").strip()
    if not text:
        raise NoUsableQuery("the model did not return a usable query: the answer is empty")
    blocks = FENCE.findall(text)
    if blocks:
        chosen = next((body for language, body in blocks if language.lower() in ("sparql", "rq")),
                      blocks[0][1])
        note = _one_line(FENCE.sub(" ", text), NOTE_CHARS)
        return check_query(chosen), note
    # No fence: a bare query is checked as it is; anything else is the
    # model saying it cannot, and that sentence is the reason given.
    if first_keyword(text) in QUERY_FORMS:
        return check_query(text), ""
    raise NoUsableQuery(f"the model did not return a query: {_one_line(text, 300)}")


# -------------------------------------------------------------- the request

def _redact(text: str, key: str) -> str:
    if key:
        text = text.replace(key, "[key]")
    return re.sub(r"\b(sk|key)[-_][A-Za-z0-9*._-]{4,}", "[key]", text)


def urllib_transport(url: str, body: bytes, headers: dict, timeout: float) -> dict:
    """POST *body* to *url*; the decoded JSON answer.  Raises :class:`ModelUnreachable`."""
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            payload = json.loads(error.read().decode("utf-8", "replace"))
            message = payload.get("error", {}).get("message") if isinstance(payload.get("error"), dict) \
                else payload.get("error") or payload.get("message")
            detail = str(message or "")
        except Exception:  # noqa: BLE001 - the status code is the answer then
            detail = ""
        detail = _one_line(_redact(detail, headers.get("Authorization", "")[7:]), 200)
        raise ModelUnreachable(f"the language model refused the request: HTTP {error.code}"
                               + (f" ({detail})" if detail else "")) from None
    except TimeoutError:
        raise ModelUnreachable(f"the language model did not answer within {timeout:.0f} s") from None
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            raise ModelUnreachable(f"the language model did not answer within {timeout:.0f} s") from None
        raise ModelUnreachable(f"the language model could not be reached: {reason}") from None
    except OSError as error:
        raise ModelUnreachable(f"the language model could not be reached: {error.strerror or type(error).__name__}") from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ModelUnreachable("the language model answered with something that is not JSON") from None


def complete(config: dict, messages: list[dict], *, transport=None) -> dict:
    """One chat completion.  *config* carries ``apiKey``, ``baseUrl``, ``model``."""
    body = json.dumps({
        "model": config["model"],
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {config['apiKey']}",
    }
    return (transport or urllib_transport)(f"{config['baseUrl']}/chat/completions", body, headers, TIMEOUT)


def reply_text(reply: dict) -> str:
    """The answer's ``content``.  A reasoning model's ``reasoning_content`` is
    its thinking, not its answer, and is not read."""
    try:
        choice = reply["choices"][0]
        content = choice["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise NoUsableQuery("the model did not return a usable query: the answer has no message") from None
    content = content if isinstance(content, str) else ""
    if not content.strip() and choice.get("finish_reason") == "length":
        raise OutputBudgetExhausted(
            "the model used its whole output budget before answering (reasoning model); "
            "try a shorter question or a non-reasoning model")
    return content


def draft(question, *, root: str | Path, environ=None, transport=None, prompt_context=None) -> dict:
    """``{"sparql", "note", "model"}`` for *question*; :class:`DraftError` otherwise.

    ``ValueError`` for a question that is not one.  *prompt_context* stands in
    for :func:`context` (a test, or a caller that drafts many questions).
    """
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question is required")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"question is longer than {MAX_QUESTION_CHARS} characters")
    try:
        config = settings.llm_effective(root, environ)
    except settings.SettingsError as error:
        raise NotConfigured(str(error)) from None
    gaps = settings.missing(config)
    if gaps:
        raise NotConfigured(f"no language model is configured ({'; '.join(gaps)}); fill it in under Settings")
    messages = build_messages(question, **(prompt_context or context(root)))
    reply = complete(config, messages, transport=transport)
    sparql, note = parse_reply(reply_text(reply))
    model = reply.get("model") if isinstance(reply.get("model"), str) and reply.get("model") else config["model"]
    return {"sparql": sparql, "note": note, "model": model}
