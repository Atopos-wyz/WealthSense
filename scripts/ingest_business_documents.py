"""将 docs/公司业务 下的全部业务文件切片并写入知识库。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.config.settings import PROJECT_ROOT
from app.dao import get_database_manager
from app.dependencies import get_knowledge_service


def knowledge_type_for(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return "FAQ"
    return "产品说明"


async def ingest(directory: Path) -> None:
    service = get_knowledge_service()
    files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".txt", ".md", ".docx"}
    )
    if not files:
        raise RuntimeError(f"目录中没有可导入文件：{directory}")
    try:
        for path in files:
            item, chunk_count = await service.ingest(
                filename=path.name,
                data=path.read_bytes(),
                knowledge_type=knowledge_type_for(path),
                title=path.stem,
                source_path=path.relative_to(PROJECT_ROOT).as_posix(),
            )
            print(
                f"imported source_id={item.id} file={path.name} "
                f"collection={item.milvus_collection} chunks={chunk_count}"
            )
    finally:
        await get_database_manager().close_all()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=PROJECT_ROOT / "docs" / "公司业务",
    )
    args = parser.parse_args()
    asyncio.run(ingest(args.directory.resolve()))


if __name__ == "__main__":
    main()
