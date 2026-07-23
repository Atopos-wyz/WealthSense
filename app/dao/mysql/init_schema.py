"""创建并验证 WealthSense 客户画像域数据表。

用法：
    python -m app.dao.mysql.init_schema --check-only
    python -m app.dao.mysql.init_schema
"""

import argparse
import asyncio
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.dao.mysql.schema import (
    CREATE_TABLE_STATEMENTS,
    PRODUCT_COLUMN_MIGRATIONS,
    create_profile_tables,
)


SUPPORTING_TABLES = frozenset({"sys_user", "fin_product"})
SCHEMA_TABLES = (
    "sys_user",
    "fin_product",
    "fin_risk_assessment",
    "fin_holdings",
    "fin_customer_profile",
    "fin_profile_evaluation",
    "fin_profile_field_audit",
    "fin_suitability_check",
)


@dataclass(frozen=True)
class DatabaseInfo:
    database_name: str
    mysql_version: str
    existing_prerequisites: frozenset[str]

    @property
    def missing_prerequisites(self) -> frozenset[str]:
        return SUPPORTING_TABLES - self.existing_prerequisites


async def inspect_database(connection: AsyncConnection) -> DatabaseInfo:
    """读取目标库信息及画像表依赖，不修改数据库。"""

    database_name, mysql_version = (
        await connection.exec_driver_sql("SELECT DATABASE(), VERSION()")
    ).one()
    rows = (
        await connection.exec_driver_sql(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name IN ('sys_user', 'fin_product')
            """
        )
    ).all()
    return DatabaseInfo(
        database_name=database_name,
        mysql_version=mysql_version,
        existing_prerequisites=frozenset(row[0] for row in rows),
    )


async def fetch_created_profile_tables(
    connection: AsyncConnection,
) -> tuple[str, ...]:
    """返回当前数据库中已经存在的画像域核心表。"""

    rows = (
        await connection.exec_driver_sql(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name IN (
                  'sys_user',
                  'fin_product',
                  'fin_risk_assessment',
                  'fin_holdings',
                  'fin_customer_profile',
                  'fin_profile_evaluation',
                  'fin_profile_field_audit',
                  'fin_suitability_check'
              )
            ORDER BY table_name
            """
        )
    ).all()
    return tuple(row[0] for row in rows)


async def migrate_product_columns(
    connection: AsyncConnection,
) -> tuple[str, ...]:
    """查询实际列后，仅迁移旧版 fin_product 缺少的字段。"""

    rows = (
        await connection.exec_driver_sql(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
              AND table_name = 'fin_product'
            """
        )
    ).all()
    existing_columns = {row[0] for row in rows}
    migrated: list[str] = []
    for column_name, statement in PRODUCT_COLUMN_MIGRATIONS.items():
        if column_name in existing_columns:
            continue
        await connection.exec_driver_sql(statement)
        migrated.append(column_name)
    return tuple(migrated)


def get_database_url(
    use_root: bool,
    port_override: int | None = None,
) -> URL:
    """从环境变量读取应用连接，或安全构造 root 管理连接。"""

    if not use_root:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError(".env 中缺少 DATABASE_URL")
        url = make_url(database_url)
        return url.set(port=port_override) if port_override else url

    required_variables = (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_DATABASE",
        "MYSQL_ROOT_PASSWORD",
    )
    missing_variables = [
        name for name in required_variables if not os.getenv(name)
    ]
    if missing_variables:
        missing = ", ".join(missing_variables)
        raise RuntimeError(f".env 中缺少root连接配置: {missing}")

    return URL.create(
        drivername="mysql+aiomysql",
        username="root",
        password=os.environ["MYSQL_ROOT_PASSWORD"],
        host=os.environ["MYSQL_HOST"],
        port=port_override or int(os.environ["MYSQL_PORT"]),
        database=os.environ["MYSQL_DATABASE"],
    )


async def run(
    check_only: bool,
    use_root: bool,
    port_override: int | None = None,
) -> int:
    """检查数据库；非检查模式下创建并验证画像域核心表。"""

    load_dotenv()
    engine = create_async_engine(
        get_database_url(
            use_root=use_root,
            port_override=port_override,
        ),
        # 当前 aiomysql 适配器的 ping 签名与 SQLAlchemy 预检不兼容；
        # 初始化脚本使用一次性短连接，无需启用连接池健康检查。
        pool_pre_ping=False,
    )
    try:
        async with engine.connect() as connection:
            database_info = await inspect_database(connection)

        print(f"目标数据库: {database_info.database_name}")
        print(f"MySQL版本: {database_info.mysql_version}")

        if database_info.missing_prerequisites:
            missing = ", ".join(sorted(database_info.missing_prerequisites))
            print(f"需要创建基础表: {missing}")
        else:
            print("基础表已存在: fin_product, sys_user")
        if check_only:
            return 0

        async with engine.begin() as connection:
            await create_profile_tables(connection.exec_driver_sql)
            migrated_columns = await migrate_product_columns(connection)

        async with engine.connect() as connection:
            created_tables = await fetch_created_profile_tables(connection)

        missing_profile_tables = set(SCHEMA_TABLES) - set(created_tables)
        if missing_profile_tables:
            missing = ", ".join(sorted(missing_profile_tables))
            print(f"建表后仍缺少: {missing}")
            return 3

        print(
            f"成功检查 {len(CREATE_TABLE_STATEMENTS)} 张表，"
            f"新增 {len(migrated_columns)} 个产品字段"
        )
        if migrated_columns:
            print("新增字段: " + ", ".join(migrated_columns))
        print("数据库中可见画像表:")
        for table_name in created_tables:
            print(f"- {table_name}")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="仅检查连接和前置表，不执行DDL",
    )
    parser.add_argument(
        "--use-root",
        action="store_true",
        help="使用.env中的MySQL root管理凭据",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="临时覆盖MySQL连接端口，例如SSH隧道端口",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(
            run(
                check_only=args.check_only,
                use_root=args.use_root,
                port_override=args.port,
            )
        )
    )


if __name__ == "__main__":
    main()
