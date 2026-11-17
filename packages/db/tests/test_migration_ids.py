"""Alembic revision ids must fit alembic_version.version_num (VARCHAR(32)).

0038 was first named with 33 characters; Postgres refused the version update on
deploy and rolled the migration back.
"""

from __future__ import annotations

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_REVISION = re.compile(r'^revision: str = "([^"]+)"', re.MULTILINE)


def test_every_revision_id_fits_the_version_column() -> None:
    ids = {
        path.name: match.group(1)
        for path in VERSIONS.glob("*.py")
        if (match := _REVISION.search(path.read_text(encoding="utf-8")))
    }
    assert ids, "no migrations found"
    too_long = {name: rev for name, rev in ids.items() if len(rev) > 32}
    assert too_long == {}
