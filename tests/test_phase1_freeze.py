"""The freeze: what blocks it, what changes the hash, and that drift is caught."""
import dataclasses
import json

import pytest

from phase1 import authority, freeze, models, prereg, stimuli


def test_hash_is_stable_and_sensitive_to_everything_that_matters(frozen_env, monkeypatch):
    h = freeze.design_hash()
    assert h == freeze.design_hash() and len(h) == 64
    s = stimuli.SCENARIOS["fixture_stall"]

    def differs(undo):
        assert freeze.design_hash() != h
        undo()
        assert freeze.design_hash() == h

    monkeypatch.setitem(stimuli.SCENARIOS, "fixture_stall", dataclasses.replace(s, documents={**s.documents, "Extra": "x"}))
    differs(lambda: monkeypatch.setitem(stimuli.SCENARIOS, "fixture_stall", s))
    monkeypatch.setitem(prereg.DECISIONS, "runs_per_cell", 3)
    differs(lambda: monkeypatch.setitem(prereg.DECISIONS, "runs_per_cell", 2))
    monkeypatch.setitem(authority.INSISTENCE, 2, "Kindly {act}.")
    differs(lambda: monkeypatch.setitem(authority.INSISTENCE, 2, "Please {act}."))
    freeze.PREREG_MD.write_text("changed\n", encoding="utf-8")
    differs(lambda: freeze.PREREG_MD.write_text("test prereg\n", encoding="utf-8"))
    old = models.SLATE[0]
    monkeypatch.setattr(models, "SLATE", [dataclasses.replace(old, slug="x/y")] + models.SLATE[1:])
    differs(lambda: monkeypatch.setattr(models, "SLATE", [old] + models.SLATE[1:]))


def test_freeze_writes_the_hash_and_an_append_only_history(frozen_env):
    e1 = freeze.freeze("first")
    assert freeze.frozen_hash() == e1["hash"] == freeze.design_hash() and freeze.guard() == e1["hash"]
    prereg.DECISIONS["runs_per_cell"] = 4  # restored by the fixture
    with pytest.raises(SystemExit, match="changed since it was frozen"):
        freeze.guard()
    e2 = freeze.freeze("second")
    lines = [json.loads(l) for l in freeze.HISTORY_PATH.read_text(encoding="utf-8").splitlines()]
    assert [x["note"] for x in lines] == ["first", "second"] and e1["hash"] != e2["hash"]


def test_guard_refuses_when_nothing_is_frozen(frozen_env):
    with pytest.raises(SystemExit, match="not frozen"):
        freeze.guard()


@pytest.mark.parametrize("name,value,expect", [
    ("runs_per_cell", None, "runs_per_cell"), ("cross", None, "cross"), ("h5_status", None, "h5_status"),
    ("near_zero", None, "near_zero"), ("min_effect", None, "min_effect"),
    ("cross", "half", "cross must be"), ("h5_status", "maybe", "h5_status must be")])
def test_freeze_refuses_while_the_prereg_is_open_or_invalid(frozen_env, monkeypatch, name, value, expect):
    monkeypatch.setitem(prereg.DECISIONS, name, value)
    with pytest.raises(SystemExit) as e:
        freeze.freeze()
    assert expect in str(e.value) and not freeze.FROZEN_PATH.exists()


def test_freeze_refuses_unsigned_wording_missing_document_and_bad_scenarios(frozen_env, monkeypatch):
    monkeypatch.setattr(authority, "AUTHORITY_FINAL", False)
    assert any("authority wording" in b for b in freeze.blockers())
    monkeypatch.setattr(authority, "AUTHORITY_FINAL", True)
    freeze.PREREG_MD.unlink()
    assert any("PHASE1_PREREG.md is missing" in b for b in freeze.blockers())
    freeze.PREREG_MD.write_text("x", encoding="utf-8")
    s = stimuli.SCENARIOS["fixture_stall"]
    monkeypatch.setitem(stimuli.SCENARIOS, "fixture_stall", dataclasses.replace(s, provenance="ai-draft"))
    assert any("ai-draft" in b for b in freeze.blockers())


def test_the_real_design_cannot_be_frozen_yet():
    blockers = freeze.blockers()
    assert any("no scenarios yet" in b for b in blockers) and any("undecided" in b for b in blockers)
