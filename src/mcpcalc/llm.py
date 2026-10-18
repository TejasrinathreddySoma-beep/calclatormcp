"""LLM adapters. Anything with `async chat_json(messages, schema) -> str` can be used (Ollama, fakes, oracles)."""
from __future__ import annotations

import json
import time

KEEP_ALIVE = "30m"  # Ollama unloads an idle model after 5 minutes by default; reloading takes 20-30 s


class OllamaLLM:
    def __init__(self, model: str, host: str | None = None, temperature: float = 0.0):
        import ollama

        self.model = model
        self.temperature = temperature
        self._client = ollama.AsyncClient(host=host) if host else ollama.AsyncClient()

    async def chat_json(self, messages: list[dict], schema: dict) -> str:
        reply = await self._client.chat(model=self.model, messages=messages, format=schema,
                                        options={"temperature": self.temperature}, keep_alive=KEEP_ALIVE)
        return reply.message.content

    async def chat_text(self, messages: list[dict]) -> str:
        reply = await self._client.chat(model=self.model, messages=messages, keep_alive=KEEP_ALIVE)
        return reply.message.content

    async def warm_up(self) -> float:
        """Load the model into memory so the first real request is fast. Returns the seconds it took."""
        started = time.perf_counter()
        await self._client.chat(model=self.model, messages=[{"role": "user", "content": "hi"}],
                                options={"num_predict": 1}, keep_alive=KEEP_ALIVE)
        return time.perf_counter() - started


class ScriptedLLM:
    """Test double: returns the given raw replies in order (the last one repeats)."""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def chat_json(self, messages: list[dict], schema: dict) -> str:
        self.calls.append(messages)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    async def chat_text(self, messages: list[dict]) -> str:
        return "ok"


class OracleLLM:
    """Benchmark sanity check: always answers with the reference expression (an upper bound for a perfect model)."""

    def __init__(self):
        self.expression = ""

    async def chat_json(self, messages: list[dict], schema: dict) -> str:
        return json.dumps({"is_calculation": True, "expression": self.expression})

    async def chat_text(self, messages: list[dict]) -> str:
        return "ok"