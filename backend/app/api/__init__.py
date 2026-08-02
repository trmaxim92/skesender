from fastapi import APIRouter

from app.api import (
    appeals,
    auth,
    channels,
    chats,
    departments,
    mailing,
    me_templates,
    roles,
    settings_fields,
    templates,
    users,
    webhooks,
    ws,
)
from app.integrations.webchat import api as widget_api

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(me_templates.router)
api_router.include_router(channels.router)
api_router.include_router(chats.router)
api_router.include_router(appeals.router)
api_router.include_router(mailing.router)
api_router.include_router(users.router)
api_router.include_router(roles.router)
api_router.include_router(departments.router)
api_router.include_router(settings_fields.router)
api_router.include_router(templates.router)
api_router.include_router(webhooks.router)
api_router.include_router(ws.router)
api_router.include_router(widget_api.router)
