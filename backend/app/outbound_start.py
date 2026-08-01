"""Resolve a recipient and prepare outbound dialog start."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.mailing.recipients import normalize_recipient
from app.models import Channel, ChannelTransport, MailingRecipientKind


class PeerResolveError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class ResolvedPeer:
    external_chat_id: str
    contact_external_id: str | None
    contact_name: str
    contact_username: str | None
    contact_phone: str | None = None


_START_TRANSPORTS = {
    ChannelTransport.TELEGRAM.value,
    ChannelTransport.TGAPI.value,
    ChannelTransport.MAXBOT.value,
    ChannelTransport.MAX.value,
}


def transport_allows_start(transport: str) -> bool:
    return transport in _START_TRANSPORTS


def _digits(value: str) -> str:
    return value.lstrip("+").lstrip("-")


async def resolve_outbound_peer(
    channel: Channel,
    recipient: str,
    db: AsyncSession | None = None,
) -> ResolvedPeer:
    normalized, kind = normalize_recipient(recipient)
    if not normalized:
        raise PeerResolveError("Укажите получателя")

    transport = channel.transport if isinstance(channel.transport, str) else channel.transport.value

    if transport == ChannelTransport.TGAPI.value:
        return await _resolve_tgapi(channel, normalized, kind)
    if transport == ChannelTransport.TELEGRAM.value:
        return await _resolve_telegram_bot(channel, normalized, kind, db)
    if transport == ChannelTransport.MAX.value:
        return await _resolve_max_personal(channel, normalized, kind)
    if transport == ChannelTransport.MAXBOT.value:
        return _resolve_maxbot_numeric(normalized, kind)
    raise PeerResolveError(f"Транспорт {transport} не поддерживает исходящий старт")


async def _resolve_telegram_bot(
    channel: Channel,
    normalized: str,
    kind: str,
    db: AsyncSession | None,
) -> ResolvedPeer:
    """Bot API needs numeric chat_id for DMs — bare @username usually fails."""
    if kind == MailingRecipientKind.PHONE.value or _looks_like_ru_phone(normalized, kind):
        raise PeerResolveError(
            "Telegram-бот не пишет по телефону — укажите @username или user id. "
            "Для номера выберите канал «Telegram · аккаунт»."
        )

    digits = _digits(normalized)
    if digits.isdigit() and kind != MailingRecipientKind.USERNAME.value:
        return ResolvedPeer(
            external_chat_id=digits,
            contact_external_id=digits,
            contact_name=digits,
            contact_username=None,
        )

    username = normalized.lstrip("@").lower()
    if not username:
        raise PeerResolveError("Укажите @username или числовой user/chat id")

    if db is not None:
        found = await _find_telegram_dialog_by_username(db, channel.id, username)
        if found is not None:
            return found

    if channel.credentials_enc:
        try:
            from app.integrations.telegram_bot import client as tg_client
            from app.security import decrypt_secret

            token = decrypt_secret(channel.credentials_enc)
            chat = await tg_client.get_chat(token, f"@{username}")
            chat_id = chat.get("id")
            if chat_id is not None:
                title = (
                    f"{chat.get('first_name') or ''} {chat.get('last_name') or ''}".strip()
                    or chat.get("title")
                    or username
                )
                return ResolvedPeer(
                    external_chat_id=str(chat_id),
                    contact_external_id=str(chat_id),
                    contact_name=str(title),
                    contact_username=username,
                )
        except Exception:
            pass

    raise PeerResolveError(
        f"Бот не знает личный чат @{username}. Bot API не принимает @логин для лички — "
        f"нужен числовой chat id. Напишите боту /start с @{username} (диалог появится в «Чатах»), "
        f"затем создайте обращение снова, либо укажите user id, "
        f"либо используйте канал «Telegram · аккаунт»."
    )


async def _find_telegram_dialog_by_username(
    db: AsyncSession,
    channel_id: int,
    username: str,
) -> ResolvedPeer | None:
    from sqlalchemy import func, or_, select

    from app.models import Dialog

    uname = username.lower().lstrip("@")
    result = await db.execute(
        select(Dialog)
        .where(
            Dialog.channel_id == channel_id,
            or_(
                func.lower(Dialog.contact_username) == uname,
                func.lower(Dialog.contact_name) == f"@{uname}",
                func.lower(Dialog.contact_name) == uname,
            ),
        )
        .order_by(Dialog.last_at.desc())
        .limit(1)
    )
    dialog = result.scalar_one_or_none()
    if dialog is None:
        return None
    ext = (dialog.external_chat_id or "").strip()
    if not ext or ext.startswith("@"):
        return None
    return ResolvedPeer(
        external_chat_id=ext,
        contact_external_id=dialog.contact_external_id or ext,
        contact_name=dialog.contact_name or uname,
        contact_username=dialog.contact_username or uname,
    )


def _looks_like_ru_phone(normalized: str, kind: str) -> bool:
    if kind == MailingRecipientKind.PHONE.value:
        return True
    digits = _digits(normalized)
    if not digits.isdigit():
        return False
    if len(digits) == 11 and digits.startswith(("7", "8")):
        return True
    if len(digits) == 10 and digits.startswith("9"):
        return True
    return False


def _to_e164_ru(normalized: str) -> str:
    digits = _digits(normalized)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits.startswith("9"):
        digits = "7" + digits
    return f"+{digits}"


def _name_from_max_user(user: object) -> str:
    names = getattr(user, "names", None) or []
    for n in names:
        first = (getattr(n, "first_name", None) or "").strip()
        last = (getattr(n, "last_name", None) or "").strip()
        full = f"{first} {last}".strip()
        if full:
            return full
        plain = (getattr(n, "name", None) or "").strip()
        if plain:
            return plain
    phone = getattr(user, "phone", None)
    if phone:
        return str(phone)
    uid = getattr(user, "id", None)
    return f"User {uid}" if uid is not None else "Клиент"


def _resolve_maxbot_numeric(normalized: str, kind: str) -> ResolvedPeer:
    if kind == MailingRecipientKind.USERNAME.value:
        raise PeerResolveError(
            "MAX · бот: укажите числовой user id (логин не поддерживается)"
        )
    if kind == MailingRecipientKind.PHONE.value or _looks_like_ru_phone(normalized, kind):
        raise PeerResolveError(
            "MAX · бот не умеет искать по телефону — нужен числовой user id. "
            "Для звонка по номеру выберите канал «MAX · аккаунт»."
        )
    digits = _digits(normalized)
    if not digits.isdigit():
        raise PeerResolveError("MAX · бот: нужен числовой user id")
    return ResolvedPeer(
        external_chat_id=digits,
        contact_external_id=digits,
        contact_name=digits,
        contact_username=None,
    )


async def _resolve_max_personal(channel: Channel, normalized: str, kind: str) -> ResolvedPeer:
    """Phone → search_by_phone → user_id → chat_id = me XOR peer."""
    from app.integrations.max_personal.runtime import runtime

    if kind == MailingRecipientKind.USERNAME.value:
        raise PeerResolveError("MAX · аккаунт: укажите телефон или user id (логин не поддерживается)")

    try:
        client = await runtime.ensure_client(channel.id)
    except Exception as exc:
        raise PeerResolveError(str(exc)) from exc

    me = getattr(getattr(client, "me", None), "contact", None)
    my_id = getattr(me, "id", None)
    if my_id is None:
        raise PeerResolveError("MAX-аккаунт ещё не готов (нет профиля)")

    phone: str | None = None
    user = None
    if _looks_like_ru_phone(normalized, kind):
        phone = _to_e164_ru(normalized)
        try:
            user = await client.search_by_phone(phone)
        except Exception as exc:
            raise PeerResolveError(f"Не удалось найти в MAX по телефону {phone}: {exc}") from exc
    else:
        digits = _digits(normalized)
        if not digits.isdigit():
            raise PeerResolveError("MAX · аккаунт: укажите телефон (+7…) или user id")
        uid = int(digits)
        try:
            user = await client.get_user(uid)
        except Exception:
            user = None
        if user is None:
            # Уже chat_id (как в inbound) — peer = chat XOR me
            peer_guess = int(uid) ^ int(my_id)
            return ResolvedPeer(
                external_chat_id=str(uid),
                contact_external_id=str(peer_guess),
                contact_name=str(peer_guess),
                contact_username=None,
            )

    peer_id = int(getattr(user, "id"))
    try:
        await client.add_contact(peer_id)
    except Exception:
        # Уже в контактах / API отказал — пробуем писать всё равно
        pass

    chat_id = int(client.get_chat_id(int(my_id), peer_id))
    name = _name_from_max_user(user)
    stored_phone = phone
    if stored_phone is None and getattr(user, "phone", None) is not None:
        stored_phone = str(user.phone)
    return ResolvedPeer(
        external_chat_id=str(chat_id),
        contact_external_id=str(peer_id),
        contact_name=name,
        contact_username=None,
        contact_phone=stored_phone,
    )


async def _resolve_tgapi(channel: Channel, normalized: str, kind: str) -> ResolvedPeer:
    """Accept exactly one of: phone, @username, or numeric user id."""
    from telethon.errors import FloodWaitError, UsernameInvalidError, UsernameNotOccupiedError
    from telethon.tl.functions.contacts import ImportContactsRequest
    from telethon.tl.types import InputPhoneContact

    from app.integrations.telegram_user.runtime import runtime

    try:
        client = await runtime.ensure_client(channel.id)
    except Exception as exc:
        raise PeerResolveError(str(exc)) from exc

    digits = _digits(normalized)
    phone: str | None = None

    try:
        # 1) @username
        if kind == MailingRecipientKind.USERNAME.value or (
            not digits.isdigit() and kind != MailingRecipientKind.PHONE.value
        ):
            username = normalized.lstrip("@").lower()
            try:
                entity = await client.get_entity(username)
            except (UsernameInvalidError, UsernameNotOccupiedError):
                entity = await client.get_entity(f"@{username}")
        # 2) phone → resolve to user id
        elif _looks_like_ru_phone(normalized, kind):
            phone = _to_e164_ru(normalized)
            contact = InputPhoneContact(
                client_id=0,
                phone=phone.lstrip("+"),
                first_name=phone,
                last_name="",
            )
            result = await client(ImportContactsRequest([contact]))
            users = getattr(result, "users", None) or []
            if users:
                entity = users[0]
            else:
                try:
                    entity = await client.get_entity(phone)
                except Exception as exc:
                    raise PeerResolveError(
                        f"Не удалось найти в Telegram по телефону {phone}"
                    ) from exc
        # 3) numeric user id
        elif digits.isdigit():
            entity = await client.get_entity(int(digits))
        else:
            raise PeerResolveError("Укажите телефон, @username или user id")
    except FloodWaitError as exc:
        raise PeerResolveError(f"FloodWait:{exc.seconds}") from exc
    except PeerResolveError:
        raise
    except Exception as exc:
        raise PeerResolveError(f"Не удалось найти получателя в Telegram: {exc}") from exc

    uid = getattr(entity, "id", None)
    if uid is None:
        raise PeerResolveError("Telegram не вернул id получателя")
    username = getattr(entity, "username", None)
    first = (getattr(entity, "first_name", None) or "").strip()
    last = (getattr(entity, "last_name", None) or "").strip()
    name = f"{first} {last}".strip() or (username or str(uid))
    stored_phone = phone
    entity_phone = getattr(entity, "phone", None)
    if stored_phone is None and entity_phone:
        stored_phone = str(entity_phone)
        if stored_phone and not stored_phone.startswith("+"):
            stored_phone = f"+{stored_phone}"
    return ResolvedPeer(
        external_chat_id=str(uid),
        contact_external_id=str(uid),
        contact_name=name,
        contact_username=username.lower() if isinstance(username, str) and username else None,
        contact_phone=stored_phone,
    )
