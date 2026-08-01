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


@asynccontextmanager
async def lifespan(_: FastAPI):
    # In-memory hub/pollers/mailing require a single uvicorn worker (or replicas
    # with external pub/sub + leader election). Do not run --workers > 1.
    settings = get_settings()
    logger.info("Starting %s (single-worker realtime/mailing)", settings.app_name)
    await ensure_schema()
    async with SessionLocal() as session:
        await seed_database(session)

    adapters = [get_adapter(t) for t in list_transports()]
    for adapter in adapters:
        try:
            await adapter.start_worker()
        except Exception:
            logger.exception("Failed to start worker for %s", adapter.transport)

    from app.mailing.worker import worker as mailing_worker

    mailing_worker.start()
    try:
        yield
    finally:
        try:
            from app.realtime.webhooks import close_webhook_client

            await close_webhook_client()
        except Exception:
            logger.exception("Failed to close webhook HTTP client")
        try:
            await mailing_worker.stop()
        except Exception:
            logger.exception("Failed to stop mailing worker")
        for adapter in reversed(adapters):
            try:
                await adapter.stop_worker()
            except Exception:
                logger.exception("Failed to stop worker for %s", adapter.transport)
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
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return JSONResponse({"status": "ok", "db": "ok"})
        except Exception as exc:
            logger.exception("Health check DB failed")
            return JSONResponse(
                {"status": "degraded", "db": "error", "detail": str(exc)[:200]},
                status_code=503,
            )

    return app


app = create_app()

