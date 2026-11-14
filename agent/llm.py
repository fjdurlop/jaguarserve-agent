"""OpenAI-compatible chat client for vLLM (and an optional hosted fallback).

`stream()` yields ("token", str) while the model writes and ends with ("reply", Reply).
`ready()` probes `/models`; with KEDA's HTTP add-on that request also wakes a scaled-to-zero server.
"""

import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

_THINK = re.compile(r"<think>.*?(</think>|$)", re.S)


class LLMUnavailable(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class Reply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM(Protocol):
    name: str

    async def ready(self) -> bool: ...
    def stream(self, messages: list[dict], tools: list[dict] | None) -> AsyncIterator[tuple[str, Any]]: ...


def strip_think(text: str) -> str:
    return _THINK.sub("", text).strip()


class OpenAICompatLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "EMPTY",
        timeout: float = 60.0,
        enable_thinking: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        vllm_extras: bool = True,
    ):
        self.name = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "EMPTY"
        self.client = AsyncOpenAI(
            base_url=self.base_url, api_key=self.api_key, timeout=timeout, max_retries=1
        )
        self.params: dict[str, Any] = {"temperature": temperature, "max_tokens": max_tokens}
        if vllm_extras:  # Qwen3 chat template switch; ignored by models without thinking mode
            self.params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
        self._ready_until = 0.0

    async def ready(self) -> bool:
        if time.monotonic() < self._ready_until:
            return True
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}
                )
            ok = resp.status_code == 200
        except httpx.HTTPError:
            ok = False
        if ok:
            self._ready_until = time.monotonic() + 15
        return ok

    async def stream(self, messages: list[dict], tools: list[dict] | None) -> AsyncIterator[tuple[str, Any]]:
        kwargs: dict[str, Any] = {"model": self.name, "messages": messages, "stream": True, **self.params}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        content: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        in_think = False
        try:
            stream = await self.client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    content.append(delta.content)
                    text = delta.content
                    if "<think>" in text:
                        in_think = True
                    if not in_think:
                        yield "token", text
                    if "</think>" in text:
                        in_think = False
                for tc in delta.tool_calls or []:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
        except (APIConnectionError, APITimeoutError) as exc:
            self._ready_until = 0.0
            raise LLMUnavailable("llm_unavailable") from exc
        except APIStatusError as exc:
            self._ready_until = 0.0
            raise LLMUnavailable(f"llm_status_{exc.status_code}") from exc
        yield (
            "reply",
            Reply(
                content=strip_think("".join(content)),
                tool_calls=[
                    ToolCall(c["id"] or f"call_{i}", c["name"], c["arguments"])
                    for i, c in sorted(calls.items())
                ],
            ),
        )
