from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MailingSendResult:
    ok: bool
    external_id: str | None = None
    error: str | None = None
