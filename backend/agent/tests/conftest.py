import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("LLM_FALLBACK", "mock")

_candidate_samples = ROOT.parent / "samples"
if not _candidate_samples.exists():
    _candidate_samples = ROOT.parent.parent / "samples"
SAMPLES = _candidate_samples


@pytest.fixture(scope="session")
def samples() -> Path:
    if not (SAMPLES / "redteam_hidden_text.pdf").exists():
        from datagen import demo_docs

        demo_docs.main()
    return SAMPLES
