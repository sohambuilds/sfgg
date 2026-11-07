import pytest

import phase1_fixtures
from phase1 import stimuli


@pytest.fixture
def fixtures(monkeypatch):
    """Install the synthetic scenarios as the Phase 1 registry for one test."""
    monkeypatch.setattr(stimuli, "SCENARIOS", dict(phase1_fixtures.FIXTURES))
    return phase1_fixtures.FIXTURES
