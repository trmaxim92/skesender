"""Unit tests for Channels ↔ Chats bottleneck fixes (C1–C12)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend/ is on path when pytest is run from repo root or backend/.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def test_credentials_cache_decrypts_once():
    from app.integrations.credentials_cache import decrypt_cached, invalidate

    invalidate()
    calls = {"n": 0}

    def decrypt(value: str) -> str:
        calls["n"] += 1
        return f"plain:{value}"

    a = decrypt_cached(1, "enc-aaa", decrypt=decrypt)
    b = decrypt_cached(1, "enc-aaa", decrypt=decrypt)
    assert a == b == "plain:enc-aaa"
    assert calls["n"] == 1

    c = decrypt_cached(1, "enc-bbb", decrypt=decrypt)
    assert c == "plain:enc-bbb"
    assert calls["n"] == 2

    d = decrypt_cached(2, "enc-aaa", decrypt=decrypt)
    assert d == "plain:enc-aaa"
    assert calls["n"] == 3


def test_channel_not_ready_error_shape():
    from app.integrations.base import ChannelNotReadyError, IntegrationError

    exc = ChannelNotReadyError("offline", retry_after=4)
    assert isinstance(exc, IntegrationError)
    assert exc.retry_after == 4
    assert "offline" in str(exc)


def test_vk_not_in_active_transports():
    pytest.importorskip("pymax")
    from app.integrations.registry import get_adapter, list_all_transports, list_transports
    from app.models import ChannelTransport

    active = list_transports()
    assert ChannelTransport.VK not in active
    assert ChannelTransport.TELEGRAM in active
    assert ChannelTransport.WEBCHAT in active
    assert ChannelTransport.VK in list_all_transports()
    assert get_adapter(ChannelTransport.VK).transport == ChannelTransport.VK


@pytest.mark.asyncio
async def test_telegram_ensure_client_fail_fast():
    pytest.importorskip("telethon")
    from app.integrations.base import ChannelNotReadyError
    from app.integrations.telegram_user.runtime import TelegramUserRuntime

    runtime = TelegramUserRuntime()
    with patch.object(runtime, "_restore_channel", new_callable=AsyncMock) as restore:
        with pytest.raises(ChannelNotReadyError) as exc:
            await runtime.ensure_client(42, wait=False)
        assert exc.value.retry_after == 3
        restore.assert_awaited()


@pytest.mark.asyncio
async def test_max_ensure_client_fail_fast():
    pytest.importorskip("pymax")
    from app.integrations.base import ChannelNotReadyError
    from app.integrations.max_personal.runtime import MaxPersonalRuntime

    runtime = MaxPersonalRuntime()
    with patch.object(runtime, "_restore_channel", new_callable=AsyncMock) as restore:
        with pytest.raises(ChannelNotReadyError) as exc:
            await runtime.ensure_client(7, wait=False)
        assert exc.value.retry_after == 3
        restore.assert_awaited()


@pytest.mark.asyncio
async def test_max_ensure_client_waits_then_ready():
    pytest.importorskip("pymax")
    from app.integrations.max_personal.runtime import MaxPersonalRuntime, RuntimeState

    runtime = MaxPersonalRuntime()
    state = RuntimeState(channel_id=9, status="reconnecting")
    # Keep task "running" so restore is not kicked repeatedly.
    state.task = asyncio.get_running_loop().create_future()
    runtime._states[9] = state
    client = object()

    async def become_online():
        await asyncio.sleep(0.3)
        state.status = "online"
        state.client = client  # type: ignore[assignment]

    asyncio.create_task(become_online())
    got = await runtime.ensure_client(9, wait=True, timeout=2.0)
    assert got is client
    state.task.cancel()


@pytest.mark.asyncio
async def test_max_soft_disconnect_keeps_db_online():
    pytest.importorskip("pymax")
    from app.integrations.max_personal.runtime import MaxPersonalRuntime, RuntimeState
    from app.models import ChannelStatus

    runtime = MaxPersonalRuntime()
    state = RuntimeState(channel_id=3, status="online", client=object())  # type: ignore[arg-type]
    state.task = asyncio.get_running_loop().create_future()
    runtime._states[3] = state

    with patch.object(runtime, "_update_channel", new_callable=AsyncMock) as upd:
        with patch.object(runtime, "_reconnect_later", new_callable=AsyncMock):
            await runtime._mark_disconnected(3, "socket blip")
        assert state.status == "reconnecting"
        assert state.client is None
        assert state.reconnect_generation == 1
        kwargs = upd.await_args.kwargs
        assert kwargs["status"] == ChannelStatus.ONLINE.value
        assert "Переподключение" in (kwargs.get("last_error") or "")
    state.task.cancel()


@pytest.mark.asyncio
async def test_telegram_stop_all_disconnect_timeout():
    pytest.importorskip("telethon")
    from app.integrations.telegram_user.runtime import RuntimeState, TelegramUserRuntime

    runtime = TelegramUserRuntime()
    client = MagicMock()

    async def hang_disconnect():
        await asyncio.sleep(30)

    client.disconnect = hang_disconnect
    state = RuntimeState(channel_id=1, status="online", client=client)
    runtime._states[1] = state

    await asyncio.wait_for(runtime.stop_all(), timeout=12)
    assert runtime._states == {}


@pytest.mark.asyncio
async def test_leader_tolerates_transient_redis_errors():
    from app.leader import BackgroundLeader

    stopped = {"n": 0}

    async def on_start():
        return None

    async def on_stop():
        stopped["n"] += 1

    leader = BackgroundLeader(on_start=on_start, on_stop=on_stop)
    leader._is_leader = True
    leader._redis_fail_streak = 0

    for _ in range(2):
        leader._redis_fail_streak += 1
        if leader._is_leader and leader._redis_fail_streak >= 3:
            await leader._relinquish()

    assert leader._is_leader is True
    assert stopped["n"] == 0
    assert leader._redis_fail_streak == 2


@pytest.mark.asyncio
async def test_leader_relinquish_after_fail_budget():
    from app.leader import BackgroundLeader

    stopped = {"n": 0}

    async def on_start():
        return None

    async def on_stop():
        stopped["n"] += 1

    leader = BackgroundLeader(on_start=on_start, on_stop=on_stop)
    leader._is_leader = True
    leader._redis_fail_streak = 0

    with patch("app.leader.redis_enabled", return_value=False):
        for _ in range(3):
            leader._redis_fail_streak += 1
            if leader._is_leader and leader._redis_fail_streak >= 3:
                await leader._relinquish()

    assert leader._is_leader is False
    assert stopped["n"] == 1


def test_http_for_channel_not_ready():
    pytest.importorskip("pymax")
    from fastapi import status

    from app.api.chats import _http_for_integration_error
    from app.integrations.base import ChannelNotReadyError

    exc = ChannelNotReadyError("offline", retry_after=4)
    http = _http_for_integration_error(exc)
    assert http.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert http.headers.get("Retry-After") == "4"


def test_poller_has_semaphore():
    from app.integrations.maxbot.poller import MaxBotPoller
    from app.integrations.telegram_bot.poller import TelegramBotPoller

    tg = TelegramBotPoller()
    mx = MaxBotPoller()
    assert tg._sem._value == 8
    assert mx._sem._value == 8


@pytest.mark.asyncio
async def test_media_job_schedules_and_swallows_errors():
    from app.integrations import media_jobs

    media_jobs._pending.clear()
    ran = {"ok": False}

    async def boom():
        ran["ok"] = True
        raise RuntimeError("download failed")

    media_jobs.schedule_media_job(boom(), name="test-job")
    await media_jobs.wait_media_jobs(timeout=2)
    assert ran["ok"] is True


def test_dialog_indexes_declared():
    from app.models import Dialog

    names = {idx.name for idx in Dialog.__table__.indexes}
    assert "ix_dialogs_assignee_last_at" in names
    assert "ix_dialogs_department_last_at" in names
