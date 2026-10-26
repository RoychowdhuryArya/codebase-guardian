"""
Archwarden — NVIDIA Nemotron Client
Wraps the OpenAI-compatible NVIDIA NIM API.
Exposes Nano/Super/Ultra dispatch for the principle mining cascade.
"""
from __future__ import annotations

import os
from typing import Iterator

try:
    from openai import OpenAI
    _OPENAI_OK = True
except ImportError:
    _OPENAI_OK = False


class NemotronClient:
    """
    OpenAI-compatible client pointing at NVIDIA NIM.
    Base URL: https://integrate.api.nvidia.com/v1
    """

    def __init__(self):
        from config import settings
        self._settings = settings
        self._client: "OpenAI | None" = None

        if _OPENAI_OK and settings.nvidia_api_key:
            self._client = OpenAI(
                api_key=settings.nvidia_api_key,
                base_url=settings.nvidia_api_base,
            )

    @property
    def available(self) -> bool:
        return self._client is not None

    def complete(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        stream: bool = False,
    ) -> str:
        """Blocking completion. Returns full response text."""
        if not self._client:
            return "[LLM unavailable — set NVIDIA_API_KEY to enable]"
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            resp = self._client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            return f"[LLM error: {e}]"

    def stream(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """Streaming completion — yields text chunks."""
        if not self._client:
            yield "[LLM unavailable — set NVIDIA_API_KEY to enable]"
            return
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            for chunk in self._client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            ):
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            yield f"[LLM stream error: {e}]"

    # ── Model-level shortcuts ──────────────────────────────────────────────────

    def nano(self, system: str, user: str, **kw) -> str:
        return self.complete(self._settings.model_nano, system, user, **kw)

    def super_(self, system: str, user: str, **kw) -> str:
        return self.complete(self._settings.model_super, system, user, **kw)

    def ultra(self, system: str, user: str, **kw) -> str:
        return self.complete(self._settings.model_ultra, system, user, **kw)

    def verify_model_ids(self) -> dict[str, bool]:
        """
        Check which configured model IDs are actually available.
        Returns {model_id: available}
        """
        if not self._client:
            return {}
        try:
            models = self._client.models.list()
            available_ids = {m.id for m in models.data}
            return {
                self._settings.model_nano: self._settings.model_nano in available_ids,
                self._settings.model_super: self._settings.model_super in available_ids,
                self._settings.model_ultra: self._settings.model_ultra in available_ids,
            }
        except Exception:
            return {}


# Singleton
_client: NemotronClient | None = None


def get_client() -> NemotronClient:
    global _client
    if _client is None:
        _client = NemotronClient()
    return _client
