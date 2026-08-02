from __future__ import annotations

from app.integrations.base import ChannelAdapter
from app.integrations.maxbot.adapter import MaxBotAdapter
from app.integrations.max_personal.adapter import MaxPersonalAdapter
from app.integrations.telegram_bot.adapter import TelegramBotAdapter
from app.integrations.telegram_user.adapter import TelegramUserAdapter
from app.integrations.vk.adapter import VkAdapter
from app.integrations.webchat.adapter import WebchatAdapter
from app.models import ChannelTransport

_adapters: dict[ChannelTransport, ChannelAdapter] = {
    ChannelTransport.MAXBOT: MaxBotAdapter(),
    ChannelTransport.MAX: MaxPersonalAdapter(),
    ChannelTransport.TELEGRAM: TelegramBotAdapter(),
    ChannelTransport.TGAPI: TelegramUserAdapter(),
    ChannelTransport.VK: VkAdapter(),
    ChannelTransport.WEBCHAT: WebchatAdapter(),
}


def get_adapter(transport: ChannelTransport | str) -> ChannelAdapter:
    key = ChannelTransport(transport) if isinstance(transport, str) else transport
    try:
        return _adapters[key]
    except KeyError as exc:
        raise KeyError(f"No adapter registered for transport={key}") from exc


def list_transports() -> list[ChannelTransport]:
    return list(_adapters.keys())
