"""kalchas-scanner entry point."""

from __future__ import annotations

import logging
import os

from kalchas_football import FootballAPIClient

from kalchas_scanner.loop import Scanner, ScannerConfig


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    class _RedactApiKey(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = record.getMessage()
            if "APIkey=" in msg:
                import re

                record.msg = re.sub(r"APIkey=[^&\s\"]+", "APIkey=***", msg)
                record.args = ()
            return True

    redact = _RedactApiKey()
    for name in ("httpx", "httpcore", "kalchas.scanner", "kalchas.football"):
        logging.getLogger(name).addFilter(redact)

    interval = int(os.environ.get("SCANNER_INTERVAL_SEC", "60"))
    with FootballAPIClient() as client:
        scanner = Scanner(client=client, config=ScannerConfig(interval_sec=interval))
        once = os.environ.get("SCANNER_ONCE", "").lower() in {"1", "true", "yes"}
        if once:
            scanner.run_once()
        else:
            scanner.run_forever()


if __name__ == "__main__":
    main()
