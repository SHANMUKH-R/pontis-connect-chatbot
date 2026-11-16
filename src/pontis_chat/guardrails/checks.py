"""Deterministic safety checks that run before and after the language model.

Input checks decide whether a message reaches the model at all and what the model
is allowed to see. Output checks decide what the member is allowed to see. Neither
depends on the model behaving well, which is the point of having them.
"""

import re
from dataclasses import dataclass, field

MAX_QUESTION_CHARS = 1500

_TAG = re.compile(r"<[^>]{0,400}>")
_TEMPLATE = re.compile(r"\{\{.*?\}\}|\$\{.*?\}|<%.*?%>", re.S)
_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_SENTENCE_END = re.compile(r"(?<=[.!?\n])\s+")

_PII_PATTERNS = (
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")),
)

_CRISIS = re.compile(
    r"\b(suicid\w*|kill (myself|himself|herself|themselves)|end (my|his|her|their) life|want to die|"
    r"don'?t see the point|no reason to live|hurt (myself|himself|herself)|self[- ]harm|overdos\w*|"
    r"withdrawal|relaps\w*|using (drugs )?again|in danger right now|being abused)\b",
    re.I,
)

_INJECTION = re.compile(
    r"(ignore|disregard|forget|override)\b[^.?!\n]{0,40}\b(instruction|rule|prompt|guideline|polic)\w*|"
    r"\b(system|developer|hidden|initial) (prompt|message|instruction)s?\b|"
    r"\b(reveal|print|show|repeat|output|leak)\b[^.?!\n]{0,30}\b(instruction|prompt|rule|configuration)s?\b|"
    r"\b(what|which) (were|are) (the |your )?(exact )?(instruction|rule|prompt)s?\b|"
    r"\byou are now\b|\bfrom now on\b|\bnew instructions?\b|\bdeveloper mode\b|\bjailbreak\b|\bDAN\b|"
    r"\b(pretend|act|role-?play)\b[^.?!\n]{0,20}\b(you are|you're|to be|as)\b",
    re.I,
)

_ACTION_CLAIM = re.compile(
    r"\bI(?:'ve| have| just)? (updated|changed|removed|registered|signed you|reset|deleted|cancell?ed|"
    r"unsubscribed|subscribed|sent|emailed|booked|scheduled|submitted|saved|recorded your)\b|"
    r"\byou(?:'re| are) (now )?(registered|subscribed|unsubscribed|signed up|enrolled)\b|"
    r"\bI(?:'ll| will) remember\b",
    re.I,
)

_URL = re.compile(r"https?://[^\s)\]>\"']+")


def crisis_message() -> str:
    return (
        "I'm really sorry you're dealing with this. I'm an information assistant and can't give emergency help. "
        "If someone is in immediate danger, call 911. For a mental health or substance use crisis, call or text 988 "
        "(Suicide & Crisis Lifeline), any time. You can also ask me about programs and I'll share what I can find."
    )


def refusal_message(org_name: str) -> str:
    return (
        f"I can't share my instructions or change how I work. "
        f"I can help with questions about {org_name}, its programs, members and events."
    )


def action_decline_message(org_name: str) -> str:
    return (
        f"I can't make changes or take actions on your behalf. I can only share information. "
        f"Please contact {org_name} staff directly for that."
    )


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Replace personal identifiers with placeholders. Returns the text and the kinds found."""
    found: list[str] = []
    for kind, pattern in _PII_PATTERNS:
        text, count = pattern.subn(f"[{kind} removed]", text)
        if count:
            found.append(kind)
    return text, found


def normalize_url(url: str) -> str:
    url = re.sub(r"^https?://(www\.)?", "", url.strip().lower())
    return url.split("#")[0].rstrip("/.,;")


@dataclass(frozen=True)
class InputVerdict:
    """What the input checks decided about one member message."""

    question: str  # the text the model and the question log are allowed to see
    search_query: str  # the question with instruction-like sentences removed, for retrieval
    flags: tuple[str, ...] = ()
    direct_answer: str | None = None  # set when the guardrail answers and the model is skipped
    direct_status: str = "ok"


def check_input(question: str, *, org_name: str, max_chars: int = MAX_QUESTION_CHARS) -> InputVerdict:
    """Screen one member message before retrieval and before the model sees it."""
    flags: list[str] = []
    text = (question or "").strip()

    cleaned = _TEMPLATE.sub(" ", _TAG.sub(" ", text))
    if cleaned != text:
        flags.append("markup_removed")
    cleaned = " ".join(cleaned.split())

    if len(_WORD.findall(cleaned)) < 1:
        flags.append("no_question")
        reply = f"I didn't catch a question there. Ask me anything about {org_name}."
        return InputVerdict("", "", tuple(flags), reply, "unavailable")

    words = cleaned.lower().split()
    if len(cleaned) > max_chars or (len(words) > 30 and len(set(words)) / len(words) < 0.3):
        flags.append("too_long_or_repetitive")
        reply = "That message is too long or repetitive for me to answer. Please ask one short question."
        return InputVerdict("", "", tuple(flags), reply, "unavailable")

    if _CRISIS.search(cleaned):
        flags.append("crisis")
        redacted, _ = redact_pii(cleaned)
        return InputVerdict(redacted, "", tuple(flags), crisis_message(), "ok")

    cleaned, pii_kinds = redact_pii(cleaned)
    if pii_kinds:
        flags.append("pii_redacted:" + ",".join(pii_kinds))

    search_query = cleaned
    if _INJECTION.search(cleaned):
        flags.append("injection_suspected")
        kept = [s for s in _SENTENCE_END.split(cleaned) if not _INJECTION.search(s)]
        search_query = " ".join(kept).strip()
        if len(_WORD.findall(search_query)) < 2:
            return InputVerdict(cleaned, "", tuple(flags), refusal_message(org_name), "unavailable")

    return InputVerdict(cleaned, search_query, tuple(flags))


@dataclass(frozen=True)
class OutputVerdict:
    answer: str
    sources: list[dict[str, str]]
    flags: tuple[str, ...] = field(default_factory=tuple)
    status: str | None = None  # set only when the check overrides the reply's status


def check_output(
    answer: str,
    sources: list[dict[str, str]],
    *,
    allowed_urls: set[str],
    org_name: str,
    secret_markers: tuple[str, ...] = (),
) -> OutputVerdict:
    """Screen a drafted reply before it is returned to the member.

    ``allowed_urls`` is every URL the retriever returned for this question; a reply
    may only cite or link to those.
    """
    flags: list[str] = []
    text = _TAG.sub("", answer or "").strip()
    if text != (answer or "").strip():
        flags.append("markup_removed")

    if any(marker and marker in text for marker in secret_markers):
        return OutputVerdict(refusal_message(org_name), [], ("prompt_leak_blocked",), "unavailable")

    if _ACTION_CLAIM.search(text):
        return OutputVerdict(action_decline_message(org_name), [], ("action_claim_blocked",), "unavailable")

    allowed = {normalize_url(u) for u in allowed_urls}
    kept_sources = [s for s in sources if normalize_url(s.get("url", "")) in allowed]
    if len(kept_sources) != len(sources):
        flags.append("unretrieved_source_removed")

    def keep_or_remove(match: re.Match[str]) -> str:
        if normalize_url(match.group(0)) in allowed:
            return match.group(0)
        flags.append("unretrieved_link_removed")
        return "[link removed]"

    text = _URL.sub(keep_or_remove, text)
    return OutputVerdict(text, kept_sources, tuple(dict.fromkeys(flags)))
