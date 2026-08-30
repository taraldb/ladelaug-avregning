from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    # VERSION lives at the repo root, two levels up from this file
    # (src/ladelaug_avregning/__init__.py). In an odd install layout where it
    # is not shipped alongside the package, fall back rather than crash.
    candidate = Path(__file__).resolve().parents[2] / "VERSION"
    try:
        return candidate.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


__version__ = _read_version()
