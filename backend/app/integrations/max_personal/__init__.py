"""MAX personal account integration (PyMax WebClient + QR)."""

from app.integrations.max_personal.adapter import MaxPersonalAdapter
from app.integrations.max_personal.runtime import runtime

__all__ = ["MaxPersonalAdapter", "runtime"]
