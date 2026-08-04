"""Render mailing template body with placeholders and variants."""

from __future__ import annotations

import re

from app.models import MailingRecipient, MailingRecipientKind

_VARIANT_SPLIT = re.compile(r"\n---+\n")


def split_body_variants(body: str) -> list[str]:
    text = body or ""
    parts = [p.strip() for p in _VARIANT_SPLIT.split(text)]
    variants = [p for p in parts if p]
    return variants or [text]


def pick_body_variant(body: str, recipient_id: int) -> str:
    variants = split_body_variants(body)
    if len(variants) == 1:
        return variants[0]
    return variants[int(recipient_id) % len(variants)]


def render_mailing_body(body: str, recipient: MailingRecipient) -> str:
    chosen = pick_body_variant(body, recipient.id)
    username = ""
    phone = ""
    if recipient.kind == MailingRecipientKind.USERNAME.value:
        username = recipient.normalized or ""
    elif recipient.kind == MailingRecipientKind.PHONE.value:
        phone = recipient.normalized or ""
    raw = recipient.raw or recipient.normalized or ""
    mapping = {
        "username": username or raw.lstrip("@"),
        "phone": phone or raw,
        "raw": raw,
        "name": username or phone or raw.lstrip("@"),
    }
    out = chosen
    for key, value in mapping.items():
        out = out.replace("{{" + key + "}}", value)
        out = out.replace("{{ " + key + " }}", value)
    return out
