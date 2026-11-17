"""Redaction helpers: audit records and run logs must never hold secrets."""
from __future__ import annotations

import re
from typing import Any, Iterable

MASK = "***REDACTED***"
SECRET_KEY_RE = re.compile(
    r"pass(word|wd|phrase)?|secret|token|api[_-]?key|private[_-]?key|community|credential|auth",
    re.IGNORECASE,
)


def is_secret_name(name: str) -> bool:
    return bool(SECRET_KEY_RE.search(name))


def redact(value: Any) -> Any:
    """Recursively mask values whose key looks secret-like."""
    if isinstance(value, dict):
        return {k: (MASK if is_secret_name(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def scrub_text(text: str, secrets_to_hide: Iterable[str] = ()) -> str:
    """Remove known secret values and obvious `key=value` secret pairs from free text."""
    for s in secrets_to_hide:
        if s and len(s) >= 3:
            text = text.replace(s, MASK)
    return re.sub(
        r"(?i)\b(pass(?:word|wd)?|secret|token|api[_-]?key|community)\b(\s*[=:]\s*)\S+",
        lambda m: f"{m.group(1)}{m.group(2)}{MASK}",
        text,
    )
