"""Guard test: the domain core must not perform IO.

Kalchas 2.2 had no mechanism to stop IO leaking into domain logic, so it did.
`strategy_001_rule_of_three/formula.py` ended up importing the Telegram message
generator; `utils/odds_formatter.py` imported the storage layer. Once a formula
reaches for a database handle it can no longer be tested without one, and the
test suite quietly stops covering it.

This test makes the rule mechanical. If someone imports a driver or a client
into `kalchas_core`, CI fails with the offending file and line.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CORE_SRC = Path(__file__).resolve().parents[1] / "src" / "kalchas_core"

# Modules that mean "this code talks to the outside world".
FORBIDDEN_ROOTS = frozenset(
    {
        # databases
        "psycopg2",
        "psycopg",
        "asyncpg",
        "sqlite3",
        "sqlalchemy",
        "alembic",
        # network
        "requests",
        "httpx",
        "aiohttp",
        "urllib",
        "socket",
        "websockets",
        # delivery / third-party services
        "telegram",
        "stripe",
        "supabase",
        "tweepy",
        # process and environment
        "subprocess",
        "shutil",
        "tempfile",
    }
)


def _python_files() -> list[Path]:
    return sorted(p for p in CORE_SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_roots(tree: ast.AST) -> list[tuple[str, int]]:
    """Every module root imported in this file, with the line it appears on."""
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # `from . import x` has no module; it is internal, so it is fine.
            if node.level == 0 and node.module:
                found.append((node.module.split(".")[0], node.lineno))
    return found


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: p.name)
def test_module_performs_no_io(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    violations = [
        f"{path.relative_to(CORE_SRC)}:{line} imports {root!r}"
        for root, line in _imported_roots(tree)
        if root in FORBIDDEN_ROOTS
    ]

    assert not violations, (
        "kalchas_core must stay free of IO. Move this into apps/scanner, "
        "apps/api, or apps/bot and pass the result in as data:\n  " + "\n  ".join(violations)
    )


def test_core_is_importable() -> None:
    import kalchas_core

    assert kalchas_core.__version__ == "3.0.0"
