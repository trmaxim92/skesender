from __future__ import annotations

import re

from app.models import MailingRecipientKind

_PHONE_RE = re.compile(r"^\+?\d{10,15}$")
_USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_]{3,64}$")


def normalize_recipient(raw: str) -> tuple[str, str]:
    """Return (normalized, kind)."""
    value = (raw or "").strip()
    if not value:
        return "", MailingRecipientKind.UNKNOWN.value

    # strip csv leftovers
    value = value.split(",")[0].strip().strip('"').strip("'")
    if not value:
        return "", MailingRecipientKind.UNKNOWN.value

    phone_candidate = value.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone_candidate.startswith("00"):
        phone_candidate = "+" + phone_candidate[2:]
    if _PHONE_RE.match(phone_candidate):
        if not phone_candidate.startswith("+"):
            phone_candidate = "+" + phone_candidate
        return phone_candidate, MailingRecipientKind.PHONE.value

    username = value.lstrip("@").strip()
    if _USERNAME_RE.match("@" + username if not username.startswith("@") else username) or _USERNAME_RE.match(
        username
    ):
        return username.lstrip("@").lower(), MailingRecipientKind.USERNAME.value

    return value, MailingRecipientKind.UNKNOWN.value


def parse_recipients_text(text: str) -> list[tuple[str, str, str]]:
    """Parse multiline text into list of (raw, normalized, kind), unique by normalized."""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for line in (text or "").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        normalized, kind = normalize_recipient(raw)
        if not normalized:
            continue
        key = f"{kind}:{normalized}"
        if key in seen:
            continue
        seen.add(key)
        out.append((raw, normalized, kind))
    return out
