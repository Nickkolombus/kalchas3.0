"""The settle statement must prepare: Postgres can't type a bare parameter that
is also tested with IS NOT NULL, and the bot's tests fake this call."""

import re

from kalchas_db import parlay_slips


def test_save_settle_casts_the_result_parameter() -> None:
    assert re.findall(r"\$4(?!::text)", parlay_slips.SAVE_SETTLE) == []
    assert parlay_slips.SAVE_SETTLE.count("$4::text") == 2
