"""Keyword search (BM25) over knowledge-base chunks, with two separate indexes.

Meeting records are indexed apart from current site content so that dated minutes
do not crowd out program pages for everyday questions.
"""

import difflib
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pontis_chat.rag.documents import Chunk, load_chunks

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "the a an of to in on for and or with by from is are was were be been it its this that as at what "
    "when where which who how does do did can could i you your our my me we they their there into "
    "than then so if not no tell please any some have has had will would should".split()
)
# Questions like "What is X?" carry almost no searchable words when X is the organization itself,
# because its name is on every page. Those questions are pointed at the overview pages instead.
_DEFINITIONAL = re.compile(r"^\s*(so )?(what('s| is| are| does| exactly)|who (is|are)|tell me about|explain|describe)\b", re.I)
_DEFINITIONAL_TERMS = ("about", "overview", "mission")
_COMMON_TERM_IDF = 1.0

# Current pages outrank reports, which outrank dated newsletters. One long report produces
# many chunks, so without this prior a short current page rarely makes the top results.
DEFAULT_TYPE_WEIGHTS = {"page": 2.0, "pdf": 1.0, "post": 1.0, "newsletter": 0.8}
TITLE_WEIGHT = 3
HEADING_WEIGHT = 2


def stem(token: str) -> str:
    """Fold plurals so "members" matches "member" and "municipalities" matches "municipality"."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


@dataclass(frozen=True)
class SearchHit:
    score: float
    chunk: Chunk


class BM25Index:
    def __init__(self, chunks: list[Chunk], *, type_weights: dict[str, float] | None = None, k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.type_weights = type_weights or {}
        self.k1, self.b = k1, b
        self.docs = [
            Counter(tokenize(c.text) + tokenize(c.title) * TITLE_WEIGHT + tokenize(c.heading) * HEADING_WEIGHT)
            for c in chunks
        ]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.average_length = sum(self.lengths) / max(len(self.lengths), 1)
        document_frequency: Counter[str] = Counter()
        for doc in self.docs:
            document_frequency.update(doc.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in document_frequency.items()}
        self._vocabulary = sorted(self.idf)

    def _correct(self, token: str) -> str:
        """Map a misspelled query word to the closest indexed word."""
        if token in self.idf or len(token) < 4:
            return token
        close = difflib.get_close_matches(token, self._vocabulary, n=1, cutoff=0.8)
        return close[0] if close else token

    def query_terms(self, query: str) -> list[str]:
        terms = [self._correct(t) for t in tokenize(query)]
        only_common_terms = all(self.idf.get(t, 0.0) < _COMMON_TERM_IDF for t in terms)
        if _DEFINITIONAL.match(query) and only_common_terms:
            terms.extend(_DEFINITIONAL_TERMS)
        return terms

    def search(self, query: str, k: int = 5) -> list[SearchHit]:
        """Return the best chunk for each of the top ``k`` documents."""
        terms = self.query_terms(query)
        scored: list[tuple[float, int]] = []
        for i, doc in enumerate(self.docs):
            score = 0.0
            for term in terms:
                tf = doc.get(term)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.average_length)
                    score += self.idf[term] * tf * (self.k1 + 1) / norm
            if score:
                scored.append((score * self.type_weights.get(self.chunks[i].doc_type, 1.0), i))
        scored.sort(reverse=True)
        seen: set[str] = set()
        hits: list[SearchHit] = []
        for score, i in scored:
            chunk = self.chunks[i]
            if chunk.url in seen:
                continue
            seen.add(chunk.url)
            hits.append(SearchHit(score, chunk))
            if len(hits) >= k:
                break
        return hits


class KnowledgeBase:
    """The searchable knowledge base: one index for site content, one for meeting records."""

    def __init__(self, chunks: list[Chunk]):
        # A chunk without a source URL cannot be cited, so it is never retrieved.
        chunks = [c for c in chunks if c.url]
        self.chunks = chunks
        self.site = BM25Index([c for c in chunks if not c.is_meeting_record], type_weights=DEFAULT_TYPE_WEIGHTS)
        self.meetings = BM25Index([c for c in chunks if c.is_meeting_record])
        self._by_url: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            self._by_url.setdefault(chunk.url, []).append(chunk)

    @classmethod
    def from_directory(cls, kb_dir: str | Path) -> "KnowledgeBase":
        return cls(load_chunks(kb_dir))

    def search_site(self, query: str, k: int = 5) -> list[SearchHit]:
        return self.site.search(query, k)

    def search_meetings(self, query: str, k: int = 5, year: str | None = None) -> list[SearchHit]:
        hits = self.meetings.search(query, k if not year else k * 6)
        if year:
            hits = [h for h in hits if h.chunk.year == str(year)]
        return hits[:k]

    def get_document(self, url: str) -> list[Chunk]:
        return self._by_url.get(url, [])

    def has_url(self, url: str) -> bool:
        return url in self._by_url
