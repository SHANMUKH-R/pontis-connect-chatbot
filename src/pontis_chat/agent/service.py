"""Answer one member question: input checks, then the agent, then output checks, then the log."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import anthropic
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from pontis_chat.agent.loop import PROMPT_MARKER, run_agent
from pontis_chat.agent.providers import ModelUnavailable, OpenAICompatibleClient
from pontis_chat.agent.tools import ToolContext
from pontis_chat.guardrails import InputVerdict, check_input, check_output
from pontis_chat.guardrails.checks import redact_pii
from pontis_chat.rag import KnowledgeBase

logger = logging.getLogger(__name__)

DONT_KNOW = "I couldn't find that in the organization's published content. Please contact staff directly."
TEMPORARILY_DOWN = "The assistant is temporarily unavailable. Please try again in a moment."


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True, hide_input_in_errors=True)

    org_name: str = Field(default="the organization", min_length=1)
    knowledge_base_dir: str = "data/knowledge_base"
    question_log_path: str = "data/question_log.jsonl"
    guardrails: bool = True
    # False swaps the system prompt for a bare one with no behavior rules. For evaluation only.
    agent_rules: bool = True
    # True also logs each answer and the passages the model was shown, so answers can be graded for
    # groundedness. For evaluation runs only: it makes the log large.
    log_evidence: bool = False
    # Without a key the service still runs, answering with the best search excerpt only.
    anthropic_api_key: SecretStr | None = Field(default=None, repr=False)
    anthropic_model: str = "claude-haiku-5-5"
    # A second model for comparison runs, reached through an OpenAI-compatible API (Gemini, Groq, Ollama).
    # Used instead of Claude when LLM_PROVIDER=openai_compatible.
    llm_provider: str = Field(default="anthropic", pattern="^(anthropic|openai_compatible)$")
    llm_base_url: str = ""
    llm_api_key: SecretStr | None = Field(default=None, repr=False)
    llm_model: str = ""
    llm_min_interval_seconds: float = Field(default=0.0, ge=0)
    agent_effort: str = "low"
    agent_max_steps: int = Field(default=6, ge=1, le=12)

    @property
    def model_name(self) -> str:
        return self.llm_model if self.llm_provider == "openai_compatible" else self.anthropic_model


@dataclass
class ChatReply:
    answer: str
    sources: list[dict[str, str]]
    status: str  # "ok", "unavailable" or "error"
    retrieved: list[str] = field(default_factory=list)
    mode: str = "agent"  # "agent", "retrieval_only" or "guardrail"
    flags: list[str] = field(default_factory=list)


class ChatService:
    def __init__(self, kb: KnowledgeBase, settings: ChatSettings, client: Any | None = None):
        self.kb = kb
        self.settings = settings
        self.client = client

    def answer(self, question: str, history: list[str] | None = None) -> ChatReply:
        history = [turn for turn in (history or []) if isinstance(turn, str)]
        org = self.settings.org_name
        if self.settings.guardrails:
            verdict = check_input(question, org_name=org)
            history = [redact_pii(turn)[0] for turn in history]
        else:
            verdict = InputVerdict(question or "", question or "")

        guarded = self.settings.guardrails
        ctx = ToolContext(self.kb, enforce_citations=guarded, screen_retrieved=guarded)
        if verdict.direct_answer is not None:
            reply = ChatReply(verdict.direct_answer, [], verdict.direct_status, mode="guardrail")
        elif self.client is not None:
            reply = self._agent_reply(ctx, verdict.question, history)
        else:
            reply = self._retrieval_only_reply(ctx, verdict.search_query, history)
        reply.flags = list(verdict.flags) + ctx.flags + reply.flags

        if self.settings.guardrails and reply.mode != "guardrail":
            checked = check_output(
                reply.answer, reply.sources, allowed_urls=set(ctx.retrieved), org_name=org, secret_markers=(PROMPT_MARKER,)
            )
            reply.answer, reply.sources = checked.answer, checked.sources
            reply.status = checked.status or reply.status
            reply.flags += list(checked.flags)

        self._log(verdict.question, ctx, reply)
        return reply

    def _agent_reply(self, ctx: ToolContext, question: str, history: list[str]) -> ChatReply:
        settings = self.settings
        try:
            result = run_agent(
                self.client,
                ctx,
                model=settings.model_name,
                org_name=settings.org_name,
                question=question,
                history=history,
                effort=settings.agent_effort,
                max_steps=settings.agent_max_steps,
                rules=settings.agent_rules,
            )
        except ModelUnavailable as error:
            logger.warning("language model unavailable: %s", error.reason)
            return ChatReply(TEMPORARILY_DOWN, [], "error", flags=[error.reason])
        except anthropic.RateLimitError:
            logger.warning("language model rate limited")
            return ChatReply(TEMPORARILY_DOWN, [], "error", flags=["llm_rate_limited"])
        except anthropic.APIConnectionError:
            logger.warning("language model unreachable")
            return ChatReply(TEMPORARILY_DOWN, [], "error", flags=["llm_unreachable"])
        except anthropic.APIStatusError as error:
            logger.error("language model request failed: %s", error.status_code)
            return ChatReply(TEMPORARILY_DOWN, [], "error", flags=[f"llm_http_{error.status_code}"])

        retrieved = list(ctx.retrieved)
        if ctx.final is not None:
            sources = [{"title": ctx.retrieved.get(url, url), "url": url} for url in ctx.final.source_urls]
            status = "ok" if ctx.final.reply_type in ("answer", "clarify") else "unavailable"
            return ChatReply(ctx.final.answer, sources, status, retrieved, flags=[f"reply_type:{ctx.final.reply_type}"])
        if result.stop == "text" and result.text:
            return ChatReply(result.text, [], "ok", retrieved, flags=["answer_not_submitted"])
        return ChatReply(DONT_KNOW, [], "unavailable", retrieved, flags=[f"agent_stopped:{result.stop}"])

    def _retrieval_only_reply(self, ctx: ToolContext, query: str, history: list[str]) -> ChatReply:
        hits = self.kb.search_site(" ".join(history[-2:] + [query]))
        ctx.remember(hits)
        if not hits:
            return ChatReply(DONT_KNOW, [], "unavailable", mode="retrieval_only")
        top = hits[0].chunk
        excerpt = " ".join(top.text.split()[:90])
        sources = [{"title": h.chunk.title, "url": h.chunk.url} for h in hits]
        return ChatReply(f"From “{top.title}”: {excerpt}", sources, "ok", list(ctx.retrieved), mode="retrieval_only")

    def _log(self, question: str, ctx: ToolContext, reply: ChatReply) -> None:
        """Append one line per question for the report on what members ask. Never the raw message."""
        record = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "question": redact_pii(question)[0] if self.settings.guardrails else "[not stored: guardrails off]",
            "topic": ctx.topic,
            "answerable": ctx.answerable,
            "status": reply.status,
            "mode": reply.mode,
            "flags": reply.flags,
            "sources": [source["url"] for source in reply.sources],
        }
        if self.settings.log_evidence:
            record["answer"] = reply.answer
            record["evidence"] = ctx.evidence
        try:
            path = Path(self.settings.question_log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("could not write the question log")


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    """Build the service once per process: load settings, index the knowledge base, create the client."""
    settings = ChatSettings()
    kb = KnowledgeBase.from_directory(settings.knowledge_base_dir)
    client = build_client(settings)
    logger.info("chat service ready: %d chunks, mode=%s", len(kb.chunks), "agent" if client else "retrieval_only")
    return ChatService(kb, settings, client)


def build_client(settings: ChatSettings) -> Any | None:
    """Create the model client the settings ask for, or None when its key is missing."""
    if settings.llm_provider == "openai_compatible":
        if not (settings.llm_api_key and settings.llm_base_url and settings.llm_model):
            return None
        return OpenAICompatibleClient(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            min_interval_seconds=settings.llm_min_interval_seconds,
        )
    key = settings.anthropic_api_key
    return anthropic.Anthropic(api_key=key.get_secret_value()) if key else None
