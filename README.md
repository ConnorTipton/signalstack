# SignalStack V1

Personal options-alert research engine. Monitors a small universe of liquid U.S. large-caps and fires Telegram alerts only when **news catalyst + price confirmation + unusual options activity** align.

See `signalstack_v1_budget_blueprint_v1_1.txt` for the full spec and `CLAUDE.md` for the working agreement.

## Quick start

```bash
# install deps
uv sync --extra dev

# copy env template and fill in values
cp .env.example .env

# start Postgres (TimescaleDB)
docker compose up -d postgres

# apply migrations
uv run alembic upgrade head

# run the review API
uv run uvicorn app.main:app --reload

# in another terminal:
curl http://localhost:8000/health
```

## Running workers

The pipeline (ingestion → detection → alerts → paper execution) runs as async workers, not via the API:

```bash
uv run python -m app.main_workers
```

Workers always started: Edgar, RSS, NewsDetector, PriceDetector, OptionsDetector, ScoringWorker, ContractSelectorWorker, AlertWorker, DailyMetricsWorker.
Conditional on credentials: LabelWorker (needs `CLOUD_LLM_API_KEY`), MarketauxWorker (needs `MARKETAUX_API_TOKEN`), Tradier stream + chain snapshots (needs `TRADIER_API_TOKEN`), Alpaca bars + chain snapshots fallback and ExecutionWorker (need Alpaca keys).

Set `MONITORED_TICKERS` and `RSS_FEEDS` in `.env` to change the universe or feed list without editing code. `RSS_FEEDS` uses semicolon-separated `source|url` or `source|url|ticker` entries.

## Development

```bash
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

Integration tests use `TEST_DATABASE_URL` when set, otherwise they create/use the configured database name with `_test` appended. They refuse to run against the application database.

## Metrics backfill

```bash
uv run python scripts/backfill_daily_metrics.py --start 2026-04-01 --end 2026-04-22
```

See `.env.example` for the full list of env vars and which phase each belongs to.
