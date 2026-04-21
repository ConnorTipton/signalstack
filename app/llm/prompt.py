"""LLM prompt builder and response parser for news article classification.

Prompt format asks the model to return a single JSON object. The parser
handles malformed responses by regex-extracting the first JSON block, and
falls back to an empty dict (all fields stored as NULL) so the raw
response_text is always preserved for replay.
"""

from __future__ import annotations

import json
import re

_BODY_MAX_CHARS = 2000  # truncate long bodies to keep within model context

_PROMPT_TEMPLATE = """\
You are a financial news classifier. Analyze the article below and respond \
with ONLY a valid JSON object — no explanation, no markdown, no extra text.

Required fields:
  event_type  : one of "earnings", "guidance", "analyst", "m_a", "fda", \
"litigation", "product", "exec_change", "macro", or null if none apply
  polarity    : "positive", "negative", or "neutral" (from a stock price \
perspective)
  importance  : float 0.0–1.0 (how market-moving this event is likely to be)
  confidence  : float 0.0–1.0 (your confidence in this classification)
  one_sentence_summary : one sentence summarising the key market-relevant fact

Article:
Title: {title}
Body: {body}

JSON:"""


def build_prompt(title: str, body: str | None) -> str:
    """Return the classification prompt for the given article."""
    truncated_body = (body or "")[:_BODY_MAX_CHARS]
    return _PROMPT_TEMPLATE.format(title=title, body=truncated_body)


def parse_response(response_text: str) -> dict:
    """Extract a classification dict from the LLM response text.

    Tries strict JSON parse first; on failure attempts to regex-extract the
    first JSON object from the response. Returns {} if both attempts fail so
    the caller can store all fields as NULL without crashing.
    """
    text = response_text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return _clamp_floats(result)
    except json.JSONDecodeError:
        pass

    # Regex fallback: grab the first {...} block (handles model preamble)
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return _clamp_floats(result)
        except json.JSONDecodeError:
            pass

    return {}


def _clamp_floats(d: dict) -> dict:
    """Clamp importance and confidence to [0.0, 1.0] in-place; return d."""
    for key in ("importance", "confidence"):
        val = d.get(key)
        if val is not None:
            try:
                d[key] = max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                d[key] = None
    return d
