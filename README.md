# SignalStack V1

Personal options-alert research engine. Monitors a small universe of liquid U.S. large-caps and fires Telegram alerts only when **news catalyst + price confirmation + unusual options activity** align.

See `signalstack_v1_budget_blueprint_v1_1.txt` for the full spec and `CLAUDE.md` for the working agreement.

## Quick start

```bash
# install deps
uv sync --extra dev

# start Postgres (TimescaleDB)
docker compose up -d postgres

# run the API
uv run uvicorn app.main:app --reload

# in another terminal:
curl http://localhost:8000/health
```

## Development

```bash
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

Copy `.env.example` to `.env` and fill in values as you progress through phases.
