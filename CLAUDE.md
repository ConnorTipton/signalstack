# SignalStack V1 — Project Instructions for Claude Code

## Source of truth
`signalstack_v1_budget_blueprint_v1_1.txt` in this repo is the authoritative spec. When in doubt, re-read it. If a new decision is made that overrides a blueprint section, note it here explicitly rather than letting drift happen silently.

## Architecture summary
Three runtime roles inside a single repo:
1. **Ingestion workers** — `app/ingest_market/`, `app/ingest_news/`, plus provider adapters in `app/providers/{tradier,alpaca,official_feeds,marketaux}/`. They store raw payloads first, then normalize.
2. **Signal engine** — `app/signals/` (news, price, options detectors + scoring), feeding `app/contracts/` (contract selector) and `app/alerts/` (Telegram) and optionally `app/execution/` (Alpaca paper).
3. **Review/API service** — `app/api/` FastAPI app. Read-only. No frontend.

Detector logic consumes normalized events only, never provider-specific payloads. All provider routing lives in adapters or `app/providers/router.py`.

## Build / test / run commands
- Install deps: `uv sync --extra dev`
- Start DB: `docker compose up -d postgres`
- Run API: `uv run uvicorn app.main:app --reload`
- Tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Apply migrations: `uv run alembic upgrade head` (Phase 2+)

## Folder ownership rules
- `app/providers/<name>/` — provider-specific clients and adapters. No detector logic here.
- `app/ingest_*` — long-lived workers. Write raw first, then normalize.
- `app/signals/` — rule-based detectors that read normalized tables and emit `detected_events`.
- `app/contracts/` — option chain filtering and contract selection.
- `app/alerts/` — formatting and delivery. No scoring logic.
- `app/execution/` — paper order routing + position management. Limit-only, one contract. Exit thresholds: invalidation=0.5×entry, target1=2×entry, target2=3×entry (informational).
- `app/replay/` — reads raw event tables and replays them through the same pipeline. Read-only; no writes.
- `app/api/v1/` — FastAPI review endpoints (alerts, health, positions, providers, performance, replay). Read-only. No frontend.
- `app/llm/` — Anthropic client, prefilter, and prompt builder. LLM provider is Anthropic (cloud). No Ollama.
- `tests/` — mirrors the `app/` layout where useful.

## Runtime configuration
`RUNTIME_MODE` env var accepts `build` (default) | `core` | `upgrade` — controls which workers are active at startup. Set in `.env` or the environment before running `python -m app.main_workers`.

## Style rules
- Python 3.12. Ruff enforces lint + format.
- `TIMESTAMP WITH TIME ZONE`, UTC everywhere. Convert to ET only in review/presentation.
- Pydantic v2 for validation. Settings via `pydantic-settings` in `app/core/config.py`.
- SQLAlchemy 2.0 style (`mapped_column`, typed `Mapped[...]`).
- Type hints are mandatory on public functions.
- No implicit network calls in module-level code. Keep imports cheap.

## Hard project rules (from blueprint)
- **Liquidity first.** Never alert on an illiquid contract. Spread/OI filters live in `app/contracts/selector.py`.
- **Rules first, LLM second.** The LLM labels and summarizes. It does not decide trades.
- **Official news first.** Tier 1 (SEC, issuer IR, exchanges, major wires) always outranks Tier 2 aggregators.
- **Every alert is decision-ready.** It must match the blueprint §16 template exactly.
- **Paper first.** No live execution in V1.
- **Replayability over speed of adding features.** Store raw payloads before normalizing.
- **Graceful degradation.** If a provider is weak, *tighten* thresholds and downgrade confidence, don't pretend.

## What Claude should always do
- Write raw payloads to `raw_*_events` before normalizing. Never skip this.
- Preserve the provider abstraction. Detectors import from `app/providers/base.py`, never from concrete adapters.
- Write tests for signal logic. Detector changes without tests are not done.
- Use `source_tier` and `provider_confidence` in every alert-path decision.
- Record `rejection_reason` on every rejected `signal_candidate`.

## What Claude should never do
- Add a frontend (web, mobile, or terminal UI) unless explicitly asked.
- Enable live trading. Paper only in V1.
- Use X/Twitter sentiment as a primary trigger.
- Introduce a new provider without implementing the existing provider protocol.
- Upgrade to paid data tiers without explicit approval (budget cap ~$100/month, §24).
- Add Ollama or any second LLM client. Anthropic (`app/llm/anthropic_client.py`) is the sole LLM provider.

## Session workflow
Work one sub-milestone at a time per the execution plan in `/Users/connortipton/.claude/plans/`. After each sub-milestone: tests pass → ruff clean → commit → push → review → start a fresh Claude session for the next one.
