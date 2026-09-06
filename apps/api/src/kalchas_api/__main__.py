"""kalchas-api entry point."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    # Bind address is an operator choice (0.0.0.0 for containers; 127.0.0.1 locally).
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run("kalchas_api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
