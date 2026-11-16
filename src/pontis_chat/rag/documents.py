"""Load Markdown knowledge-base files and split them into retrievable chunks."""

import re
from dataclasses import dataclass
from pathlib import Path

# Front-matter types that are meeting records rather than current site content.
MEETING_TYPES = frozenset({"minutes", "agenda", "meeting_material"})

_FRONT_MATTER_LINE = re.compile(r'^(\w+):\s*"?(.*?)"?\s*$', re.M)
_HEADING = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    url: str
    title: str
    heading: str
    text: str
    doc_type: str
    as_of: str
    year: str
    path: str

    @property
    def is_meeting_record(self) -> bool:
        return self.doc_type in MEETING_TYPES


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    """Split a Markdown file into its YAML-style front matter and its body."""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            return dict(_FRONT_MATTER_LINE.findall(parts[1])), parts[2]
    return {}, raw


def split_sections(body: str) -> list[tuple[str, str]]:
    """Split a Markdown body into (heading, text) sections."""
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in body.splitlines():
        match = _HEADING.match(line.strip())
        if match:
            sections.append((match.group(1).strip(), []))
        else:
            sections[-1][1].append(line)
    return [(heading, "\n".join(lines).strip()) for heading, lines in sections if "".join(lines).strip()]


def chunk_document(path: Path, *, max_words: int = 220, overlap: int = 40) -> list[Chunk]:
    """Turn one Markdown file into chunks of at most ``max_words`` words.

    Sections are packed together until the word limit is reached, so short sections
    under one page stay in the same chunk and long sections are split with overlap.
    """
    meta, body = parse_front_matter(path.read_text(errors="ignore"))
    if meta.get("status", "canonical") != "canonical":
        return []
    title = meta.get("title", path.stem)

    def make(heading: str, words: list[str]) -> Chunk:
        return Chunk(
            url=meta.get("url", ""),
            title=title,
            heading=heading,
            text=" ".join(words),
            doc_type=meta.get("type", ""),
            as_of=meta.get("as_of", "") or meta.get("modified", ""),
            year=meta.get("year", ""),
            path=str(path),
        )

    chunks: list[Chunk] = []
    pending: list[str] = []
    pending_heading = ""
    for heading, text in split_sections(body):
        words = text.split()
        if pending and len(pending) + len(words) > max_words:
            chunks.append(make(pending_heading, pending))
            pending = []
        if not pending:
            pending_heading = heading
        pending.extend(words)
        while len(pending) > max_words:
            chunks.append(make(pending_heading, pending[:max_words]))
            pending = pending[max_words - overlap :]
    if pending:
        chunks.append(make(pending_heading, pending))
    return chunks


def load_chunks(kb_dir: str | Path, *, max_words: int = 220) -> list[Chunk]:
    """Load every canonical Markdown document under ``kb_dir`` as chunks."""
    chunks: list[Chunk] = []
    for path in sorted(Path(kb_dir).rglob("*.md")):
        if "originals" in path.parts or path.name.startswith("00_"):
            continue
        chunks.extend(chunk_document(path, max_words=max_words))
    return chunks
