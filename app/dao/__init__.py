"""数据库访问与连接生命周期管理。"""

from app.dao.manager import DatabaseManager, get_database_manager

__all__ = ["DatabaseManager", "get_database_manager"]
