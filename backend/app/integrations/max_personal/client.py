"""MAX personal helpers (session paths, thin wrappers)."""

from pathlib import Path

from app.config import get_settings


def channel_work_dir(channel_id: int) -> Path:
    return Path(get_settings().max_personal_data_dir) / f"ch_{channel_id}"
