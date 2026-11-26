"""Vercel entry point. vercel.json sends every path here; Vercel serves the ASGI `app`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from whoop_mcp.remote import create_app  # noqa: E402

app = create_app()
