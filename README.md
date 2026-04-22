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

Workers start unconditionally: Edgar, RSS, Marketaux, LabelWorker, TradierWorker, BarAggregator, NewsDetector, PriceDetector, OptionsDetector, AlertWorker.  
Conditional on credentials: ChainSnapshotWorker (needs `TRADIER_API_TOKEN`), ExecutionWorker (needs `ALPACA_API_KEY`).

## Development

```bash
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

See `.env.example` for the full list of env vars and which phase each belongs to.
