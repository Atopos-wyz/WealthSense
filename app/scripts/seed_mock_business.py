import asyncio

from app.config.settings import get_settings
from app.container import build_container
from app.tool.operation.database_registry import DatabaseOperationToolRegistry


async def seed() -> dict[str, int]:
    container = await build_container(get_settings())
    try:
        registry = container.tool_registry
        if not isinstance(registry, DatabaseOperationToolRegistry):
            raise RuntimeError(
                "database Mock seeding requires configured MySQL and Redis"
            )
        return await registry.repository.seed_defaults()
    finally:
        await container.close()


def main() -> None:
    result = asyncio.run(seed())
    print(
        "Database Mock seed complete: "
        f"accounts_created={result['accounts_created']}, "
        f"product_details_created={result['product_details_created']}"
    )


if __name__ == "__main__":
    main()
