import pytest

import phase1_fixtures
from phase1 import authority, checks, freeze, prereg, stimuli


@pytest.fixture
def fixtures(monkeypatch):
    """Install the synthetic scenarios as the Phase 1 registry for one test."""
    monkeypatch.setattr(stimuli, "SCENARIOS", dict(phase1_fixtures.FIXTURES))
    return phase1_fixtures.FIXTURES


@pytest.fixture
def frozen_env(tmp_path, monkeypatch, fixtures):
    """Everything `freeze` needs to succeed, pointed at a temp directory: decided prereg values, signed-off
    authority wording, a prereg document, and the fixture scenarios allowed past the provenance check."""
    prereg_md = tmp_path / "PHASE1_PREREG.md"
    prereg_md.write_text("test prereg\n", encoding="utf-8")
    monkeypatch.setattr(freeze, "PREREG_MD", prereg_md)
    monkeypatch.setattr(freeze, "FROZEN_PATH", tmp_path / "FROZEN.json")
    monkeypatch.setattr(freeze, "HISTORY_PATH", tmp_path / "history.jsonl")
    monkeypatch.setattr(authority, "AUTHORITY_FINAL", True)
    for k, v in (("runs_per_cell", 2), ("cross", "trimmed"), ("h5_status", "exploratory"), ("near_zero", 0.05),
                 ("min_effect", 0.2)):
        monkeypatch.setitem(prereg.DECISIONS, k, v)
    real_all = checks.all_problems
    monkeypatch.setattr(checks, "all_problems", lambda allow_fixture=False: real_all(allow_fixture=True))
    return tmp_path
