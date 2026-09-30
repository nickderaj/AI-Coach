"""``python -m trainer.api``: serve the API with uvicorn (used by the systemd unit)."""

from __future__ import annotations

import argparse

import uvicorn


def main(argv: list[str] | None = None) -> None:
    """Parse the bind address and hand the app factory to uvicorn."""
    parser = argparse.ArgumentParser(prog="python -m trainer.api", description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    uvicorn.run(
        "trainer.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
