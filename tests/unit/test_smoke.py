from pathlib import Path

import ladelaug_avregning

_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def test_version_matches_version_file():
    assert ladelaug_avregning.__version__ == _VERSION_FILE.read_text(encoding="utf-8").strip()
