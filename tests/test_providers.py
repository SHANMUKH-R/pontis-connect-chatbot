import json
from types import SimpleNamespace

import httpx
import openai

from pontis_chat.agent.providers import OpenAICompatibleClient
from pontis_chat.agent.service import ChatService, ChatSettings, build_client

RECYCLING = "https://example.org/recycling/"


def tool_call(name, arguments, call_id="call_1"):
    raw = {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}, "extra_content": {"signature": "sig"}}
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments), model_dump=lambda **_: raw)


def completion(content=None, tool_calls=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


class FakeChatCompletions:
    """Stands in for the OpenAI SDK client: replays scripted completions and records each request."""

    def __init__(self, *completions):
        self.completions = list(completions)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        next_completion = self.completions.pop(0)
        if isinstance(next_completion, Exception):
            raise next_completion
        return next_completion


def service(kb, tmp_path, fake):
    settings = ChatSettings(_env_file=None, question_log_path=str(tmp_path / "log.jsonl"))
    client = OpenAICompatibleClient(api_key="unused", base_url="unused", client=fake)
    return ChatService(kb, settings, client)


def test_agent_loop_runs_on_an_openai_compatible_model(kb, tmp_path):
    answer = json.dumps({"answer": "Any member municipality can join.", "reply_type": "answer", "source_urls": [RECYCLING]})
    fake = FakeChatCompletions(
        completion(tool_calls=[tool_call("search_site_content", '{"query": "recycling eligibility"}')], finish_reason="tool_calls"),
        completion(tool_calls=[tool_call("submit_answer", answer, "call_2")], finish_reason="tool_calls"),
    )

    reply = service(kb, tmp_path, fake).answer("Who can join the recycling program?")

    assert reply.status == "ok"
    assert reply.sources == [{"title": "Recycling Program", "url": RECYCLING}]


def test_request_is_translated_to_chat_completions_format(kb, tmp_path):
    fake = FakeChatCompletions(
        completion(tool_calls=[tool_call("search_site_content", '{"query": "recycling"}')], finish_reason="tool_calls"),
        completion(tool_calls=[tool_call("submit_answer", '{"answer": "No.", "reply_type": "dont_know"}', "call_2")]),
    )

    service(kb, tmp_path, fake).answer("Is there recycling?")

    first, second = fake.requests
    assert first["messages"][0]["role"] == "system"
    assert first["tools"][0]["function"]["name"] == "search_site_content"
    assert "additionalProperties" not in first["tools"][0]["function"]["parameters"]
    assistant, tool_result = second["messages"][-2:]
    assert assistant["tool_calls"][0]["extra_content"] == {"signature": "sig"}
    assert tool_result["role"] == "tool" and tool_result["tool_call_id"] == "call_1"
    assert RECYCLING in tool_result["content"]


def test_arguments_that_are_not_json_come_back_to_the_model_as_a_tool_error(kb, tmp_path):
    fake = FakeChatCompletions(
        completion(tool_calls=[tool_call("search_site_content", "{not json")], finish_reason="tool_calls"),
        completion(tool_calls=[tool_call("submit_answer", '{"answer": "No.", "reply_type": "dont_know"}', "call_2")]),
    )

    service(kb, tmp_path, fake).answer("Is there recycling?")

    assert fake.requests[1]["messages"][-1]["content"].startswith("Error: bad arguments")


def test_provider_rate_limit_becomes_an_error_reply(kb, tmp_path):
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.example/v1/chat/completions"))
    fake = FakeChatCompletions(openai.RateLimitError("slow down", response=response, body=None))

    reply = service(kb, tmp_path, fake).answer("Who can join?")

    assert reply.status == "error"
    assert "llm_rate_limited" in reply.flags


def test_second_provider_without_its_settings_gives_no_client():
    settings = ChatSettings(_env_file=None, llm_provider="openai_compatible")

    assert build_client(settings) is None
    assert settings.model_name == ""
