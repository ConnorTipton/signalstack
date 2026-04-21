"""Unit tests for the keyword prefilter."""

from app.llm.prefilter import prefilter_article

# ---------------------------------------------------------------------------
# Category matching
# ---------------------------------------------------------------------------


def test_prefilter_matches_earnings_in_title():
    assert prefilter_article("Apple beats earnings estimates", None) == "earnings"


def test_prefilter_matches_guidance_in_body():
    result = prefilter_article("Company Update", "Management raised guidance for full year.")
    assert result == "guidance"


def test_prefilter_matches_analyst_upgrade():
    result = prefilter_article("Goldman Sachs upgrades AAPL", None)
    assert result == "analyst"


def test_prefilter_matches_m_a():
    result = prefilter_article("Microsoft to acquire Activision", None)
    assert result == "m_a"


def test_prefilter_matches_fda():
    result = prefilter_article("FDA approves new drug", None)
    assert result == "fda"


def test_prefilter_matches_litigation():
    result = prefilter_article("Apple hit with class action lawsuit", None)
    assert result == "litigation"


def test_prefilter_matches_product():
    result = prefilter_article("Apple unveils new iPhone model", None)
    assert result == "product"


def test_prefilter_matches_exec_change():
    result = prefilter_article("CEO steps down at Tesla", None)
    assert result == "exec_change"


def test_prefilter_matches_macro():
    result = prefilter_article("Federal Reserve raises interest rate by 25bps", None)
    assert result == "macro"


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


def test_prefilter_case_insensitive_title():
    assert prefilter_article("EARNINGS BEAT THIS QUARTER", None) is not None


def test_prefilter_case_insensitive_body():
    assert prefilter_article("Routine Update", "REVENUE GUIDANCE RAISED") is not None


# ---------------------------------------------------------------------------
# Non-matching
# ---------------------------------------------------------------------------


def test_prefilter_returns_none_for_irrelevant_article():
    result = prefilter_article("Company celebrates anniversary", "A fun party was held.")
    assert result is None


def test_prefilter_returns_none_for_empty_body():
    result = prefilter_article("Company News", None)
    assert result is None


def test_prefilter_returns_none_for_empty_strings():
    result = prefilter_article("", "")
    assert result is None


# ---------------------------------------------------------------------------
# Body extends match coverage
# ---------------------------------------------------------------------------


def test_prefilter_title_alone_no_match_body_has_match():
    # Title has no keyword but body does
    result = prefilter_article("Company Statement", "The acquisition was announced today.")
    assert result == "m_a"


def test_prefilter_checks_both_title_and_body():
    result = prefilter_article("Weather Report", "Revenue for Q3 beat analyst expectations.")
    assert result is not None
