from pontis_chat.rag import KnowledgeBase


def urls(hits):
    return [hit.chunk.url for hit in hits]


def test_only_canonical_documents_with_a_url_are_indexed(kb: KnowledgeBase):
    indexed = {chunk.url for chunk in kb.chunks}

    assert "https://example.org/old-bylaws" not in indexed
    assert "" not in indexed


def test_meeting_records_are_kept_out_of_site_search(kb: KnowledgeBase):
    assert "https://example.org/minutes-2025" not in urls(kb.search_site("recycling contract"))
    assert urls(kb.search_meetings("recycling contract")) == ["https://example.org/minutes-2025"]


def test_meeting_search_filters_by_year(kb: KnowledgeBase):
    assert kb.search_meetings("recycling", year="2024") == []
    assert len(kb.search_meetings("recycling", year="2025")) == 1


def test_current_page_outranks_report_on_the_same_topic(kb: KnowledgeBase):
    assert urls(kb.search_site("recycling"))[0] == "https://example.org/recycling/"


def test_misspelled_and_plural_words_still_match(kb: KnowledgeBase):
    assert urls(kb.search_site("recyclng programs"))[0] == "https://example.org/recycling/"


def test_question_about_the_organization_itself_finds_the_about_page(kb: KnowledgeBase):
    assert urls(kb.search_site("What is this?"))[0] == "https://example.org/about/"


def test_each_document_appears_once_in_results(kb: KnowledgeBase):
    found = urls(kb.search_site("recycling contract members"))

    assert len(found) == len(set(found))
