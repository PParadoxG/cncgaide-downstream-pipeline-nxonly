"""The local settings file: ``settings.json`` at the repository root.

It holds what this machine needs and the repository must never carry - today
the connection to a language model for drafting queries::

    {"llm": {"apiKey": "...", "baseUrl": "https://api.deepseek.com", "model": "deepseek-chat"}}

All three are needed and none has a default: the provider is the owner's
choice (DeepSeek above is an example).  The file is git-ignored;
``settings.example.json`` is the tracked template, with every field empty.
A missing file means nothing is configured, so the drafting feature is
simply not offered.

Three environment variables override the file, field by field, when they are
set: ``CNCGAIDE_LLM_API_KEY``, ``CNCGAIDE_LLM_BASE_URL``,
``CNCGAIDE_LLM_MODEL``.  They are optional.

The key itself never leaves this module except towards the model endpoint:
what the web interface reads is :func:`public_view`, which carries the key
masked.  Writes replace the file atomically (a temporary file in the same
folder, then ``os.replace``), and only the fields a request names change.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

FILE_NAME = "settings.json"
DEFAULTS = {"apiKey": "", "baseUrl": "", "model": ""}
LLM_FIELDS = tuple(DEFAULTS)
FIELD_WORDS = {"apiKey": "API key", "baseUrl": "base URL", "model": "model"}
ENV = {"apiKey": "CNCGAIDE_LLM_API_KEY", "baseUrl": "CNCGAIDE_LLM_BASE_URL", "model": "CNCGAIDE_LLM_MODEL"}
MAX_LENGTH = {"apiKey": 512, "baseUrl": 512, "model": 128}
MODEL_NAME = re.compile(r"^[A-Za-z0-9_.:/@+-]+$")

_write_lock = threading.Lock()


class SettingsError(ValueError):
    """The file cannot be read, or a change to it is not acceptable."""


class SettingsWriteError(SettingsError):
    """The change was acceptable; the file could not be written."""


def path(root: str | Path) -> Path:
    return Path(root) / FILE_NAME


def read_file(root: str | Path) -> dict:
    """The whole file as a dict; ``{}`` when there is no file."""
    target = path(root)
    if not target.is_file():
        return {}
    try:
        loaded = json.loads(target.read_text(encoding="utf-8") or "{}")
    except (OSError, UnicodeDecodeError, ValueError):
        raise SettingsError(f"{FILE_NAME} is not valid JSON; fix or delete it") from None
    if not isinstance(loaded, dict):
        raise SettingsError(f"{FILE_NAME} must hold a JSON object")
    return loaded


def llm_file(root: str | Path) -> dict:
    """The ``llm`` block of the file, every field present (empty when not set)."""
    block = read_file(root).get("llm")
    block = block if isinstance(block, dict) else {}
    out = dict(DEFAULTS)
    for field in LLM_FIELDS:
        value = block.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = value.strip()
    return out


def llm_effective(root: str | Path, environ=None) -> dict:
    """What the drafting feature uses: the file, overridden by the environment.

    ``source`` names where the key came from (``env`` or ``file``);
    ``envOverrides`` lists every field the environment sets.
    """
    environ = os.environ if environ is None else environ
    out = llm_file(root)
    overrides = []
    for field in LLM_FIELDS:
        value = (environ.get(ENV[field]) or "").strip()
        if value:
            out[field] = value
            overrides.append(field)
    out["baseUrl"] = out["baseUrl"].rstrip("/")
    out["source"] = "env" if "apiKey" in overrides else "file"
    out["envOverrides"] = overrides
    return out


def missing(effective: dict) -> list[str]:
    """What is not set, in words: ``["base URL not set", ...]``."""
    return [f"{FIELD_WORDS[field]} not set" for field in LLM_FIELDS if not effective.get(field)]


def mask(key: str) -> str:
    """Enough of a key to recognise it, never enough to use it."""
    if not key:
        return ""
    if len(key) < 12:
        return "..." + key[-2:]
    return f"{key[:3]}...{key[-4:]}"


def public_view(root: str | Path, environ=None) -> dict:
    """The settings as the web interface may see them: the key masked."""
    effective = llm_effective(root, environ)
    return {"llm": {
        "apiKeyMasked": mask(effective["apiKey"]),
        "hasApiKey": bool(effective["apiKey"]),
        "baseUrl": effective["baseUrl"],
        "model": effective["model"],
        "source": effective["source"],
        "envOverrides": effective["envOverrides"],
    }}


def _checked(field: str, value) -> str:
    """One field of a change, validated.  An empty string clears the field."""
    if not isinstance(value, str):
        raise SettingsError(f"llm.{field} must be a string")
    value = value.strip()
    if len(value) > MAX_LENGTH[field]:
        raise SettingsError(f"llm.{field} is longer than {MAX_LENGTH[field]} characters")
    if not value:
        return ""
    if field == "apiKey" and any(char.isspace() for char in value):
        raise SettingsError("llm.apiKey must not contain white space")
    if field == "baseUrl" and not re.match(r"^https?://[^\s/]+", value):
        raise SettingsError("llm.baseUrl must start with http:// or https://")
    if field == "model" and not MODEL_NAME.match(value):
        raise SettingsError("llm.model may use letters, digits and _ . : / @ + - only")
    return value.rstrip("/") if field == "baseUrl" else value


def update_llm(root: str | Path, changes: dict) -> None:
    """Change the fields *changes* names and keep everything else.

    An empty string clears a field; a field that is absent is kept.  Unknown
    fields are refused rather than silently dropped.
    """
    if not isinstance(changes, dict):
        raise SettingsError("llm must be a JSON object")
    unknown = sorted(set(changes) - set(LLM_FIELDS))
    if unknown:
        raise SettingsError(f"unknown llm field(s): {', '.join(unknown)}")
    checked = {field: _checked(field, value) for field, value in changes.items()}
    with _write_lock:
        whole = read_file(root)
        block = whole.get("llm") if isinstance(whole.get("llm"), dict) else {}
        block = {field: block[field] for field in LLM_FIELDS if isinstance(block.get(field), str)}
        block.update(checked)
        whole["llm"] = block
        _write_atomic(path(root), json.dumps(whole, indent=2) + "\n")


def _write_atomic(target: Path, text: str) -> None:
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise SettingsWriteError(f"could not write {FILE_NAME}: {error.strerror or type(error).__name__}") from None
