from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from app.config import get_settings
from app.models import AttachmentKind

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u0400-\u04FF]+")


def attachments_root() -> Path:
    root = Path(get_settings().attachments_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def sanitize_filename(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", (name or "file").strip()) or "file"
    return cleaned[:180]


def guess_kind(mime_type: str | None, filename: str | None = None) -> AttachmentKind:
    mime = (mime_type or "").lower()
    name = (filename or "").lower()
    if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic")):
        return AttachmentKind.IMAGE
    if mime.startswith("video/") or name.endswith((".mp4", ".mov", ".mkv", ".webm")):
        return AttachmentKind.VIDEO
    if mime.startswith("audio/") or name.endswith((".mp3", ".wav", ".m4a", ".ogg")):
        return AttachmentKind.AUDIO
    return AttachmentKind.FILE


def preview_label(kind: str | AttachmentKind, file_name: str | None = None) -> str:
    value = kind.value if isinstance(kind, AttachmentKind) else kind
    if value == AttachmentKind.IMAGE.value:
        return "📷 Фото"
    if value == AttachmentKind.VIDEO.value:
        return "🎬 Видео"
    if value == AttachmentKind.AUDIO.value:
        return "🎵 Аудио"
    return f"📎 {file_name or 'Файл'}"


def save_bytes(
    *,
    data: bytes,
    file_name: str,
    message_id: int | None = None,
    mime_type: str | None = None,
) -> tuple[str, str, str | None, int]:
    """Save bytes under attachments dir. Returns (relative_path, safe_name, mime, size)."""
    safe = sanitize_filename(file_name)
    mime = mime_type or mimetypes.guess_type(safe)[0]
    folder = attachments_root() / (str(message_id) if message_id else "tmp")
    folder.mkdir(parents=True, exist_ok=True)
    relative = f"{folder.name}/{uuid.uuid4().hex}_{safe}"
    absolute = attachments_root() / relative
    absolute.write_bytes(data)
    return relative, safe, mime, len(data)


def absolute_path(relative: str) -> Path:
    root = attachments_root().resolve()
    path = (root / relative).resolve()
    # is_relative_to avoids startswith false-positives (root vs root_evil).
    if not path.is_relative_to(root):
        raise ValueError("Invalid attachment path")
    return path
