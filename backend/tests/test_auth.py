"""Auth / session unit tests (JWT version, login presence, password rotate)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


@pytest.fixture(autouse=True)
def _auth_settings(monkeypatch):
    """Stable SECRET_KEY for JWT encode/decode in unit tests."""
    monkeypatch.setenv("SECRET_KEY", "unit-test-secret-key-32chars!!")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("DEBUG", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_token_version_matches():
    from app.security import token_version_matches

    assert token_version_matches({"ver": 0}, 0) is True
    assert token_version_matches({"ver": 3}, 3) is True
    assert token_version_matches({"ver": 2}, 3) is False
    assert token_version_matches({}, 0) is True  # missing claim → 0
    assert token_version_matches({"ver": "1"}, 1) is True
    assert token_version_matches({"ver": "x"}, 0) is True
    assert token_version_matches({"ver": "x"}, 1) is False


def test_access_token_roundtrip_includes_ver():
    from app.security import create_access_token, decode_access_token, token_version_matches

    token = create_access_token("ops@example.com", "operator", token_version=5)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "ops@example.com"
    assert payload["role"] == "operator"
    assert int(payload["ver"]) == 5
    assert token_version_matches(payload, 5) is True
    assert token_version_matches(payload, 6) is False


def test_decode_access_token_rejects_garbage():
    from app.security import decode_access_token

    assert decode_access_token("not-a-jwt") is None


def test_should_promote_to_online_on_login():
    from app.models import PresenceStatusSlug
    from app.presence import should_promote_to_online_on_login

    assert should_promote_to_online_on_login(None) is True
    assert should_promote_to_online_on_login(PresenceStatusSlug.OFFLINE.value) is True
    assert should_promote_to_online_on_login(PresenceStatusSlug.ONLINE.value) is False
    assert should_promote_to_online_on_login(PresenceStatusSlug.TRAINING.value) is False
    assert should_promote_to_online_on_login("custom-break") is False


@pytest.mark.asyncio
async def test_change_password_returns_fresh_token_with_new_ver():
    from app.api import auth as auth_api
    from app.schemas import ChangePasswordRequest
    from app.security import decode_access_token, hash_password, verify_password

    user = SimpleNamespace(
        id=11,
        email="ops@example.com",
        role="operator",
        password_hash=hash_password("old-secret"),
        token_version=2,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=user)
    db.commit = AsyncMock()

    body = ChangePasswordRequest(current_password="old-secret", new_password="new-secret")
    caller = SimpleNamespace(id=11)

    with patch.object(auth_api, "hub") as hub:
        hub.disconnect_user = AsyncMock()
        result = await auth_api.change_my_password(body, caller, db)  # type: ignore[arg-type]

    hub.disconnect_user.assert_awaited_once_with(11)
    db.commit.assert_awaited()
    assert user.token_version == 3
    assert verify_password("new-secret", user.password_hash)
    assert result.access_token
    payload = decode_access_token(result.access_token)
    assert payload is not None
    assert payload["sub"] == "ops@example.com"
    assert int(payload["ver"]) == 3


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current():
    from app.api import auth as auth_api
    from app.schemas import ChangePasswordRequest
    from app.security import hash_password
    from fastapi import HTTPException

    user = SimpleNamespace(
        id=11,
        email="ops@example.com",
        role="operator",
        password_hash=hash_password("old-secret"),
        token_version=2,
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=user)
    body = ChangePasswordRequest(current_password="wrong", new_password="new-secret")

    with pytest.raises(HTTPException) as exc:
        await auth_api.change_my_password(body, SimpleNamespace(id=11), db)  # type: ignore[arg-type]
    assert exc.value.status_code == 400
    assert user.token_version == 2


@pytest.mark.asyncio
async def test_login_promotes_only_offline_to_online():
    from app.api import auth as auth_api
    from app.models import PresenceStatusSlug
    from app.schemas import LoginRequest
    from app.security import hash_password

    online = SimpleNamespace(id=1, slug=PresenceStatusSlug.ONLINE.value)
    offline = SimpleNamespace(id=2, slug=PresenceStatusSlug.OFFLINE.value)
    training = SimpleNamespace(id=3, slug=PresenceStatusSlug.TRAINING.value)

    async def run_login(*, presence, expect_promote: bool):
        user = SimpleNamespace(
            id=5,
            email="a@b.c",
            role="operator",
            password_hash=hash_password("pass1234"),
            token_version=0,
            is_active=True,
            presence_status=presence,
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        db = AsyncMock()
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        request = MagicMock()
        request.headers = {}
        request.client = SimpleNamespace(host="127.0.0.1")

        with (
            patch.object(auth_api, "limiter") as lim,
            patch.object(auth_api, "get_status_by_slug", new_callable=AsyncMock) as get_slug,
            patch.object(auth_api, "set_user_presence", new_callable=AsyncMock) as set_pres,
        ):
            lim.check = AsyncMock()
            get_slug.return_value = online
            body = LoginRequest(email="a@b.c", password="pass1234")
            out = await auth_api.login(body, request, db)
            assert out.access_token
            if expect_promote:
                get_slug.assert_awaited()
                set_pres.assert_awaited()
                db.commit.assert_awaited()
            else:
                set_pres.assert_not_awaited()

    await run_login(presence=None, expect_promote=True)
    await run_login(presence=offline, expect_promote=True)
    await run_login(presence=training, expect_promote=False)
    await run_login(presence=online, expect_promote=False)
