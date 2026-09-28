"""Budget holds and resume, with fake costs."""
import json
import random

import pytest

import pilot as P


def test_recorded_spend_never_passes_cap():
    rng = random.Random(3)
    for _ in range(200):
        cap = rng.uniform(0.5, 5)
        max_cost = {"m": rng.uniform(0.01, 0.2)}
        b = P.Budget(cap, 0.0, max_cost)
        while True:
            hold = b.reserve("m")
            if hold is None:
                break
            # A real episode can cost up to its hold (1.5x the worst seen so far).
            b.settle("m", hold, rng.uniform(0, hold))
            assert b.spent <= cap + 1e-12


def test_unreadable_cost_is_charged_at_its_hold():
    b = P.Budget(10, 1.0, {"m": 0.2})
    hold = b.reserve("m")
    b.settle("m", hold, None)
    assert b.spent == 1.0 + hold and b.reserved == 0


def test_reservations_block_concurrent_overspend():
    b = P.Budget(1.0, 0.0, {"m": 0.3})
    holds = [b.reserve("m") for _ in range(4)]
    assert holds[:2] == pytest.approx([0.45, 0.45]) and holds[2:] == [None, None]


def _rec(rep, **kw):
    cell = {"model": "grok-4.7", "scenario": "late_claims", "wording": "silent", "size": "high"}
    rec = {**cell, "id": f"grok-4.7|late_claims|silent|high|{rep}", "error": None,
           "fingerprint": P.cell_fingerprint(*cell.values())}
    return {**rec, **kw}


def test_resume_skips_done_and_retries_errored_or_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "OUT", tmp_path)
    recs = [
        _rec(0),
        _rec(1, error="HTTP 500"),
        _rec(2, fingerprint="0" * 64),  # its prompt has changed since it ran: rerun
    ]
    tmp_path.joinpath("results.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    assert set(P.load_done()) == {"grok-4.7|late_claims|silent|high|0"}


def test_records_without_fingerprint_match_through_cell_history():
    rec = _rec(0, design_hash=P.current_design_hash())
    del rec["fingerprint"]
    assert P.is_current(rec)
    assert not P.is_current({**rec, "design_hash": "f" * 64})


def test_planned_ids_are_stable_and_rep_major():
    eps = P.planned(1, 2, ["claude-opus-5.5"])
    assert eps[0]["id"] == "claude-opus-5.5|price_coordination|silent|high|0"
    reps = [e["rep"] for e in eps]
    assert reps == sorted(reps)
    assert len(eps) == 2 * len(P.SCENARIOS) * len(P.STAGE_CELLS[1])
