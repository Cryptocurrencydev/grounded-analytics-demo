"""Model access. The only module that imports the Anthropic SDK."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

MODEL = os.environ.get("LLM_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("LLM_EFFORT", "low")


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    stop_reason: str | None
    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    content: Any = None  # replayed as-is on the next turn of a tool loop
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    name: str

    def create(self, *, system: str, messages: list[dict], schema: dict | None = None,
               tools: list[dict] | None = None, effort: str | None = None,
               max_tokens: int = 8000, cache_prompt: bool = False) -> LLMResponse: ...


class LLMUnavailable(RuntimeError):
    pass


class AnthropicLLM:
    name = MODEL

    def __init__(self, timeout: float = 100.0) -> None:
        import anthropic

        self._anthropic = anthropic
        # An empty key is fine here: the request fails later and the caller shows the safe fallback
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or "unset", timeout=timeout, max_retries=1)

    def create(self, *, system, messages, schema=None, tools=None, effort=None, max_tokens=8000, cache_prompt=False):
        output_config: dict = {"effort": effort or EFFORT}
        if schema:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        system_block: dict = {"type": "text", "text": system}
        if cache_prompt:
            system_block["cache_control"] = {"type": "ephemeral"}
        kwargs: dict = dict(
            model=MODEL, max_tokens=max_tokens, system=[system_block], messages=messages,
            output_config=output_config, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if tools:
            kwargs["tools"] = tools
        a = self._anthropic
        try:
            # Large requests stream so the SDK's non-streaming timeout guard never trips
            if max_tokens > 16000:
                with self.client.beta.messages.stream(**kwargs) as stream:
                    r = stream.get_final_message()
            else:
                r = self.client.beta.messages.create(**kwargs)
        except a.RateLimitError as e:
            raise LLMUnavailable("rate_limited") from e
        except a.APIStatusError as e:
            raise LLMUnavailable(f"api_status_{e.status_code}") from e
        except a.APIConnectionError as e:
            raise LLMUnavailable("connection") from e
        text = "".join(b.text for b in r.content if b.type == "text")
        uses = [ToolUse(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"]
        usage = {
            "input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens,
            "cache_read_tokens": getattr(r.usage, "cache_read_input_tokens", 0) or 0,
            "cache_write_tokens": getattr(r.usage, "cache_creation_input_tokens", 0) or 0,
        }
        return LLMResponse(r.stop_reason, text, uses, r.content, usage)


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        if os.environ.get("LLM_MODE") == "mock":
            from .llm_mock import MockLLM

            _llm = MockLLM()
        else:
            _llm = AnthropicLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    global _llm
    _llm = llm
