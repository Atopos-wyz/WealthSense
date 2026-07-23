"""可选的 OpenAI 兼容 LLM 客户端。"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config.settings import Settings
from app.models.error_codes import ErrorCode
from app.utils.exceptions import AppException


class LanguageModelClient:
    def __init__(self, settings: Settings) -> None:
        api_key = (
            settings.llm_api_key.get_secret_value().strip()
            if settings.llm_api_key is not None
            else ""
        )
        self._base_url = (settings.llm_base_url or "").strip()
        self._api_key = api_key
        self._model = settings.llm_model
        self._enable_thinking = settings.llm_enable_thinking
        self._timeout = settings.llm_timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self._base_url and self._api_key)

    async def chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
    ) -> str:
        if not self.available:
            raise RuntimeError("LLM 未配置")
        url = self._base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "enable_thinking": self._enable_thinking,
        }
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(4):
                try:
                    response = await client.post(
                        url,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"]
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError("LLM 返回空内容")
                    return content.strip()
                except Exception as exc:
                    last_error = exc
                    if attempt < 3:
                        await asyncio.sleep(2**attempt)
        raise AppException(ErrorCode.LLM_CALL_FAILED) from last_error
