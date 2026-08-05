from datetime import datetime

from pydantic import BaseModel, Field

from app.models import (
    AppealStatus,
    AttachmentKind,
    ChannelStatus,
    ChannelTransport,
    MessageDirection,
    MessageStatus,
    Role,
    TemplateKind,
)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str


class MeUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    presence_status_id: int | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=6, max_length=255)


class PresenceStatusOut(BaseModel):
    id: int
    name: str
    slug: str
    color: str
    sort_order: int
    is_system: bool
    is_active: bool
    participates_in_routing: bool
    can_write_chats: bool
    on_duty: bool

    model_config = {"from_attributes": True}


class PresenceStatusCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    color: str = Field(default="#9ca3af", min_length=4, max_length=16)
    sort_order: int = 0
    participates_in_routing: bool = False
    can_write_chats: bool = True
    on_duty: bool = True
    is_active: bool = True


class PresenceStatusUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    color: str | None = Field(default=None, min_length=4, max_length=16)
    sort_order: int | None = None
    participates_in_routing: bool | None = None
    can_write_chats: bool | None = None
    on_duty: bool | None = None
    is_active: bool | None = None


class PresenceEmployeeOut(BaseModel):
    id: int
    name: str
    email: str
    role_name: str | None = None
    department_ids: list[int] = []
    is_active: bool = True
    presence_status: PresenceStatusOut | None = None


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: Role
    is_active: bool = True
    access_role_id: int | None = None
    role_name: str | None = None
    permissions: list[str] = []
    all_channels: bool = False
    channel_ids: list[int] = []
    department_ids: list[int] = []
    presence_status_id: int | None = None
    presence_status: PresenceStatusOut | None = None
    can_write_chats: bool = True

    model_config = {"from_attributes": True}


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=3)
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=4, max_length=128)
    role: Role | None = None
    access_role_id: int | None = None
    channel_ids: list[int] = []
    department_ids: list[int] = []


class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    role: Role | None = None
    access_role_id: int | None = None
    channel_ids: list[int] | None = None
    department_ids: list[int] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=4, max_length=128)


class AccessRoleOut(BaseModel):
    id: int
    name: str
    slug: str
    is_system: bool
    all_channels: bool
    permissions: list[str] = []
    channel_ids: list[int] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class AccessRoleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    permissions: list[str] = []
    all_channels: bool = False
    channel_ids: list[int] = []


class AccessRoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    permissions: list[str] | None = None
    all_channels: bool | None = None
    channel_ids: list[int] | None = None


class PermissionCatalogItem(BaseModel):
    code: str
    label: str


class ChannelOut(BaseModel):
    id: int
    name: str
    transport: ChannelTransport
    status: ChannelStatus
    identity: str
    external_id: str | None = None
    connected_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime
    has_credentials: bool = False
    department_id: int | None = None
    department_name: str | None = None
    public_key: str | None = None

    model_config = {"from_attributes": True}


class ChannelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    department_id: int | None = None
    status: ChannelStatus | None = None


class MaxBotConnectRequest(BaseModel):
    token: str = Field(min_length=10)
    name: str | None = None
    department_id: int | None = None


class TelegramConnectRequest(BaseModel):
    token: str = Field(min_length=10)
    name: str | None = None
    department_id: int | None = None


class WebchatConnectRequest(BaseModel):
    name: str | None = None
    department_id: int | None = None
    allowed_origins: list[str] = Field(default_factory=list)


class ChannelConnectResult(BaseModel):
    channel: ChannelOut
    bot: dict | None = None


class MaxQrStartRequest(BaseModel):
    name: str | None = None
    department_id: int | None = None
    # Optional SOCKS/HTTP proxy for Telegram · аккаунт (ignored by MAX QR).
    proxy: str | None = None


class MaxQrStartResponse(BaseModel):
    channel: ChannelOut
    qr_url: str
    status: str


class MaxQrStatusResponse(BaseModel):
    channel_id: int
    status: str
    qr_url: str | None = None
    identity: str | None = None
    hint: str | None = None
    error: str | None = None
    channel: ChannelOut | None = None


class MaxQr2FARequest(BaseModel):
    password: str = Field(min_length=1)


class DialogOut(BaseModel):
    id: int
    channel_id: int
    contact_name: str
    contact_phone: str | None = None
    contact_username: str | None = None
    contact_avatar_url: str | None = None
    last_message: str
    last_at: datetime
    last_direction: MessageDirection | None = None
    last_status: MessageStatus | None = None
    unread: int
    assignee_id: int | None = None
    transport: ChannelTransport | None = None
    appeal_id: int | None = None
    appeal_number: int | None = None
    appeal_status: AppealStatus | None = None
    department_id: int | None = None

    model_config = {"from_attributes": True}


class DialogsPageOut(BaseModel):
    items: list[DialogOut]
    has_more: bool
    limit: int
    offset: int


class UnreadSummaryOut(BaseModel):
    new: int = 0
    mine: int = 0
    others: int = 0


class AppealOut(BaseModel):
    id: int
    dialog_id: int
    number: int
    status: AppealStatus
    opened_at: datetime
    closed_at: datetime | None = None
    closed_by_id: int | None = None
    closed_by_name: str | None = None

    model_config = {"from_attributes": True}


class AppealListItemOut(BaseModel):
    id: int
    dialog_id: int
    number: int
    status: AppealStatus
    opened_at: datetime
    closed_at: datetime | None = None
    closed_by_id: int | None = None
    closed_by_name: str | None = None
    contact_name: str
    contact_username: str | None = None
    contact_external_id: str | None = None
    contact_avatar_url: str | None = None
    channel_id: int
    channel_name: str | None = None
    transport: ChannelTransport | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    last_message: str = ""
    last_at: datetime


class AppealListOut(BaseModel):
    items: list[AppealListItemOut]
    total: int
    limit: int
    offset: int


class AppealDetailOut(AppealListItemOut):
    """Single appeal for the dedicated history screen."""

    current_appeal_id: int | None = None
    current_appeal_status: AppealStatus | None = None
    can_open_in_chats: bool = False


class ClientCardOut(BaseModel):
    contact_name: str
    contact_username: str | None = None
    contact_avatar_url: str | None = None
    contact_external_id: str | None = None
    contact_phone: str | None = None
    channel_id: int
    transport: ChannelTransport | None = None
    channel_name: str | None = None
    dialog_created_at: datetime
    appeals_count: int
    assignee_id: int | None = None
    assignee_name: str | None = None
    department_id: int | None = None


class FieldDefinitionOut(BaseModel):
    id: int
    scope: str
    department_id: int | None = None
    key: str
    label: str
    field_type: str
    options: list[str] = []
    required: bool = False
    sort_order: int = 0
    is_system: bool = False
    is_active: bool = True

    model_config = {"from_attributes": True}


class FieldDefinitionCreateRequest(BaseModel):
    scope: str = Field(pattern="^(client|appeal)$")
    department_id: int | None = None
    key: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=255)
    field_type: str = Field(
        default="text",
        pattern="^(text|textarea|number|phone|select|date|bool|link)$",
    )
    options: list[str] = []
    required: bool = False
    sort_order: int = 0


class FieldDefinitionUpdateRequest(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    field_type: str | None = Field(
        default=None,
        pattern="^(text|textarea|number|phone|select|date|bool|link)$",
    )
    options: list[str] | None = None
    required: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class FieldValueItem(BaseModel):
    key: str
    value: str = ""


class ClientFieldsUpdateRequest(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    external_id: str | None = None
    values: list[FieldValueItem] = []


class AppealFieldsUpdateRequest(BaseModel):
    values: list[FieldValueItem] = []


class DialogSidebarOut(BaseModel):
    client: ClientCardOut
    current_appeal: AppealOut | None = None
    appeals: list[AppealOut] = []
    client_fields: list[FieldDefinitionOut] = []
    appeal_fields: list[FieldDefinitionOut] = []
    client_values: dict[str, str] = {}
    appeal_values: dict[str, str] = {}


class DepartmentOut(BaseModel):
    id: int
    name: str
    slug: str
    is_active: bool
    member_ids: list[int] = []
    channel_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class DepartmentCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    member_ids: list[int] = []


class DepartmentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    member_ids: list[int] | None = None


class AssignDialogRequest(BaseModel):
    assignee_id: int | None = None


class AttachmentOut(BaseModel):
    id: int
    kind: AttachmentKind
    file_name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    url: str

    model_config = {"from_attributes": True}


class ReplyPreview(BaseModel):
    id: int
    text: str
    direction: MessageDirection
    operator_name: str | None = None


class MessageOut(BaseModel):
    id: int
    dialog_id: int
    direction: MessageDirection
    text: str
    status: MessageStatus
    operator_name: str | None = None
    created_at: datetime
    edited_at: datetime | None = None
    deleted_at: datetime | None = None
    is_internal: bool = False
    appeal_id: int | None = None
    attachments: list[AttachmentOut] = []
    reply_to: ReplyPreview | None = None

    model_config = {"from_attributes": True}


class MessagesPageOut(BaseModel):
    items: list[MessageOut]
    has_more: bool


class EditMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class CreateNoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    appeal_id: int | None = None


class SendMessageRequest(BaseModel):
    text: str = Field(default="", max_length=4000)


class StartChatRequest(BaseModel):
    channel_id: int
    recipient: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=4000)


class StartChatOut(BaseModel):
    dialog: DialogOut
    message: MessageOut


WEBHOOK_EVENT_TYPES = (
    "message.created",
    "dialog.updated",
    "dialog.assigned",
    "channel.status",
)


class TemplateCategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateCategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sort_order: int = 0


class TemplateCategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = None


class TemplateOut(BaseModel):
    id: int
    name: str
    body: str
    transport: str
    kind: TemplateKind = TemplateKind.GENERAL
    category_id: int | None = None
    category_name: str | None = None
    media_kind: str | None = None
    media_name: str | None = None
    mime_type: str | None = None
    has_media: bool = False
    created_by_id: int | None = None
    is_mine: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    body: str = Field(default="", max_length=8000)
    transport: str = "all"
    kind: TemplateKind = TemplateKind.GENERAL
    category_id: int | None = None


class TemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=8000)
    transport: str | None = None
    kind: TemplateKind | None = None
    category_id: int | None = None


class WebhookOut(BaseModel):
    id: int
    url: str
    events: list[str]
    active: bool
    has_secret: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookCreateRequest(BaseModel):
    url: str = Field(min_length=8, max_length=1024)
    events: list[str] = Field(min_length=1)
    secret: str | None = Field(default=None, max_length=255)


class WebhookUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=1024)
    events: list[str] | None = None
    active: bool | None = None
    secret: str | None = Field(default=None, max_length=255)


class MailingTemplateOut(BaseModel):
    id: int
    name: str
    body: str
    media_kind: str | None = None
    media_name: str | None = None
    mime_type: str | None = None
    has_media: bool = False
    created_at: datetime
    updated_at: datetime


class MailingCampaignChannelOut(BaseModel):
    channel_id: int
    channel_name: str | None = None
    transport: str | None = None
    identity: str | None = None
    paused_until: datetime | None = None
    pause_reason: str | None = None


class MailingRecipientOut(BaseModel):
    id: int
    raw: str
    normalized: str
    kind: str
    status: str
    channel_id: int | None = None
    error: str | None = None
    sent_at: datetime | None = None


class MailingCampaignOut(BaseModel):
    id: int
    name: str
    template_id: int
    template_name: str | None = None
    status: str
    delay_sec: int
    max_per_hour: int = 30
    max_per_day: int = 150
    fail_pause_pct: int = 40
    quiet_start_hour: int | None = None
    quiet_end_hour: int | None = None
    write_to_crm: bool = True
    total: int
    sent: int
    failed: int
    channels: list[MailingCampaignChannelOut] = []
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class MailingCampaignDetailOut(MailingCampaignOut):
    recipients: list[MailingRecipientOut] = []
    recipients_total: int = 0


class MailingCampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    template_id: int
    channel_ids: list[int] = Field(min_length=1)
    delay_sec: int = Field(default=15, ge=1, le=300)
    max_per_hour: int = Field(default=30, ge=0, le=500)
    max_per_day: int = Field(default=150, ge=0, le=5000)
    fail_pause_pct: int = Field(default=40, ge=0, le=100)
    quiet_start_hour: int | None = Field(default=None, ge=0, le=23)
    quiet_end_hour: int | None = Field(default=None, ge=0, le=23)
    write_to_crm: bool = True
    recipients_text: str = Field(min_length=1, max_length=2_000_000)



class WidgetSessionRequest(BaseModel):
    public_key: str = Field(min_length=8, max_length=128)
    visitor_id: str | None = Field(default=None, max_length=64)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=64)


class WidgetSessionOut(BaseModel):
    visitor_token: str
    visitor_id: str
    dialog_id: int
    channel_name: str
    channel_online: bool


class WidgetMessageCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class WidgetMessageOut(BaseModel):
    id: int
    external_id: str | None = None
    direction: MessageDirection
    text: str
    created_at: datetime
