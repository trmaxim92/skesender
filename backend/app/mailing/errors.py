"""Classify mailing / Telegram / MAX provider errors for worker reactions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class MailingErrorKind(StrEnum):
    FLOOD_WAIT = "flood_wait"
    PEER_FLOOD = "peer_flood"
    ACCOUNT_BAN = "account_ban"
    AUTH_DEAD = "auth_dead"
    SLOW_MODE = "slow_mode"
    TRANSIENT = "transient"
    FATAL = "fatal"


_FLOOD_RE = re.compile(r"FloodWait[:\s]*(\d+)", re.I)
_SLOW_RE = re.compile(r"SlowModeWait[:\s]*(\d+)|wait of (\d+) seconds", re.I)

_PEER_FLOOD_MARKERS = (
    "peerflood",
    "peer_flood",
    "too many requests",
    "too many channels",
)
_ACCOUNT_BAN_MARKERS = (
    "userbannedinchannel",
    "user_banned_in_channel",
    "userbanned:",
    "chatwriteforbidden",
    "userisblocked",
    "youblockeduser",
)
_AUTH_DEAD_MARKERS = (
    "authkeyunregistered",
    "auth_key_unregistered",
    "authdead:",
    "sessionrevoked",
    "session_revoked",
    "userdeactivatedban",
    "user_deactivated_ban",
    "userdeactivated",
)


@dataclass(frozen=True)
class ClassifiedMailingError:
    kind: MailingErrorKind
    message: str
    wait_seconds: int | None = None


def classify_mailing_error(raw: str | None, *, exc_name: str | None = None) -> ClassifiedMailingError:
    text = (raw or "").strip() or "Ошибка отправки"
    blob = f"{exc_name or ''} {text}".lower().replace(" ", "")
    readable = text[:2000]

    flood = _FLOOD_RE.search(text)
    if flood or (exc_name or "") == "FloodWaitError":
        seconds = int(flood.group(1)) if flood else 30
        return ClassifiedMailingError(MailingErrorKind.FLOOD_WAIT, readable, max(1, seconds))

    slow = _SLOW_RE.search(text)
    if slow or "slowmode" in blob:
        groups = slow.groups() if slow else ()
        seconds = next((int(g) for g in groups if g), 30)
        return ClassifiedMailingError(MailingErrorKind.SLOW_MODE, readable, max(1, seconds))

    if any(m in blob for m in _PEER_FLOOD_MARKERS) or (exc_name or "") == "PeerFloodError":
        return ClassifiedMailingError(MailingErrorKind.PEER_FLOOD, readable, 6 * 3600)

    if any(m in blob for m in _AUTH_DEAD_MARKERS):
        return ClassifiedMailingError(MailingErrorKind.AUTH_DEAD, readable, 24 * 3600)

    if any(m in blob for m in _ACCOUNT_BAN_MARKERS) or (exc_name or "") in {
        "UserBannedInChannelError",
        "ChatWriteForbiddenError",
        "UserIsBlockedError",
    }:
        return ClassifiedMailingError(MailingErrorKind.ACCOUNT_BAN, readable, 12 * 3600)

    if any(x in blob for x in ("timeout", "connection", "temporary", "tryagain", "retry")):
        return ClassifiedMailingError(MailingErrorKind.TRANSIENT, readable, 60)

    return ClassifiedMailingError(MailingErrorKind.FATAL, readable)
