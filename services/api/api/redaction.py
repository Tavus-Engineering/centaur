"""Runtime payload redaction helpers."""

from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d(). -]{8,}\d)(?!\w)")
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Z0-9._~+/=-]+")
_FIELD_SPLIT_RE = re.compile(r"(?<!^)(?=[A-Z])|[^A-Za-z0-9]+")
_SECRET_FIELD_TOKENS = {
    "auth",
    "credential",
    "password",
    "secret",
    "token",
}
_SECRET_FIELD_NAMES = {
    "accesskey",
    "apikey",
    "authorization",
    "clientsecret",
    "cookie",
    "privatekey",
    "accesstoken",
    "refreshtoken",
}
_EMAIL_FIELD_NAMES = {"email", "useremail", "authoremail"}
_PHONE_FIELD_NAMES = {"phone", "phonenumber", "userphone"}
_SSN_FIELD_NAMES = {"ssn", "socialsecuritynumber"}
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(?P<name>[A-Z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?KEY|AUTH|"
    r"CREDENTIAL|COOKIE|PASSWORD|PRIVATE[_-]?KEY|SECRET|TOKEN)[A-Z0-9_]*)"
    r"(?P<sep>\s*=\s*)"
    r"(?P<value>[^\s\r\n]+)"
)
_SECRET_HEADER_RE = re.compile(
    r"(?im)\b(?P<name>[A-Za-z0-9_-]*(?:api[-_]?key|apikey|authorization|"
    r"cookie|credential|password|private[-_]?key|secret|token)[A-Za-z0-9_-]*)"
    r"(?P<sep>\s*:\s*)"
    r"(?P<value>[^\s,;}]+)"
)
_SECRET_QUERY_RE = re.compile(
    r"(?i)(?P<prefix>[?&](?:api[_-]?key|apikey|access[_-]?key|auth|"
    r"password|secret|token)=)(?P<value>[^&#\s]+)"
)


def _normalize_field_name(field_name: str | None) -> str:
    if not field_name:
        return ""
    return re.sub(r"[^a-z0-9]", "", field_name.casefold())


def _field_tokens(field_name: str | None) -> set[str]:
    if not field_name:
        return set()
    return {part.casefold() for part in _FIELD_SPLIT_RE.split(field_name) if part}


def _redact_phone_match(match: re.Match[str]) -> str:
    candidate = match.group(0)
    digits = sum(ch.isdigit() for ch in candidate)
    if 10 <= digits <= 15 and ":" not in candidate:
        return "[REDACTED:phone]"
    return candidate


def _redact_secret_assignment(match: re.Match[str]) -> str:
    return f"{match.group('name')}{match.group('sep')}[REDACTED:secret]"


def _redact_secret_query_param(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}[REDACTED:secret]"


def sanitize_runtime_string(value: str) -> str:
    """Redact common secret and PII shapes in free-form runtime output."""
    sanitized = _BEARER_TOKEN_RE.sub("Bearer [REDACTED:secret]", value)
    sanitized = _SECRET_ASSIGNMENT_RE.sub(_redact_secret_assignment, sanitized)
    sanitized = _SECRET_HEADER_RE.sub(_redact_secret_assignment, sanitized)
    sanitized = _SECRET_QUERY_RE.sub(_redact_secret_query_param, sanitized)
    sanitized = _EMAIL_RE.sub("[REDACTED:email]", sanitized)
    sanitized = _SSN_RE.sub("[REDACTED:ssn]", sanitized)
    return _PHONE_CANDIDATE_RE.sub(_redact_phone_match, sanitized)


def sanitize_runtime_value(value: Any, *, field_name: str | None = None) -> Any:
    """Recursively redact secrets/PII while preserving non-sensitive structure."""
    normalized_field = _normalize_field_name(field_name)
    field_tokens = _field_tokens(field_name)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {k: sanitize_runtime_value(v, field_name=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_runtime_value(item, field_name=field_name) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_runtime_value(item, field_name=field_name) for item in value)
    if isinstance(value, str):
        if normalized_field in _SECRET_FIELD_NAMES or field_tokens & _SECRET_FIELD_TOKENS:
            return "[REDACTED:secret]"
        if normalized_field in _EMAIL_FIELD_NAMES or "email" in field_tokens:
            return "[REDACTED:email]"
        if normalized_field in _PHONE_FIELD_NAMES or "phone" in field_tokens:
            return "[REDACTED:phone]"
        if normalized_field in _SSN_FIELD_NAMES or "ssn" in field_tokens:
            return "[REDACTED:ssn]"
        return sanitize_runtime_string(value)
    return value
