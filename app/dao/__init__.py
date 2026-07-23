"""Database access and connection lifecycle management."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.dao.manager import DatabaseManager

__all__ = ["DatabaseManager", "get_database_manager"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    from app.dao.manager import DatabaseManager, get_database_manager

    exports = {
        "DatabaseManager": DatabaseManager,
        "get_database_manager": get_database_manager,
    }
    return exports[name]
