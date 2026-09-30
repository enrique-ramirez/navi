"""`python -m agitha`: build the config from the command line and serve until stopped."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agitha.server import Config, make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agitha", description="The album import page and its API.")
    parser.add_argument("--port", type=int, default=8882, help="0 picks a free port")
    parser.add_argument("--host", default="", help="the address to bind; empty is every interface")
    for name in ("inbox", "jobs", "library", "extras", "static"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--musiclib", required=True, help="the command that runs musiclib")
    args = parser.parse_args(argv)

    config = Config(
        inbox=args.inbox, jobs=args.jobs, library=args.library, extras=args.extras,
        musiclib=args.musiclib, static=args.static, port=args.port, host=args.host,
    )
    server = make_server(config)
    # A bound-to-everything server has no single address to print; 0.0.0.0 is
    # what a caller that asked for port 0 needs to find the port.
    shown = config.host or "0.0.0.0"
    print(f"listening on http://{shown}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
