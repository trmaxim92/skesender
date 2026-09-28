"""Harden pymax photo upload against flaky MAX PHOTO_UPLOAD URLs."""

from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from urllib.parse import parse_qs, quote, urlparse

import aiohttp
from pydantic import ValidationError

logger = logging.getLogger(__name__)

_PATCHED = False
_MAX_URL_ATTEMPTS = 3


def _extract_photo_id(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    for key in ("photoIds", "photoId", "photo_ids", "photo_id"):
        values = query.get(key) or []
        if values and values[0]:
            return str(values[0])
    return None


def apply_photo_upload_patch() -> None:
    """Retry PHOTO_UPLOAD when URL lacks photoIds; log the bad URL."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        from pymax.api.uploads import service as upload_service
        from pymax.api.uploads.models import PhotoUploadResponse
        from pymax.api.uploads.payloads import AttachPhotoPayload, UploadPayload
        from pymax.api.response import payload_item
        from pymax.exceptions import UploadError
        from pymax.protocol import Opcode
    except Exception:
        logger.exception("Cannot import pymax upload service for patch")
        return

    original = upload_service.UploadService.upload_photo

    async def upload_photo(self, photo, profile: bool = False):  # type: ignore[no-untyped-def]
        logger.info("Uploading photo")
        url = None
        photo_id: str | None = None
        last_err: Exception | None = None
        for attempt in range(1, _MAX_URL_ATTEMPTS + 1):
            data = None
            try:
                data = await self.app.invoke(
                    Opcode.PHOTO_UPLOAD,
                    payload=UploadPayload(profile=profile).model_dump(),
                )
                url = payload_item(data, "url", str)
            except Exception as exc:
                last_err = exc
                logger.warning(
                    "PHOTO_UPLOAD invoke failed attempt=%s/%s: %s",
                    attempt,
                    _MAX_URL_ATTEMPTS,
                    exc,
                )
                await asyncio.sleep(0.35 * attempt)
                continue

            if not url:
                logger.warning(
                    "PHOTO_UPLOAD empty url attempt=%s/%s payload=%r",
                    attempt,
                    _MAX_URL_ATTEMPTS,
                    getattr(data, "payload", None) if data is not None else None,
                )
                await asyncio.sleep(0.35 * attempt)
                continue

            photo_id = _extract_photo_id(url)
            if photo_id:
                break
            logger.warning(
                "PHOTO_UPLOAD url missing photoIds attempt=%s/%s url=%s",
                attempt,
                _MAX_URL_ATTEMPTS,
                url,
            )
            last_err = UploadError("Photo upload URL does not contain photoIds")
            url = None
            photo_id = None
            await asyncio.sleep(0.35 * attempt)
        else:
            raise UploadError(
                "Photo upload URL does not contain photoIds"
            ) from last_err

        if not url or not photo_id:
            raise UploadError("Photo upload URL does not contain photoIds")

        try:
            photo_data = photo.validate_photo()
        except Exception as e:
            logger.exception("Photo validation crashed")
            raise UploadError("Photo validation crashed") from e
        if not photo_data:
            raise UploadError("Photo validation failed")

        try:
            photo_bytes = await photo.read()
        except Exception as e:
            logger.exception("Failed to read photo bytes")
            raise UploadError("Failed to read photo bytes") from e

        form = aiohttp.FormData()
        form.add_field(
            name="file",
            value=photo_bytes,
            filename=f"image.{quote(photo_data[0])}",
            content_type=photo_data[1],
        )

        try:
            async with (
                aiohttp.ClientSession(proxy=self.app.config.proxy) as session,
                session.post(url=url, data=form) as response,
            ):
                if response.status != HTTPStatus.OK:
                    raise UploadError(f"Photo upload failed with status {response.status}")
                try:
                    result = await response.json()
                except Exception as e:
                    raise UploadError("Failed to decode photo upload response JSON") from e
        except UploadError:
            raise
        except Exception as e:
            logger.exception("Unexpected error during photo upload")
            raise UploadError("Unexpected error during photo upload") from e

        try:
            model = PhotoUploadResponse.model_validate(result)
            token = model.photos[photo_id].token
        except (ValidationError, KeyError, Exception) as e:
            logger.exception("Invalid photo upload response photo_id=%s", photo_id)
            raise UploadError("Invalid photo upload response model") from e

        return AttachPhotoPayload(photo_token=token)

    upload_service.UploadService.upload_photo = upload_photo  # type: ignore[method-assign]
    _PATCHED = True
    logger.info("Applied pymax photo upload retry patch")
