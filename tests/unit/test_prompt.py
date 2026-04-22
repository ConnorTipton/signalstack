"""Unit tests for the LLM prompt builder and response parser."""

from app.llm.prompt import build_prompt, parse_response

_TITLE = "Apple Reports Record Q1 Revenue"
_BODY = "Apple Inc. today announced record quarterly revenue of $120 billion."


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


def test_build_prompt_contains_title():
    prompt = build_prompt(_TITLE, _BODY)
    assert _TITLE in prompt


def test_build_prompt_contains_body():
    prompt = build_prompt(_TITLE, _BODY)
    assert "record quarterly revenue" in prompt


def test_build_prompt_handles_none_body():
    prompt = build_prompt(_TITLE, None)
    assert _TITLE in prompt
    assert "Body:" in prompt


def test_build_prompt_truncates_long_body():
    long_body = "x" * 5000
    prompt = build_prompt(_TITLE, long_body)
    # Should not exceed 2000 + some padding for the template text
    assert len(prompt) < 4000


def test_build_prompt_requests_json_output():
    prompt = build_prompt(_TITLE, _BODY)
    assert "JSON" in prompt


def test_build_prompt_lists_required_fields():
    prompt = build_prompt(_TITLE, _BODY)
    for field in ("event_type", "polarity", "importance", "confidence", "one_sentence_summary"):
        assert field in prompt


# ---------------------------------------------------------------------------
# parse_response — valid JSON
# ---------------------------------------------------------------------------

_VALID_JSON = """{
  "event_type": "earnings",
  "polarity": "positive",
  "importance": 0.85,
  "confidence": 0.92,
  "one_sentence_summary": "Apple beat Q1 estimates with record revenue."
}"""


def test_parse_response_extracts_event_type():
    result = parse_response(_VALID_JSON)
    assert result["event_type"] == "earnings"


def test_parse_response_extracts_polarity():
    result = parse_response(_VALID_JSON)
    assert result["polarity"] == "positive"


def test_parse_response_extracts_importance():
    result = parse_response(_VALID_JSON)
    assert result["importance"] == 0.85


def test_parse_response_extracts_confidence():
    result = parse_response(_VALID_JSON)
    assert result["confidence"] == 0.92


def test_parse_response_extracts_summary():
    result = parse_response(_VALID_JSON)
    assert "Apple beat Q1" in result["one_sentence_summary"]


# ---------------------------------------------------------------------------
# parse_response — JSON embedded in preamble text
# ---------------------------------------------------------------------------


def test_parse_response_handles_preamble():
    response = 'Here is the classification:\n{"event_type": "guidance", "polarity": "negative", "importance": 0.6, "confidence": 0.7, "one_sentence_summary": "Guidance cut."}'
    result = parse_response(response)
    assert result.get("event_type") == "guidance"


def test_parse_response_returns_empty_dict_for_garbage():
    result = parse_response("I cannot classify this article.")
    assert result == {}


def test_parse_response_returns_empty_dict_for_empty_string():
    result = parse_response("")
    assert result == {}


# ---------------------------------------------------------------------------
# parse_response — float clamping
# ---------------------------------------------------------------------------


def test_parse_response_clamps_importance_above_1():
    result = parse_response(
        '{"event_type": "earnings", "polarity": "positive", "importance": 1.5, "confidence": 0.9, "one_sentence_summary": "x"}'
    )
    assert result["importance"] == 1.0


def test_parse_response_clamps_confidence_below_0():
    result = parse_response(
        '{"event_type": "earnings", "polarity": "positive", "importance": 0.5, "confidence": -0.1, "one_sentence_summary": "x"}'
    )
    assert result["confidence"] == 0.0


def test_parse_response_handles_null_event_type():
    result = parse_response(
        '{"event_type": null, "polarity": "neutral", "importance": 0.1, "confidence": 0.5, "one_sentence_summary": "No clear event."}'
    )
    assert result["event_type"] is None
