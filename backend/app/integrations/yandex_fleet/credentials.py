from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FleetCredentials:
    client_id: str
    api_key: str
    park_id: str
    source: str  # "db" | "env"
