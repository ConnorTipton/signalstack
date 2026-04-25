# SignalStack Desktop App — Design Spec

**Date:** 2026-04-24
**Status:** Approved by user, ready for implementation planning
**Scope:** A single-window desktop app (macOS) that wraps the existing SignalStack dashboard, controls the workers/API as subprocesses, and exposes a sensitivity setting that gates which alert grades fire.

---

## 1. Goal

Replace the current multi-step manual workflow:

1. Open Docker Desktop manually
2. Run `uv run python -m app.main_workers` in a terminal
3. Run `uv run uvicorn app.main:app --reload` in another terminal
4. Open `http://localhost:8000` in a browser

…with a single desktop app that:

- Opens with one command (`uv run python -m app.desktop`)
- Embeds the existing dashboard ([web/SignalStack.html](../../../web/SignalStack.html)) so the user sees all the same tabs they see in the browser today (Overview, Alerts, Performance, Providers, Replay)
- Adds a **Control** tab with a Start/Stop button that launches Docker Desktop, brings up Postgres, and starts the workers and API
- Adds a **Settings** tab with a High/Medium/Low sensitivity selector
- Always reflects the latest code in the repo — no rebuild or reinstall needed when files change

## 2. Non-goals

- Live trading toggle (V1 stays paper-only per blueprint)
- Bundling into a clickable `.app` (skip `briefcase` / `py2app`; user launches via `uv run`)
- Cross-platform support — macOS only
- Multiple sensitivity profiles, scheduling, or any setting beyond sensitivity
- Auto-installing Docker Desktop (we detect missing install but do not download it)
- Automated UI tests for PyWebView GUI

## 3. Architecture summary

**Tech stack:** PyWebView (Python window with embedded webview). Selected over Tauri / Electron because the project is already Python, the existing dashboard is a self-contained HTML file with no build step, and subprocess management is trivial in Python. No new languages introduced.

**Process model:**

```
SignalStack desktop app (PyWebView, Python)
├── Embeds web/SignalStack.html (full existing dashboard)
├── Exposes pywebview js_api: start_system, stop_system,
│   get_status, get_recent_logs, get_sensitivity, set_sensitivity
└── Manages two subprocesses:
    ├── uvicorn app.main:app   (port 8000)
    └── python -m app.main_workers
```

**Code lives in:** `app/desktop/` (new module).

## 4. File layout

### New files

| File | Purpose | Approx. size |
|---|---|---|
| `app/desktop/__main__.py` | Entry point so `uv run python -m app.desktop` launches the window | ~20 lines |
| `app/desktop/window.py` | Creates the PyWebView window, points at `web/SignalStack.html`, registers js_api | ~40 lines |
| `app/desktop/controller.py` | Subprocess lifecycle: start/stop workers and API, manage Docker readiness, ring buffer for logs | ~120 lines |
| `app/desktop/js_api.py` | Methods exposed to webview JS (start_system, stop_system, get_status, get_recent_logs, get_sensitivity, set_sensitivity) | ~60 lines |
| `app/desktop/state.py` | Atomic read/write of `~/.signalstack/desktop_state.json` | ~40 lines |
| `web/signalstack/Control.jsx` | Control tab React component | ~150 lines |
| `web/signalstack/Settings.jsx` | Settings tab React component | ~80 lines |
| `tests/desktop/test_state.py` | Unit tests for state file read/write | ~60 lines |
| `tests/desktop/test_controller.py` | Unit tests for controller subprocess lifecycle (with fakes) | ~100 lines |
| `tests/alerts/test_sensitivity_gate.py` | Integration tests for sensitivity gating in alert worker | ~120 lines |

### Modified files

| File | Change |
|---|---|
| [`pyproject.toml`](../../../pyproject.toml) | Add `pywebview` to dependencies |
| [`app/core/config.py`](../../../app/core/config.py) | Add `sensitivity_mode: Literal["high", "medium", "low"]` setting (sourced from state file via helper, with `medium` default) |
| [`app/alerts/worker.py`](../../../app/alerts/worker.py) | Add sensitivity gate: filter candidates whose grade is not in the allowed set for the current mode; record `rejection_reason = "sensitivity_gate:{mode}:grade_{grade}"` for filtered ones |
| [`web/SignalStack.html`](../../../web/SignalStack.html) | Wire in Control and Settings sections; load Control.jsx and Settings.jsx |
| [`web/signalstack/Sidebar.jsx`](../../../web/signalstack/Sidebar.jsx) | Add "Control" and "Settings" sidebar entries |

### State file location

`~/.signalstack/desktop_state.json` — outside the repo so it survives moves/re-clones, isolated from version control, and unique to the user.

```json
{ "sensitivity_mode": "medium" }
```

## 5. UI design

### Window

A single PyWebView window, ~1200×800px, titled **"SignalStack"**. Loads `web/SignalStack.html` directly. The dashboard's existing API base (`http://localhost:8000` per [api.js:4](../../../web/signalstack/api.js#L4)) continues to work unchanged — the embedded page calls localhost just like the browser version does.

### Sidebar (existing, with two additions)

1. Overview *(existing)*
2. Alerts *(existing)*
3. Performance *(existing)*
4. Providers *(existing)*
5. Replay *(existing)*
6. **Control** *(new)*
7. **Settings** *(new)*

The user can navigate freely between all seven sections at any time. When the system is stopped, sections 1–5 will show empty/fallback states from their existing fetch hooks (already handled gracefully in [api.js](../../../web/signalstack/api.js)).

### Style requirement (non-negotiable)

All new components MUST reuse styles and primitives from [`web/signalstack/Shared.jsx`](../../../web/signalstack/Shared.jsx) and match the visual language of existing tabs (Providers, Performance). No new fonts, colors, or component patterns. The Control and Settings tabs should look like a natural extension of the existing dashboard, not a visually distinct add-on.

### Control tab

Layout (matched to existing card/section style):

- **System Status** card with four status rows: Docker, Postgres, Workers, API. Each row has a colored dot and a status label.
  - Green dot = running
  - Red dot = stopped
  - Yellow dot + spinner = transitioning (starting or stopping)
- **Action button** below the status card. Reads "▶ Start System" (green) when stopped, "■ Stop System" (red) when running. Disabled during transitions.
- **Metadata row** showing: last started time, current sensitivity mode (read-only here — set via Settings tab).
- **Recent log output** card showing the last 50 lines of combined worker + API stdout/stderr. Auto-refreshes every 2 seconds.
- **Optional services notice** (yellow info note when applicable): "Optional services unavailable: Marketaux, LLM labeling" — surfaces graceful-degradation state from credential checks.

### Settings tab

Layout:

- **Sensitivity** card with three radio buttons:
  - High — A-grade alerts only (most selective)
  - Medium — A and B grade alerts (default)
  - Low — A, B, and C grade alerts (most permissive)
- Caption beneath: "Changes apply immediately — no restart needed."
- Confirmation toast on successful change. On failure (rare), red toast with reason and the radio reverts.

## 6. Sensitivity behavior

### Core principle

Sensitivity is **only an alert-time gate**. Scoring math is untouched. Candidates are still computed and stored with their normal grades per [app/signals/scoring.py](../../../app/signals/scoring.py) (A ≥ 82, B ≥ 72, C ≥ 65). Sensitivity decides only which grades trigger an actual alert.

### Mode → allowed grades

| Mode | Allowed grades |
|---|---|
| High | `{"A"}` |
| Medium *(default)* | `{"A", "B"}` |
| Low | `{"A", "B", "C"}` |

D-grade candidates never alert in any mode (already enforced by existing cap logic in [scoring.py:192-212](../../../app/signals/scoring.py#L192-L212)).

### Where the gate lives

In [`app/alerts/worker.py`](../../../app/alerts/worker.py). The worker's existing candidate-fetch loop adds one filter step:

```python
allowed = sensitivity_mode_to_grades(read_sensitivity())
for candidate in candidates:
    if candidate.grade not in allowed:
        candidate.rejection_reason = f"sensitivity_gate:{mode}:grade_{candidate.grade}"
        # commit and skip — do not emit an Alert for this candidate
        continue
    # ... existing emit-alert path ...
```

This satisfies the [CLAUDE.md](../../../CLAUDE.md) project rule: *"Record `rejection_reason` on every rejected `signal_candidate`."*

### Live reload (no restart needed)

The alert worker calls `read_sensitivity()` once at the top of each loop iteration. Cost: a single small file read (~microseconds). A radio change in the UI takes effect on the worker's next loop tick — typically within a few seconds.

The state file is written atomically: write to `<path>.tmp`, then `os.rename` to the final path. The worker is guaranteed to never see a half-written file.

### Grade fidelity (non-functional requirement)

The `grade` field on every Alert reflects the candidate's actual computed grade per [app/signals/scoring.py](../../../app/signals/scoring.py). The sensitivity mode is *only* an admission filter — it never modifies, hides, or rewrites the grade. Telegram messages ([formatter.py:101](../../../app/alerts/formatter.py#L101)) and dashboard views ([Alerts.jsx](../../../web/signalstack/Alerts.jsx), [AlertDetail.jsx](../../../web/signalstack/AlertDetail.jsx)) must show the true grade regardless of which sensitivity mode was active when the alert fired. This is verified by an integration test (see Testing section).

### Default behavior

If `~/.signalstack/desktop_state.json` does not exist, sensitivity defaults to `medium`. So workers running outside the desktop app (e.g., directly from terminal) get the blueprint default behavior — backward-compatible.

If the file exists but contains an invalid mode value, `read_sensitivity()` logs a warning and falls back to `medium`. No crash.

## 7. Start / Stop / Status

### Start sequence

1. **Check Docker daemon.** Run `docker info` with a 1-second timeout.
2. **If Docker is not running:**
   - Detect whether Docker Desktop is installed (test `/Applications/Docker.app` existence).
   - If not installed: show "Docker Desktop is not installed" with an install link, abort start.
   - If installed: run `open -a Docker` to launch Docker Desktop. Update Docker status to "Starting…" (yellow, spinner).
   - Poll `docker info` every 2 seconds, up to **60 seconds total**. On success, proceed. On timeout, show "Docker Desktop didn't start in time. Open it manually and try again." Leave the Docker Desktop GUI running for the user to retry.
3. **Ensure Postgres.** Run `docker compose up -d postgres` (idempotent). Update Postgres status to "Starting…".
4. **Wait for Postgres ready.** Poll `pg_isready` (or a quick connect attempt) for up to 10 seconds. On success, Postgres status → green.
5. **Spawn API.** `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` as a subprocess, with `cwd` set to the repo root (computed from `app/desktop/__main__.py`'s `__file__`). Pipe stdout/stderr to a thread that pushes lines into a 200-line ring buffer. API status → green once `proc.poll() is None` after a 1-second settle.
6. **Spawn workers.** `uv run python -m app.main_workers` as a subprocess, same `cwd` (repo root) and logging treatment. Workers status → green once `proc.poll() is None` after a 1-second settle.

If any step fails, show the error in the log tail and leave the system in a partially-stopped state. Subprocesses that did start cleanly stay running — we don't tear down on failure of a later step, because that would mask the original error.

**Total Start time:** ~3–5 seconds when Docker is already running, ~30–60 seconds on cold boot.

### Stop sequence

1. Send SIGTERM to the workers subprocess. Wait up to 10 seconds for clean exit.
2. Send SIGTERM to the API subprocess. Wait up to 10 seconds.
3. If either doesn't exit in time, send SIGKILL and log a warning to the ring buffer.
4. Update status dots to red.
5. **Postgres keeps running.** (Per user decision: pause/resume during a session is fast; full clean shutdown is the user's responsibility via Docker Desktop.)

### Window close behavior

The PyWebView window's `closing` event triggers the same Stop flow before the app exits. This prevents orphaned worker/API processes from running in the background after the window is closed. Postgres is left running, consistent with the explicit Stop button.

### Status detection

The Python controller tracks two `subprocess.Popen` handles plus polled state for Docker and Postgres:

| Component | Detection method |
|---|---|
| Docker | `docker info` exit code (1s timeout) |
| Postgres | `docker compose ps postgres --format json` parsed for state == "running" |
| API | `proc.poll() is None` for the uvicorn subprocess |
| Workers | `proc.poll() is None` for the workers subprocess |

The `js_api.get_status()` endpoint returns all four states. The Control tab polls every 2 seconds via `setInterval` and updates the status dots.

### Log tail

Stdout/stderr from both subprocesses pipe through a Python thread that pushes lines into a 200-line `collections.deque`. The Control tab fetches the last 50 lines every 2 seconds via `js_api.get_recent_logs()`. No disk I/O.

### Single-instance lock

A file-based lock at `~/.signalstack/desktop.lock` (containing PID) prevents two SignalStack windows from running simultaneously. On launch:

- If the lock file exists and the PID is alive: show "SignalStack is already running" and exit immediately.
- Otherwise: create the lock file, register cleanup on exit (atexit + signal handlers).

This avoids the chaos of two desktop apps both trying to spawn `uvicorn` on port 8000.

## 8. Error handling — surfaced UI states

The Control tab is the single place errors surface. No silent failures.

| Failure | User experience |
|---|---|
| Docker Desktop not installed | Red banner: "Docker Desktop is not installed. [link]". Start button stays enabled (in case user installs and clicks again). |
| Docker daemon doesn't come up in 60s | Red banner: "Docker Desktop didn't start in time. Open it manually and try again." Start aborts; status reflects whatever did succeed. |
| Postgres won't start in 10s | Red banner: "Postgres failed to start. Check Docker logs." Start aborts; Postgres status returns to red. |
| Port 8000 already in use | Red banner: "Port 8000 is in use — another API may already be running." Workers don't get started. |
| Worker crashes after start succeeded | Status dot flips red on next 2-second poll. Last 50 lines of log tail show the traceback. Start button re-enables. |
| Telegram or LLM credentials missing | Yellow info note in Control tab: "Optional services unavailable: Marketaux, LLM labeling". Not a hard failure — workers run normally, per [CLAUDE.md](../../../CLAUDE.md) graceful-degradation rule. |
| Sensitivity write fails (disk full, permissions) | Settings tab shows red toast and reverts the radio to the previous value. Atomic rename ensures the state file is never half-written. |

## 9. Edge cases

- **Multiple desktop windows:** prevented by single-instance lock (see §7).
- **Laptop sleep:** subprocesses survive sleep on macOS. Status polling resumes on wake. No special handling.
- **User edits the JSON state file by hand to an invalid value:** `read_sensitivity()` validates against `{"high", "medium", "low"}` and falls back to `medium`, logging a warning.
- **Repo path changes (user moves the folder):** state file is in `~/.signalstack/`, survives. Subprocess cwd follows the desktop app's launch location.
- **Running desktop app + legacy terminal workflow simultaneously:** Postgres is fine (shared). API/workers will collide on port 8000 / DB constraints — the desktop app's port-8000 check catches the API collision; a parallel worker process will likely fail noisily on DB constraints, which is the right outcome (we don't try to detect external workers).

## 10. Testing strategy

| Layer | Test type | What's covered |
|---|---|---|
| `state.py` (read/write sensitivity) | Unit | Missing file → default; malformed JSON → default + warning; valid modes → correct return; invalid mode → default + warning; atomic write under interruption (verify no partial file) |
| `sensitivity_mode_to_grades` mapping | Unit (pure) | Three modes → correct grade sets |
| Alert worker sensitivity gate | Integration (uses `_test` DB) | Seed candidates with grades A/B/C/D, run worker once per mode, assert: (1) only allowed grades produce Alerts, (2) rejected candidates have correct `rejection_reason`, (3) emitted Alerts carry the candidate's true grade (grade fidelity) |
| Controller subprocess lifecycle | Unit (with fake subprocess) | Start spawns, Stop terminates within timeout, kill on timeout, status reflects `poll()` correctly, ring buffer captures stdout/stderr lines |
| Desktop window / GUI | **Manual smoke test** | After build: launch app, click Start, verify dots turn green, click Alerts tab and verify alerts load, change sensitivity in Settings, verify next worker iteration honors it, click Stop, verify clean shutdown, close window, verify subprocesses are gone (`pgrep -f main_workers` returns empty) |

Manual smoke test definition: a person opens the app and clicks through the basic flow once after each meaningful change to confirm nothing is obviously broken. Not automated. PyWebView GUIs are not worth automating for a personal-use tool.

## 11. Build, run, and update model

### How the user runs it

```bash
uv run python -m app.desktop
```

Single command. No build step. No bundle.

### How updates work

The desktop app is a thin Python launcher reading files from the repo. To get changes:

```bash
git pull        # or just edit files
```

…and click Start again. There is no app to "redownload" — the app *is* the repo. This was a key user requirement: "If I made changes to the file, would I have to redownload the app or could I do something like update it everytime?" Answer: never redownload; always live.

### Future: bundling to .app

Out of scope for V1. If the user later wants a clickable `.app` icon, `briefcase` can wrap the existing module without code changes. Adding this is purely cosmetic and can be done later without affecting the architecture.

## 12. Adherence to project rules

This design respects all hard rules from [CLAUDE.md](../../../CLAUDE.md):

- ✅ **No live trading.** Sensitivity is alert-side only; nothing in the desktop app touches execution.
- ✅ **No new providers.** No data integrations changed.
- ✅ **No second LLM client.** No LLM changes at all.
- ✅ **Detector logic untouched.** Scoring math in [app/signals/scoring.py](../../../app/signals/scoring.py) is not modified.
- ✅ **`rejection_reason` recorded** on every gate-rejected candidate.
- ✅ **No frontend addition.** The user explicitly asked for this app, and CLAUDE.md says "Add a frontend… unless explicitly asked."
- ✅ **Tests for signal logic.** The sensitivity gate is signal logic; it gets integration tests.
- ✅ **Match existing patterns.** Reuses existing `Shared.jsx` styling, `subprocess` patterns from elsewhere in the codebase, and adds no new abstractions.

## 13. Implementation considerations to address in the plan

These are not open design questions — they are technical wrinkles the implementer needs to handle. Calling them out so they don't get discovered late.

- **CORS / file:// origin.** The PyWebView window loads `web/SignalStack.html` from the local filesystem. The page's JS calls `http://localhost:8000`. The existing CORS middleware was added for `localhost:3000` (dev server). The plan must extend the CORS allow-list to cover the webview origin (likely `null` or `file://`) — or, alternatively, configure PyWebView to serve the HTML via its built-in local HTTP server (which makes the origin `http://localhost:<random_port>` and avoids the file:// issue entirely). Decision deferred to plan; PyWebView's `http_server=True` is likely the simpler path.
- **Subprocess working directory.** Both subprocesses must run with `cwd` set to the repo root so that `uv run`, `docker compose`, and relative file references behave correctly. The desktop module computes the repo root from its own `__file__` location.
- **Pipe buffering.** The log-tail thread reads stdout/stderr line-by-line. Both `uvicorn` and `python -m app.main_workers` must run with line-buffered output (pass `bufsize=1` and `text=True` to `Popen`, and set `PYTHONUNBUFFERED=1` in the subprocess env) — otherwise log lines won't appear in real time.

## 14. Open questions

None at time of writing. All design decisions made during brainstorming and confirmed by the user.

---

**Spec complete. Next step: implementation plan.**
