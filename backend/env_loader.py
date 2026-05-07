"""Load env vars from env.local at process start.

The repo's env.local uses lowercase keys (open_router_key, voyage_api_key);
this loader normalizes them to the canonical uppercase env vars that the
rest of the code reads (OPENROUTER_API_KEY, VOYAGE_API_KEY).

Idempotent: existing os.environ values win, so production secrets set via
Fly.io take precedence over a local file.
"""
from __future__ import annotations

import os
from pathlib import Path

_ALIASES = {
    "open_router_key": "OPENROUTER_API_KEY",
    "openrouter_key": "OPENROUTER_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "voyage_api_key": "VOYAGE_API_KEY",
    "voyage_key": "VOYAGE_API_KEY",
    "google_places_key": "GOOGLE_PLACES_KEY",
    "google_client_id": "GOOGLE_CLIENT_ID",
}


def load_env_local(path: str | Path = "env.local") -> int:
    p = Path(path)
    if not p.exists():
        return 0
    loaded = 0
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        canonical = _ALIASES.get(k.lower(), k.upper())
        if canonical not in os.environ:
            os.environ[canonical] = v
            loaded += 1
    return loaded
