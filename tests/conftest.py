from pathlib import Path

import pytest

from pontis_chat.rag import KnowledgeBase

_DOCS = {
    "about.md": (
        'title: "About"\nurl: "https://example.org/about/"\ntype: "page"\nmodified: "2026-01-10"',
        "# About\n\nThe Riverside Alliance brings neighboring towns together to solve shared problems. "
        "Members are municipalities, not individuals.",
    ),
    "recycling.md": (
        'title: "Recycling Program"\nurl: "https://example.org/recycling/"\ntype: "page"',
        "# Recycling Program\n\n## Who is eligible\n\nAny member municipality can join the shared recycling "
        "contract. Contact staff to enroll.",
    ),
    "report.md": (
        'title: "Annual Report"\nurl: "https://example.org/report.pdf"\ntype: "pdf"',
        "# Annual Report\n\nThe recycling contract saved members money. The solar program expanded.",
    ),
    "minutes.md": (
        'title: "Member Meeting Minutes"\nurl: "https://example.org/minutes-2025"\ntype: "minutes"\nyear: "2025"',
        "# Minutes\n\nThe board voted to approve the recycling contract renewal.",
    ),
    "old.md": (
        'title: "Old Bylaws"\nurl: "https://example.org/old-bylaws"\ntype: "pdf"\nstatus: "superseded"',
        "# Bylaws\n\nSuperseded recycling rules.",
    ),
    "no-url.md": ('title: "Flyer"\ntype: "post"', "# Flyer\n\nRecycling day flyer with no web address."),
}


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    for name, (front_matter, body) in _DOCS.items():
        (tmp_path / name).write_text(f"---\n{front_matter}\n---\n\n{body}\n")
    return tmp_path


@pytest.fixture
def kb(kb_dir: Path) -> KnowledgeBase:
    return KnowledgeBase.from_directory(kb_dir)
