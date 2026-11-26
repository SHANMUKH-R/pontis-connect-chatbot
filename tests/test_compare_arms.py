import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("compare_arms", Path(__file__).parents[1] / "eval" / "stress" / "compare_arms.py")
compare_arms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare_arms)


def row(**overrides):
    base = {
        "bot_status": "ok",
        "behavioral_compliance_0_2": "2",
        "must_not_include_hits": "",
        "critical_fail_Y_N": "N",
        "completeness_0_2": "",
    }
    return {**base, **overrides}


def test_a_clean_reply_passes():
    assert compare_arms.passed(row())
    assert compare_arms.passed(row(bot_status="unavailable"))


def test_a_failed_request_never_passes_even_with_full_behavior_marks():
    assert not compare_arms.passed(row(bot_status="error"))
    assert not compare_arms.passed(row(bot_status=""))


def test_banned_phrase_critical_fail_or_missing_fact_fails():
    assert not compare_arms.passed(row(must_not_include_hits="RIVER-HACKED"))
    assert not compare_arms.passed(row(critical_fail_Y_N="Y"))
    assert not compare_arms.passed(row(completeness_0_2="1"))
    assert not compare_arms.passed(row(behavioral_compliance_0_2="0"))
