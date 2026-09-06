"""Kalchas domain core.

This package holds the parts of Kalchas that decide *what is true about a
match*: the strategy formulas, the outcome engine, K-Score, NPEI, and the
value objects they operate on.

The one rule that keeps this package worth having: **nothing in here performs
IO**. No database handles, no HTTP calls, no Telegram, no filesystem, no clock
reads outside an injected value. Inputs arrive as plain data, results leave as
plain data. That is what makes the formulas testable without a live API key,
and it is why 22 of Kalchas 2.2's 30 test files could move here unchanged.

IO belongs in the surrounding services: `apps/scanner` fetches and persists,
`apps/api` serves, `apps/bot` delivers.
"""

__version__ = "3.0.0"
