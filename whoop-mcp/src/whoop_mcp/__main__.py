"""CLI: `whoop-mcp auth` to connect WHOOP, `whoop-mcp serve` to run the MCP server."""

from __future__ import annotations

import sys

from .auth import AuthError, TokenStore, run_auth_flow
from .config import load_settings


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "auth":
        settings = load_settings()
        try:
            run_auth_flow(settings, TokenStore(settings.token_file))
        except AuthError as e:
            sys.exit(f"Erro: {e}")
    elif cmd == "serve":
        from .server import run

        run()
    else:
        sys.exit("Uso: whoop-mcp [auth|serve]")


if __name__ == "__main__":
    main()
