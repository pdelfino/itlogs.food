"""One OpenAI-compatible chat client with JSON-schema output, used by both the reader and the
reply parser. The same code reaches Muse Spark on the Meta Model API, Muse Spark Open on
Baseten or Modal, and Muse Glimmer on this Mac through llama-server: which one is three env
values (config.py). Nothing outside providers/ knows an endpoint."""

from __future__ import annotations

import base64
import json
import logging
import time

import httpx

log = logging.getLogger("itlogs.chat")


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


class ChatModel:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(60, connect=10),
            transport=transport,
        )
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.latency_ms: list[float] = []

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict,
        jpeg: bytes | None = None,
        max_tokens: int = 1500,
    ) -> dict | None:
        """One call, one JSON object back (None when the model returned nothing usable)."""
        content: list[dict] = [{"type": "text", "text": user}]
        if jpeg is not None:
            content.append({"type": "image_url", "image_url": {"url": data_url(jpeg)}})
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_schema", "json_schema": schema},
            "max_tokens": max_tokens,
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        t0 = time.perf_counter()
        r = await self._http.post("/chat/completions", json=body)
        self.latency_ms.append((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
        choice = r.json()["choices"][0]
        raw = choice["message"].get("content")
        if not raw:
            # reasoning models spend the budget before the answer; say so instead of crashing
            log.warning("empty content, finish_reason=%s", choice.get("finish_reason"))
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("structured output is not JSON (%s): %r", e, raw[:120])
            return None

    async def aclose(self) -> None:
        await self._http.aclose()
