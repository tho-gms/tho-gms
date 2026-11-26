"""CLI: `auth` connects WHOOP locally, `serve` runs over stdio, `http` runs the remote server."""

from __future__ import annotations

import sys

from .auth import AuthError, run_auth_flow
from .config import load_settings


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "auth":
        settings = load_settings()
        from .server import build_service

        try:
            run_auth_flow(settings, build_service(settings).client.store)
        except AuthError as e:
            sys.exit(f"Erro: {e}")
    elif cmd == "serve":
        from .server import run

        run()
    elif cmd == "http":
        from .remote import run

        run()
    else:
        sys.exit("Uso: whoop-mcp [auth|serve|http]")


if __name__ == "__main__":
    main()
