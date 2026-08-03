from __future__ import annotations

from app.models import User
from app.presence import presence_allows_write
from app.rbac import role_all_channels, user_permissions
from app.schemas import PresenceStatusOut, UserOut
from app.models import Role


def presence_to_out(status) -> PresenceStatusOut | None:
    if status is None:
        return None
    return PresenceStatusOut.model_validate(status)


def user_to_out(user: User) -> UserOut:
    # Prefer already-loaded attrs only — lazy IO under async causes MissingGreenlet.
    role = user.__dict__.get("access_role")
    perms = sorted(user_permissions(user))
    if role is not None and role_all_channels(user):
        channel_ids: list[int] = []
    elif role is not None and "channel_access" in (role.__dict__ or {}):
        channel_ids = [rc.channel_id for rc in (role.channel_access or [])]
    elif "channel_access" in user.__dict__:
        channel_ids = [uc.channel_id for uc in (user.channel_access or [])]
    else:
        channel_ids = []
    memberships = user.__dict__.get("department_memberships") or []
    department_ids = [m.department_id for m in memberships]
    legacy = Role(user.role) if user.role in {r.value for r in Role} else Role.OPERATOR
    presence = user.__dict__.get("presence_status")
    return UserOut(
        id=user.id,
        email=user.email,
        name=user.name,
        role=legacy,
        is_active=user.is_active,
        access_role_id=user.access_role_id,
        role_name=role.name if role else None,
        permissions=perms,
        all_channels=role_all_channels(user),
        channel_ids=channel_ids,
        department_ids=department_ids,
        presence_status_id=user.presence_status_id,
        presence_status=presence_to_out(presence),
        can_write_chats=user_can_write_effective(user, perms),
    )


def user_can_write_effective(user: User, perms: list[str] | set[str] | None = None) -> bool:
    from app.rbac import ACTION_WRITE

    codes = set(perms) if perms is not None else user_permissions(user)
    if ACTION_WRITE not in codes:
        return False
    return presence_allows_write(user)
