"""MAX Bot API integration (official platform-api2.max.ru)."""

from app.integrations.maxbot.adapter import MaxBotAdapter
from app.integrations.maxbot.poller import poller

__all__ = ["MaxBotAdapter", "poller"]
