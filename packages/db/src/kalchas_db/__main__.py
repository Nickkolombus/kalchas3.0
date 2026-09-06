"""CLI: alembic upgrade head."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    # alembic.ini lives at repo root when installed editable from the workspace.
    root = Path(__file__).resolve().parents[4]
    ini = root / "alembic.ini"
    if not ini.exists():
        # Fallback: package-local copy for container layouts that only ship packages/db.
        ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    if not ini.exists():
        raise SystemExit(f"alembic.ini not found (looked under {root})")
    os.chdir(ini.parent)
    from alembic.config import main as alembic_main

    argv = sys.argv[1:] or ["upgrade", "head"]
    alembic_main(argv=["-c", str(ini), *argv])


if __name__ == "__main__":
    main()
