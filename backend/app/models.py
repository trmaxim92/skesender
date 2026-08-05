from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class ChannelTransport(StrEnum):
    MAXBOT = "maxbot"
    MAX = "max"
    TELEGRAM = "telegram"
    TGAPI = "tgapi"
    VK = "vk"
    WEBCHAT = "webchat"


class ChannelStatus(StrEnum):
    ONLINE = "online"
    CONNECTING = "connecting"
    QR_PENDING = "qr_pending"
    OFFLINE = "offline"
    ERROR = "error"


class MessageDirection(StrEnum):
    IN = "in"
    OUT = "out"


class MessageStatus(StrEnum):
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class AttachmentKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"


class AppealStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class FieldScope(StrEnum):
    CLIENT = "client"
    APPEAL = "appeal"


class FieldType(StrEnum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    PHONE = "phone"
    SELECT = "select"
    DATE = "date"
    BOOL = "bool"
    LINK = "link"


class TemplateKind(StrEnum):
    GENERAL = "general"
    APPEAL_CLOSED = "appeal_closed"


class PresenceStatusSlug(StrEnum):
    """Reserved system slugs — custom statuses use free-form slugs."""

    ONLINE = "online"
    OFFLINE = "offline"
    TRAINING = "training"


class MailingCampaignStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class MailingRecipientKind(StrEnum):
    USERNAME = "username"
    PHONE = "phone"
    UNKNOWN = "unknown"


class MailingRecipientStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class WebhookOutboxStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"


class PresenceStatus(Base):
    """Operator presence mode — runtime overlay that can only tighten role rights."""

    __tablename__ = "presence_statuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    color: Mapped[str] = mapped_column(String(16), default="#9ca3af")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Rules (status may only restrict relative to role permissions).
    participates_in_routing: Mapped[bool] = mapped_column(Boolean, default=False)
    can_write_chats: Mapped[bool] = mapped_column(Boolean, default=True)
    on_duty: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="presence_status")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=Role.OPERATOR.value)
    access_role_id: Mapped[int | None] = mapped_column(
        ForeignKey("access_roles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    presence_status_id: Mapped[int | None] = mapped_column(
        ForeignKey("presence_statuses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on password change / deactivation to invalidate existing JWTs.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    access_role: Mapped["AccessRole | None"] = relationship(back_populates="users")
    presence_status: Mapped["PresenceStatus | None"] = relationship(back_populates="users")
    channel_access: Mapped[list["UserChannel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    department_memberships: Mapped[list["UserDepartment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    channels: Mapped[list["Channel"]] = relationship(back_populates="created_by")
    assigned_dialogs: Mapped[list["Dialog"]] = relationship(back_populates="assignee")
    closed_appeals: Mapped[list["Appeal"]] = relationship(back_populates="closed_by")


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    members: Mapped[list["UserDepartment"]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )
    channels: Mapped[list["Channel"]] = relationship(back_populates="department")
    field_definitions: Mapped[list["FieldDefinition"]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )


class UserDepartment(Base):
    __tablename__ = "user_departments"
    __table_args__ = (UniqueConstraint("user_id", "department_id", name="uq_user_department"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True
    )

    user: Mapped[User] = relationship(back_populates="department_memberships")
    department: Mapped[Department] = relationship(back_populates="members")


class AccessRole(Base):
    __tablename__ = "access_roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    all_channels: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    channel_access: Mapped[list["RoleChannel"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[list[User]] = relationship(back_populates="access_role")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "code", name="uq_role_permission_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("access_roles.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)

    role: Mapped[AccessRole] = relationship(back_populates="permissions")


class RoleChannel(Base):
    __tablename__ = "role_channels"
    __table_args__ = (UniqueConstraint("role_id", "channel_id", name="uq_role_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("access_roles.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)

    role: Mapped[AccessRole] = relationship(back_populates="channel_access")
    channel: Mapped["Channel"] = relationship()


class UserChannel(Base):
    __tablename__ = "user_channels"
    __table_args__ = (UniqueConstraint("user_id", "channel_id", name="uq_user_channel"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)

    user: Mapped[User] = relationship(back_populates="channel_access")
    channel: Mapped["Channel"] = relationship()


class Channel(Base):
    __tablename__ = "channels"
    __table_args__ = (UniqueConstraint("transport", "external_id", name="uq_channel_transport_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    transport: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ChannelStatus.OFFLINE.value)
    identity: Mapped[str] = mapped_column(String(255), default="")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_marker: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    created_by: Mapped[User | None] = relationship(back_populates="channels")
    department: Mapped[Department | None] = relationship(back_populates="channels")
    dialogs: Mapped[list["Dialog"]] = relationship(
        back_populates="channel",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Dialog(Base):
    __tablename__ = "dialogs"
    __table_args__ = (
        UniqueConstraint("channel_id", "external_chat_id", name="uq_dialog_channel_chat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    external_chat_id: Mapped[str] = mapped_column(String(64), index=True)
    contact_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_name: Mapped[str] = mapped_column(String(255), default="Клиент")
    contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_message: Mapped[str] = mapped_column(Text, default="")
    last_direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    unread: Mapped[int] = mapped_column(Integer, default=0)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_appeal_id: Mapped[int | None] = mapped_column(
        ForeignKey("appeals.id", ondelete="SET NULL", use_alter=True, name="fk_dialogs_current_appeal"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    channel: Mapped[Channel] = relationship(back_populates="dialogs")
    department: Mapped["Department | None"] = relationship()
    assignee: Mapped[User | None] = relationship(back_populates="assigned_dialogs")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="dialog")
    appeals: Mapped[list["Appeal"]] = relationship(
        back_populates="dialog",
        foreign_keys="Appeal.dialog_id",
        cascade="all, delete-orphan",
    )
    current_appeal: Mapped["Appeal | None"] = relationship(
        foreign_keys=[current_appeal_id],
        post_update=True,
    )


class Appeal(Base):
    __tablename__ = "appeals"
    __table_args__ = (
        UniqueConstraint("dialog_id", "number", name="uq_appeal_dialog_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default=AppealStatus.OPEN.value, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dialog: Mapped[Dialog] = relationship(
        back_populates="appeals",
        foreign_keys=[dialog_id],
    )
    closed_by: Mapped[User | None] = relationship(back_populates="closed_appeals")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="appeal")


class ChatMessage(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("channel_id", "external_id", name="uq_message_channel_external"),
        Index(
            "ix_messages_dialog_created_id",
            "dialog_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    appeal_id: Mapped[int | None] = mapped_column(
        ForeignKey("appeals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    direction: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=MessageStatus.SENT.value)
    # Internal manager note — visible in CRM only, never sent to the client.
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    operator_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reply_to_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    dialog: Mapped[Dialog] = relationship(back_populates="messages")
    appeal: Mapped[Appeal | None] = relationship(back_populates="messages")
    reply_to: Mapped["ChatMessage | None"] = relationship(
        remote_side="ChatMessage.id",
        foreign_keys=[reply_to_message_id],
    )
    attachments: Mapped[list["MessageAttachment"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    file_name: Mapped[str] = mapped_column(String(255), default="file")
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    message: Mapped[ChatMessage] = relationship(back_populates="attachments")


class FieldDefinition(Base):
    __tablename__ = "field_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    key: Mapped[str] = mapped_column(String(64), index=True)
    label: Mapped[str] = mapped_column(String(255))
    field_type: Mapped[str] = mapped_column(String(16), default=FieldType.TEXT.value)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    department: Mapped[Department | None] = relationship(back_populates="field_definitions")


class FieldValue(Base):
    __tablename__ = "field_values"
    __table_args__ = (
        UniqueConstraint("scope", "owner_id", "field_key", name="uq_field_value_owner_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), index=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    field_key: Mapped[str] = mapped_column(String(64), index=True)
    value_text: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TemplateCategory(Base):
    __tablename__ = "template_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MessageTemplate(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    transport: Mapped[str] = mapped_column(String(32), default="all", index=True)
    kind: Mapped[str] = mapped_column(String(32), default=TemplateKind.GENERAL.value, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("template_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    media_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    category: Mapped[TemplateCategory | None] = relationship()


class OutboundWebhook(Base):
    __tablename__ = "outbound_webhooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    url: Mapped[str] = mapped_column(String(1024))
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    outbox: Mapped[list["WebhookOutbox"]] = relationship(
        back_populates="webhook", cascade="all, delete-orphan"
    )


class WebhookOutbox(Base):
    """Durable outbound webhook deliveries (survive restarts / transient HTTP failures)."""

    __tablename__ = "webhook_outbox"
    __table_args__ = (
        Index("ix_webhook_outbox_pending", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    webhook_id: Mapped[int] = mapped_column(
        ForeignKey("outbound_webhooks.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    body_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), default=WebhookOutboxStatus.PENDING.value, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    webhook: Mapped[OutboundWebhook] = relationship(back_populates="outbox")


class MailingTemplate(Base):
    __tablename__ = "mailing_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    media_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    media_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    media_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    campaigns: Mapped[list["MailingCampaign"]] = relationship(back_populates="template")


class MailingCampaign(Base):
    __tablename__ = "mailing_campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    template_id: Mapped[int] = mapped_column(ForeignKey("mailing_templates.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=MailingCampaignStatus.DRAFT.value, index=True)
    delay_sec: Mapped[int] = mapped_column(Integer, default=15)
    # 0 = no cap. Per-channel across all campaigns.
    max_per_hour: Mapped[int] = mapped_column(Integer, default=30)
    max_per_day: Mapped[int] = mapped_column(Integer, default=150)
    # Pause campaign when failed/(sent+failed) >= pct after enough samples. 0 = off.
    fail_pause_pct: Mapped[int] = mapped_column(Integer, default=40)
    quiet_start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiet_end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    write_to_crm: Mapped[bool] = mapped_column(Boolean, default=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    template: Mapped[MailingTemplate] = relationship(back_populates="campaigns")
    channels: Mapped[list["MailingCampaignChannel"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )
    recipients: Mapped[list["MailingRecipient"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class MailingCampaignChannel(Base):
    __tablename__ = "mailing_campaign_channels"
    __table_args__ = (
        UniqueConstraint("campaign_id", "channel_id", name="uq_mailing_campaign_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("mailing_campaigns.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    campaign: Mapped[MailingCampaign] = relationship(back_populates="channels")
    channel: Mapped[Channel] = relationship()


class MailingRecipient(Base):
    __tablename__ = "mailing_recipients"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "kind", "normalized", name="uq_mailing_recipient_campaign_kind_norm"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("mailing_campaigns.id", ondelete="CASCADE"), index=True
    )
    raw: Mapped[str] = mapped_column(String(255))
    normalized: Mapped[str] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(16), default=MailingRecipientKind.UNKNOWN.value)
    status: Mapped[str] = mapped_column(
        String(16), default=MailingRecipientStatus.PENDING.value, index=True
    )
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id"), nullable=True)
    peer_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    peer_contact_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    peer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    peer_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign: Mapped[MailingCampaign] = relationship(back_populates="recipients")
    channel: Mapped[Channel | None] = relationship()

