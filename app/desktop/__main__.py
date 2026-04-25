"""Entry point: `uv run python -m app.desktop`."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.desktop.instance_lock import InstanceLockError, acquire_lock
from app.desktop.window import run

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    # __file__ -> app/desktop/__main__.py; parents[2] -> repo root
    return Path(__file__).resolve().parents[2]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    lock_path = Path.home() / ".signalstack" / "desktop.lock"
    try:
        with acquire_lock(lock_path):
            run(repo_root=_repo_root())
    except InstanceLockError as exc:
        print(f"SignalStack: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"SignalStack: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
