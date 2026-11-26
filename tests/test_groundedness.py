import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("groundedness", Path(__file__).parents[1] / "eval" / "groundedness.py")
groundedness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(groundedness)


def claims(*verdicts):
    return [groundedness.Claim(claim="c", verdict=verdict, evidence_quote="") for verdict in verdicts]


def test_score_is_two_only_when_every_claim_is_supported():
    assert groundedness.score(claims("supported", "supported")) == 2
    assert groundedness.score(claims("supported", "supported", "unsupported")) == 1
    assert groundedness.score(claims("supported", "unsupported", "unsupported")) == 0


def test_any_contradicted_claim_scores_zero():
    assert groundedness.score(claims("supported", "supported", "supported", "contradicted")) == 0


def test_an_answer_with_no_claims_is_not_graded():
    assert groundedness.score([]) is None


def test_only_answers_with_evidence_are_sent_to_the_judge():
    passage = [{"url": "https://example.org/a", "title": "A", "text": "text"}]

    assert groundedness.is_gradable({"flags": ["reply_type:answer"], "answer": "Yes.", "evidence": passage})
    assert not groundedness.is_gradable({"flags": ["reply_type:dont_know"], "answer": "No idea.", "evidence": passage})
    assert not groundedness.is_gradable({"flags": ["reply_type:answer"], "answer": "Yes.", "evidence": []})


def test_summary_states_how_many_replies_were_graded():
    rows = [
        {"score": 2, "claims": 3, "supported": 3, "contradicted": 0},
        {"score": 0, "claims": 2, "supported": 1, "contradicted": 1},
        {"score": "", "claims": 0, "supported": 0, "contradicted": 0},
    ]

    summary = groundedness.summarize(rows, total_records=10, model="judge-model")

    assert "Replies in the log: 10" in summary
    assert "Graded: 2" in summary
    assert "| Answers with every claim supported (score 2) | 1 of 2 (50%) |" in summary
    assert "| Claims supported | 4 of 5 (80%) |" in summary
