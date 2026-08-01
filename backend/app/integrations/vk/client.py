"""VK API client — to be implemented."""

from typing import Any


async def get_group(_token: str) -> dict[str, Any]:
    raise NotImplementedError("vk.client.get_group is not implemented yet")


async def send_message(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError("vk.client.send_message is not implemented yet")
