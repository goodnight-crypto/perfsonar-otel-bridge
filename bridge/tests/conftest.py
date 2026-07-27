import json
from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "samples"


@pytest.fixture
def sample():
    """docs/samples/ の実 JSON を名前の前方一致で読み込む。"""

    def _load(prefix: str) -> dict:
        matches = sorted(SAMPLES.glob(f"{prefix}*.json"))
        if not matches:
            raise FileNotFoundError(f"{prefix}* が {SAMPLES} に無い")
        return json.loads(matches[0].read_text())

    return _load
