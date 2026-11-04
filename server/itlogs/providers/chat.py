"""One OpenAI-compatible chat client with JSON-schema output, used by both the reader and the
reply parser. The same code reaches Muse Spark on the Meta Model API, Muse Spark Open on
Baseten or Modal, and Muse Glimmer on this Mac through llama-server: which one is three env
values (config.py). Nothing outside providers/ knows an endpoint.

An endpoint that refuses response_format or reasoning_effort answers 400, and the first such 400
switches this client to plain mode: the schema goes into the system prompt and the JSON object is
cut out of the text. Baseten's docs say Muse Spark Open has no structured output mode, but it took
the schema when measured on 2026-NOVEMBER-03, so this fallback has not fired on a live endpoint."""

from __future__ import annotations

import base64
import json
import logging
import time

import httpx

log = logging.getLogger("itlogs.chat")


def data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def json_object(text: str) -> dict | None:
    """The first JSON object in a reply: bare, inside a code fence, or after a sentence."""
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        d = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


class ChatModel:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        reasoning_effort: str | None = None,
        plain: bool = False,
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
        # plain: no response_format and no reasoning_effort on the wire; the schema is in the
        # prompt instead. Set from the start for an endpoint known not to take them, or
        # switched on by the first 400 that mentions them.
        self.plain = plain
        self.latency_ms: list[float] = []
        self.last_usage: dict[str, int | None] = {}

    def _body(self, system: str, content: list[dict], schema: dict, max_tokens: int) -> dict:
        if self.plain:
            system = (
                system
                + " Answer with one JSON object and nothing else, no prose, no code fence. "
                + "Its schema: "
                + json.dumps(schema.get("schema", schema))
            )
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "max_tokens": max_tokens,
        }
        if not self.plain:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
        return body

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict,
        jpeg: bytes | list[bytes] | None = None,
        max_tokens: int = 1500,
    ) -> dict | None:
        """One call, one JSON object back (None when the model returned nothing usable)."""
        content: list[dict] = [{"type": "text", "text": user}]
        images = [jpeg] if isinstance(jpeg, bytes) else (jpeg or [])
        for image in images:
            content.append({"type": "image_url", "image_url": {"url": data_url(image)}})
        t0 = time.perf_counter()
        r = await self._http.post(
            "/chat/completions", json=self._body(system, content, schema, max_tokens)
        )
        if r.status_code == 400 and not self.plain:
            # the endpoint refused the structured-output fields: say so once, go plain, retry
            log.warning("400 on the structured call, switching to plain mode: %r", r.text[:200])
            self.plain = True
            r = await self._http.post(
                "/chat/completions", json=self._body(system, content, schema, max_tokens)
            )
        self.latency_ms.append((time.perf_counter() - t0) * 1000)
        r.raise_for_status()
        data = r.json()
        # where the time went: prompt (image) tokens vs completion, and the reasoning share
        # when the endpoint reports it (Muse Spark Open always reasons; this is the cost)
        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        self.last_usage = {
            "prompt": usage.get("prompt_tokens"),
            "completion": usage.get("completion_tokens"),
            "reasoning": details.get("reasoning_tokens"),
        }
        choice = data["choices"][0]
        raw = choice["message"].get("content")
        if not raw:
            # reasoning models spend the budget before the answer; say so instead of crashing
            log.warning("empty content, finish_reason=%s", choice.get("finish_reason"))
            return None
        d = json_object(raw)
        if d is None:
            log.warning("structured output is not JSON: %r", raw[:120])
        return d

    async def aclose(self) -> None:
        await self._http.aclose()
