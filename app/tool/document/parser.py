"""按需求文档约定解析 FAQ 与长文档。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    content: str
    title: str
    chunk_index: int


class DocumentParser:
    """FAQ 每个问答独立成块，长文档按 512/64 策略递归切分。"""

    _heading_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    def __init__(self, *, chunk_size: int = 512, chunk_overlap: int = 64) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def parse_file(self, path: Path) -> list[DocumentChunk]:
        return self.parse_bytes(path.name, path.read_bytes())

    def parse_bytes(self, filename: str, data: bytes) -> list[DocumentChunk]:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".docx"}:
            raise ValueError("仅支持 txt、md、docx 文件")
        if suffix == ".docx":
            text = self._docx_to_markdown(data)
        else:
            text = data.decode("utf-8-sig")
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            raise ValueError("文档内容不能为空")
        if suffix == ".txt" and self._looks_like_faq(text):
            return self._parse_faq(text)
        return self._parse_long_document(text, Path(filename).stem)

    @staticmethod
    def _looks_like_faq(text: str) -> bool:
        lines = [line for line in text.splitlines() if line.strip()]
        return bool(lines) and sum("\t" in line for line in lines) / len(lines) >= 0.8

    @staticmethod
    def _parse_faq(text: str) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        for line in text.splitlines():
            if not line.strip() or "\t" not in line:
                continue
            question, answer = (part.strip() for part in line.split("\t", 1))
            if not question or not answer:
                continue
            chunks.append(
                DocumentChunk(
                    content=f"问题：{question}\n回答：{answer}",
                    title=question,
                    chunk_index=len(chunks),
                )
            )
        if not chunks:
            raise ValueError("FAQ 文档中没有有效问答对")
        return chunks

    def _parse_long_document(
        self,
        text: str,
        fallback_title: str,
    ) -> list[DocumentChunk]:
        heading_path: list[str] = []
        section_title = fallback_title
        section_lines: list[str] = []
        sections: list[tuple[str, str]] = []

        def flush() -> None:
            body = "\n".join(section_lines).strip()
            if body:
                sections.append((section_title, body))
            section_lines.clear()

        for line in text.splitlines():
            match = self._heading_pattern.match(line)
            if match:
                flush()
                level = len(match.group(1))
                heading = match.group(2).strip()
                heading_path[level - 1 :] = [heading]
                section_title = " > ".join(heading_path)
            else:
                section_lines.append(line)
        flush()
        if not sections:
            sections.append((fallback_title, text))

        chunks: list[DocumentChunk] = []
        for title, body in sections:
            prefix = f"{title}\n"
            content_size = max(64, self.chunk_size - len(prefix))
            content_overlap = min(self.chunk_overlap, content_size - 1)
            for piece in self._recursive_split(body, content_size, content_overlap):
                chunks.append(
                    DocumentChunk(
                        content=f"{prefix}{piece}".strip(),
                        title=title,
                        chunk_index=len(chunks),
                    )
                )
        return chunks

    def _recursive_split(
        self,
        text: str,
        size: int,
        overlap: int,
    ) -> list[str]:
        if len(text) <= size:
            return [text.strip()] if text.strip() else []

        pieces: list[str] = []
        start = 0
        while start < len(text):
            target_end = min(start + size, len(text))
            end = target_end
            if target_end < len(text):
                window = text[start:target_end]
                boundaries = [
                    window.rfind("\n\n"),
                    window.rfind("\n"),
                    window.rfind("。"),
                    window.rfind("；"),
                    window.rfind("，"),
                ]
                best = max(boundaries)
                if best >= size // 2:
                    end = start + best + 1
            piece = text[start:end].strip()
            if piece:
                pieces.append(piece)
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
        return pieces

    @staticmethod
    def _docx_to_markdown(data: bytes) -> str:
        from docx import Document

        document = Document(BytesIO(data))
        lines: list[str] = []
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style_name = paragraph.style.name if paragraph.style else ""
            match = re.match(r"Heading\s+([1-6])", style_name, re.IGNORECASE)
            if match:
                lines.append(f"{'#' * int(match.group(1))} {text}")
            else:
                lines.append(text)
        return "\n\n".join(lines)
