from __future__ import annotations

from app.integrations.base import ChannelAdapter
from app.integrations.maxbot.adapter import MaxBotAdapter
from app.integrations.max_personal.adapter import MaxPersonalAdapter
from app.integrations.telegram_bot.adapter import TelegramBotAdapter
from app.integrations.telegram_user.adapter import TelegramUserAdapter
from app.integrations.vk.adapter import VkAdapter
from app.integrations.webchat.adapter import WebchatAdapter
from app.models import ChannelTransport

# Active transports started as background workers.
_adapters: dict[ChannelTransport, ChannelAdapter] = {
    ChannelTransport.MAXBOT: MaxBotAdapter(),
    ChannelTransport.MAX: MaxPersonalAdapter(),
    ChannelTransport.TELEGRAM: TelegramBotAdapter(),
    ChannelTransport.TGAPI: TelegramUserAdapter(),
    ChannelTransport.WEBCHAT: WebchatAdapter(),
}

# Stubs kept for lookup / future enablement — not started as workers (C12).
_stub_adapters: dict[ChannelTransport, ChannelAdapter] = {
    ChannelTransport.VK: VkAdapter(),
}


def get_adapter(transport: ChannelTransport | str) -> ChannelAdapter:
    key = ChannelTransport(transport) if isinstance(transport, str) else transport
    try:
        return _adapters[key]
    except KeyError:
        pass
    try:
        return _stub_adapters[key]
    except KeyError as exc:
        raise KeyError(f"No adapter registered for transport={key}") from exc


def list_transports() -> list[ChannelTransport]:
    """Transports with active workers (excludes stubs like VK)."""
    return list(_adapters.keys())


def list_all_transports() -> list[ChannelTransport]:
    return [*_adapters.keys(), *_stub_adapters.keys()]
