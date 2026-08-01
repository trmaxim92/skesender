from __future__ import annotations

from app.mailing.senders.max_personal import MaxPersonalMailingSender
from app.mailing.senders.maxbot import MaxBotMailingSender
from app.mailing.senders.telegram import TelegramBotMailingSender
from app.mailing.senders.tgapi import TelegramUserMailingSender
from app.mailing.senders.vk import VkMailingSender
from app.mailing.types import MailingSendResult
from app.models import Channel, MailingTemplate
from app.outbound_start import ResolvedPeer

_SENDERS = {
    "tgapi": TelegramUserMailingSender(),
    "telegram": TelegramBotMailingSender(),
    "maxbot": MaxBotMailingSender(),
    "max": MaxPersonalMailingSender(),
    "vk": VkMailingSender(),
}


def get_mailing_sender(transport: str):
    sender = _SENDERS.get(transport)
    if sender is None:
        raise KeyError(f"No mailing sender for transport={transport}")
    return sender


async def send_mailing(
    channel: Channel,
    *,
    peer: ResolvedPeer,
    template: MailingTemplate,
    media_bytes: bytes | None,
) -> MailingSendResult:
    sender = get_mailing_sender(channel.transport)
    return await sender.send(
        channel,
        peer=peer,
        template=template,
        media_bytes=media_bytes,
    )
