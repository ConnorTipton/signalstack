"""Keyword prefilter for news articles.

Only articles that match at least one event category are forwarded to the LLM.
This keeps LLM costs low and limits labeling to financially relevant events.

Categories match blueprint §12: earnings, guidance, analyst, M&A, FDA,
litigation, product launch, executive change, macro.
"""

from __future__ import annotations

# Priority-ordered: first match wins as the "primary" category hint.
# The LLM may assign a different event_type after reading the full article.
_CATEGORIES: dict[str, list[str]] = {
    "earnings": [
        "earnings", "revenue", "profit", "loss", "quarterly results",
        "annual results", "beats estimates", "misses estimates", "q1", "q2",
        "q3", "q4", "fiscal year", "net income",
    ],
    "guidance": [
        "guidance", "outlook", "forecast", "raised guidance", "lowered guidance",
        "full-year", "full year", "raised its", "lowered its", "expects to",
    ],
    "analyst": [
        "analyst", "upgrade", "downgrade", "price target", "overweight",
        "underweight", "outperform", "underperform", "buy rating", "sell rating",
        "hold rating", "initiated coverage", "reiterated",
    ],
    "m_a": [
        "merger", "acquisition", "acquire", "acquired", "takeover", "buyout",
        "deal", "merger agreement", "definitive agreement", "strategic combination",
    ],
    "fda": [
        "fda", "food and drug administration", "approval", "approved",
        "clinical trial", "phase 3", "phase 2", "phase 1", "drug",
        "medical device", "regulatory clearance", "nda", "bla",
    ],
    "litigation": [
        "lawsuit", "litigation", "sued", "settlement", "fine", "penalty",
        "investigation", "regulatory action", "class action", "judgment",
        "injunction", "subpoena",
    ],
    "product": [
        "launch", "unveil", "new product", "new model", "new version",
        "announced", "introduces", "releases", "shipping",
    ],
    "exec_change": [
        "ceo", "cfo", "coo", "cto", "chief executive", "chief financial",
        "chief operating", "appointed", "resigned", "steps down", "named as",
        "new president", "leadership",
    ],
    "macro": [
        "federal reserve", "fed ", "interest rate", "inflation", "gdp",
        "recession", "tariff", "trade war", "monetary policy", "rate hike",
        "rate cut", "economic growth",
    ],
}


def prefilter_article(title: str, body: str | None) -> str | None:
    """Return the first matched category name, or None if no category matches.

    Matching is case-insensitive substring search across title + body. The
    returned category is a hint for logging/debugging; the LLM assigns the
    definitive event_type.
    """
    text = f"{title} {body or ''}".lower()
    for category, keywords in _CATEGORIES.items():
        if any(kw in text for kw in keywords):
            return category
    return None
