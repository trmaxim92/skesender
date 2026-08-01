"""Channel integration packages.

Each messenger transport lives in its own subpackage under ``app.integrations``.
"""

from app.integrations.registry import get_adapter, list_transports

__all__ = ["get_adapter", "list_transports"]
