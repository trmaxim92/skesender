import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import api_router
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.integrations.registry import get_adapter, list_transports
import app.models  # noqa: F401 — register ORM metadata
from app.seed import seed_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def ensure_schema() -> None:
    # Bootstrap / legacy patches. New durable changes should go through Alembic
    # (see backend/alembic). Stamp existing DBs: `alembic stamp 0001_baseline`.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE channels ADD COLUMN IF NOT EXISTS poll_marker BIGINT")
        )
        await conn.execute(
            text(
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS reply_to_message_id "
                "INTEGER REFERENCES messages(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_messages_reply_to_message_id "
                "ON messages (reply_to_message_id)"
            )
        )
        await conn.execute(
            text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS edited_at TIMESTAMPTZ")
        )
        await conn.execute(
            text("ALTER TABLE messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
        )
        await conn.execute(
            text("ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS last_direction VARCHAR(8)")
        )
        await conn.execute(
            text("ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS last_status VARCHAR(16)")
        )
        await conn.execute(
            text("ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS contact_avatar_url TEXT")
        )
        await conn.execute(
            text(
                """
                UPDATE dialogs AS d
                SET last_direction = m.direction,
                    last_status = m.status
                FROM (
                    SELECT DISTINCT ON (dialog_id)
                        dialog_id, direction, status
                    FROM messages
                    WHERE deleted_at IS NULL
                    ORDER BY dialog_id, created_at DESC, id DESC
                ) AS m
                WHERE d.id = m.dialog_id
                  AND (d.last_direction IS NULL OR d.last_status IS NULL)
                """
            )
        )
        await conn.execute(
            text("ALTER TABLE templates ADD COLUMN IF NOT EXISTS kind VARCHAR(32) DEFAULT 'general'")
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS template_categories (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_by_id INTEGER NOT NULL REFERENCES users(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_template_categories_created_by_id "
                "ON template_categories (created_by_id)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE templates ADD COLUMN IF NOT EXISTS category_id "
                "INTEGER REFERENCES template_categories(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_templates_category_id ON templates (category_id)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS appeals (
                    id SERIAL PRIMARY KEY,
                    dialog_id INTEGER NOT NULL REFERENCES dialogs(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL DEFAULT 1,
                    status VARCHAR(16) NOT NULL DEFAULT 'open',
                    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    closed_at TIMESTAMPTZ,
                    closed_by_id INTEGER REFERENCES users(id),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_appeal_dialog_number UNIQUE (dialog_id, number)
                )
                """
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_appeals_dialog_id ON appeals (dialog_id)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_appeals_status ON appeals (status)")
        )
        await conn.execute(
            text(
                "ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS current_appeal_id "
                "INTEGER REFERENCES appeals(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_dialogs_current_appeal_id "
                "ON dialogs (current_appeal_id)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS appeal_id "
                "INTEGER REFERENCES appeals(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_messages_appeal_id ON messages (appeal_id)")
        )
        # Backfill: one open appeal per dialog without current_appeal.
        await conn.execute(
            text(
                """
                INSERT INTO appeals (dialog_id, number, status, opened_at, created_at)
                SELECT d.id, 1, 'open', COALESCE(d.created_at, NOW()), COALESCE(d.created_at, NOW())
                FROM dialogs d
                WHERE d.current_appeal_id IS NULL
                  AND NOT EXISTS (SELECT 1 FROM appeals a WHERE a.dialog_id = d.id)
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE dialogs d
                SET current_appeal_id = a.id
                FROM appeals a
                WHERE a.dialog_id = d.id
                  AND a.number = 1
                  AND d.current_appeal_id IS NULL
                """
            )
        )
        await conn.execute(
            text(
                """
                UPDATE messages m
                SET appeal_id = d.current_appeal_id
                FROM dialogs d
                WHERE m.dialog_id = d.id
                  AND m.appeal_id IS NULL
                  AND d.current_appeal_id IS NOT NULL
                """
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS access_role_id "
                "INTEGER REFERENCES access_roles(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_users_access_role_id ON users (access_role_id)")
        )
        await conn.execute(
            text(
                "ALTER TABLE channels ADD COLUMN IF NOT EXISTS department_id "
                "INTEGER REFERENCES departments(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_channels_department_id ON channels (department_id)")
        )
        await conn.execute(
            text(
                "ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS department_id "
                "INTEGER REFERENCES departments(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_dialogs_department_id ON dialogs (department_id)")
        )
        await conn.execute(
            text("ALTER TABLE dialogs ADD COLUMN IF NOT EXISTS contact_phone VARCHAR(64)")
        )
        await conn.execute(
            text(
                "ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_internal "
                "BOOLEAN NOT NULL DEFAULT FALSE"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_messages_is_internal ON messages (is_internal)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_field_def_client_key
                ON field_definitions (key) WHERE scope = 'client'
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_field_def_appeal_dept_key
                ON field_definitions (department_id, key) WHERE scope = 'appeal'
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_messages_dialog_created_id
                ON messages (dialog_id, created_at, id)
                """
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version "
                "INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS webhook_outbox (
                    id SERIAL PRIMARY KEY,
                    webhook_id INTEGER NOT NULL
                        REFERENCES outbound_webhooks(id) ON DELETE CASCADE,
                    event_type VARCHAR(64) NOT NULL,
                    body_json TEXT NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_webhook_outbox_webhook_id "
                "ON webhook_outbox (webhook_id)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_webhook_outbox_status "
                "ON webhook_outbox (status)"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_webhook_outbox_pending "
                "ON webhook_outbox (status, next_attempt_at)"
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS presence_statuses (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(128) NOT NULL,
                    slug VARCHAR(64) NOT NULL UNIQUE,
                    color VARCHAR(16) NOT NULL DEFAULT '#9ca3af',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_system BOOLEAN NOT NULL DEFAULT FALSE,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    participates_in_routing BOOLEAN NOT NULL DEFAULT FALSE,
                    can_write_chats BOOLEAN NOT NULL DEFAULT TRUE,
                    on_duty BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_presence_statuses_slug "
                "ON presence_statuses (slug)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS presence_status_id "
                "INTEGER REFERENCES presence_statuses(id) ON DELETE SET NULL"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_users_presence_status_id "
                "ON users (presence_status_id)"
            )
        )
        # Mailing anti-ban / pacing columns
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaigns ADD COLUMN IF NOT EXISTS max_per_hour "
                "INTEGER NOT NULL DEFAULT 30"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaigns ADD COLUMN IF NOT EXISTS max_per_day "
                "INTEGER NOT NULL DEFAULT 150"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaigns ADD COLUMN IF NOT EXISTS fail_pause_pct "
                "INTEGER NOT NULL DEFAULT 40"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaigns ADD COLUMN IF NOT EXISTS quiet_start_hour INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaigns ADD COLUMN IF NOT EXISTS quiet_end_hour INTEGER"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaigns ADD COLUMN IF NOT EXISTS write_to_crm "
                "BOOLEAN NOT NULL DEFAULT TRUE"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaign_channels ADD COLUMN IF NOT EXISTS paused_until TIMESTAMPTZ"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_campaign_channels ADD COLUMN IF NOT EXISTS pause_reason TEXT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_recipients ADD COLUMN IF NOT EXISTS peer_chat_id VARCHAR(64)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_recipients ADD COLUMN IF NOT EXISTS peer_contact_id VARCHAR(64)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_recipients ADD COLUMN IF NOT EXISTS peer_name VARCHAR(255)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_recipients ADD COLUMN IF NOT EXISTS peer_username VARCHAR(255)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_recipients ADD COLUMN IF NOT EXISTS attempts "
                "INTEGER NOT NULL DEFAULT 0"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE mailing_recipients ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ"
            )
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_mailing_recipients_next_attempt_at "
                "ON mailing_recipients (next_attempt_at)"
            )
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Without REDIS_URL: single-process mode (in-memory hub + local background workers).
    # With REDIS_URL: WS/widget fan-out via pub/sub; only the Redis leader runs pollers/mailing/outbox.
    settings = get_settings()
    from app.config import validate_runtime_settings

    validate_runtime_settings(settings)
    mode = "redis multi-worker" if settings.redis_enabled else "single-worker"
    logger.info("Starting %s (%s)", settings.app_name, mode)
    try:
        from app.integrations.telegram_proxy import log_telegram_proxy_status

        await log_telegram_proxy_status()
    except Exception:
        logger.exception("Telegram proxy health check failed")
    await ensure_schema()
    async with SessionLocal() as session:
        await seed_database(session)

    if settings.redis_enabled:
        try:
            from app.redisutil import get_redis

            await get_redis()
        except Exception:
            logger.exception("REDIS_URL set but Redis is unreachable — aborting start")
            raise

    from app.integrations.webchat.visitor_hub import visitor_hub
    from app.leader import BackgroundLeader
    from app.mailing.worker import worker as mailing_worker
    from app.realtime.hub import hub
    from app.realtime.webhooks import worker as webhook_outbox_worker
    from app.redisutil import close_redis

    adapters = [get_adapter(t) for t in list_transports()]
    workers_running = {"value": False}

    async def start_background() -> None:
        if workers_running["value"]:
            return
        for adapter in adapters:
            try:
                await adapter.start_worker()
            except Exception:
                logger.exception("Failed to start worker for %s", adapter.transport)
        mailing_worker.start()
        webhook_outbox_worker.start()
        workers_running["value"] = True
        logger.info("Background workers started (leader)")

    async def stop_background() -> None:
        if not workers_running["value"]:
            return
        try:
            from app.realtime.webhooks import close_webhook_client

            await close_webhook_client()
        except Exception:
            logger.exception("Failed to close webhook HTTP client")
        try:
            await webhook_outbox_worker.stop()
        except Exception:
            logger.exception("Failed to stop webhook outbox worker")
        try:
            await mailing_worker.stop()
        except Exception:
            logger.exception("Failed to stop mailing worker")
        for adapter in reversed(adapters):
            try:
                await adapter.stop_worker()
            except Exception:
                logger.exception("Failed to stop worker for %s", adapter.transport)
        workers_running["value"] = False
        logger.info("Background workers stopped")

    await hub.start_pubsub()
    await visitor_hub.start_pubsub()

    leader = BackgroundLeader(on_start=start_background, on_stop=stop_background)
    leader.start()
    app.state.bg_leader = leader
    app.state.redis_enabled = settings.redis_enabled
    try:
        yield
    finally:
        try:
            await leader.stop()
        except Exception:
            logger.exception("Failed to stop leader elector")
        try:
            await visitor_hub.stop_pubsub()
        except Exception:
            logger.exception("Failed to stop widget pubsub")
        try:
            await hub.stop_pubsub()
        except Exception:
            logger.exception("Failed to stop chats pubsub")
        if workers_running["value"]:
            try:
                await stop_background()
            except Exception:
                logger.exception("Failed to stop background workers on shutdown")
        try:
            await close_redis()
        except Exception:
            logger.exception("Failed to close Redis")
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def widget_cors(request, call_next):
        """Allow any Origin for public widget API (Bearer token, no cookies)."""
        if not request.url.path.startswith("/api/widget"):
            return await call_next(request)
        origin = request.headers.get("origin") or "*"
        if request.method == "OPTIONS":
            from starlette.responses import Response

            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type, Origin",
                    "Access-Control-Max-Age": "86400",
                    "Vary": "Origin",
                },
            )
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        return response

    app.include_router(api_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        payload: dict = {
            "status": "ok",
            "db": "ok",
            "redis": "disabled",
            "bg_leader": None,
            "mode": "single-worker",
        }
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            logger.exception("Health check DB failed")
            return JSONResponse(
                {
                    "status": "degraded",
                    "db": "error",
                    "redis": payload["redis"],
                    "detail": str(exc)[:200],
                },
                status_code=503,
            )

        if getattr(app.state, "redis_enabled", False):
            payload["mode"] = "redis multi-worker"
            try:
                from app.redisutil import get_redis

                r = await get_redis()
                if r is None:
                    payload["redis"] = "error"
                    payload["status"] = "degraded"
                else:
                    await r.ping()
                    payload["redis"] = "ok"
            except Exception as exc:
                logger.exception("Health check Redis failed")
                payload["redis"] = "error"
                payload["status"] = "degraded"
                payload["redis_detail"] = str(exc)[:200]

        leader = getattr(app.state, "bg_leader", None)
        if leader is not None:
            payload["bg_leader"] = bool(leader.is_leader)

        status_code = 200 if payload["status"] == "ok" else 503
        return JSONResponse(payload, status_code=status_code)

    return app


app = create_app()

