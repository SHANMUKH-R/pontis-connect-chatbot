"""Run the agent loop on a model served through an OpenAI-compatible API.

The loop speaks the Anthropic message format. This adapter translates each request and
response, so a second model (Gemini, or an open model on Groq or Ollama) can be compared
with Claude without changing the loop, the tools or the guardrails.
"""

import json
import time
from types import SimpleNamespace
from typing import Any

import openai


class ModelUnavailable(Exception):
    """The model provider could not answer. ``reason`` is a short code for the reply flags."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _without_additional_properties(schema: dict[str, Any]) -> dict[str, Any]:
    # Gemini's function declarations reject "additionalProperties".
    return {key: value for key, value in schema.items() if key != "additionalProperties"}


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": _without_additional_properties(tool["input_schema"]),
            },
        }
        for tool in tools
    ]


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            converted.append({"role": message["role"], "content": content})
        elif message["role"] == "user":
            for result in content:
                converted.append({"role": "tool", "tool_call_id": result["tool_use_id"], "content": result["content"]})
        else:
            text = "\n".join(block.text for block in content if block.type == "text")
            # Each call goes back exactly as the provider sent it. Gemini attaches a signature to its
            # tool calls and rejects the next request if the signature is missing.
            calls = [block.raw for block in content if block.type == "tool_use"]
            assistant: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                assistant["tool_calls"] = calls
            converted.append(assistant)
    return converted


def _parse_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return {"_invalid_json": arguments}
    return parsed if isinstance(parsed, dict) else {"_invalid_json": arguments}


def to_anthropic_response(completion: Any) -> SimpleNamespace:
    choice = completion.choices[0]
    blocks: list[SimpleNamespace] = []
    if choice.message.content:
        blocks.append(SimpleNamespace(type="text", text=choice.message.content))
    for call in choice.message.tool_calls or []:
        blocks.append(
            SimpleNamespace(
                type="tool_use",
                id=call.id,
                name=call.function.name,
                input=_parse_arguments(call.function.arguments),
                raw=call.model_dump(exclude_none=True),
            )
        )
    if choice.finish_reason == "content_filter":
        stop_reason = "refusal"
    elif choice.finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "tool_use" if choice.message.tool_calls else "end_turn"
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class OpenAICompatibleClient:
    """Offers ``client.messages.create(...)`` like the Anthropic client, backed by a chat-completions API."""

    def __init__(self, *, api_key: str, base_url: str, min_interval_seconds: float = 0.0, client: Any | None = None):
        self._client = client or openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=5)
        self._min_interval = min_interval_seconds
        self._last_call = 0.0
        self.messages = SimpleNamespace(create=self._create)

    def _create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        **_claude_only: Any,
    ) -> SimpleNamespace:
        # Free tiers allow only a few requests a minute, so calls can be spaced out.
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        try:
            completion = self._client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=to_openai_messages(system, messages),
                tools=to_openai_tools(tools),
                tool_choice="auto",
            )
        except openai.RateLimitError as error:
            raise ModelUnavailable("llm_rate_limited") from error
        except openai.APIConnectionError as error:
            raise ModelUnavailable("llm_unreachable") from error
        except openai.APIStatusError as error:
            raise ModelUnavailable(f"llm_http_{error.status_code}") from error
        return to_anthropic_response(completion)
