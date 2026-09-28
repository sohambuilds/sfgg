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


def test_resume_skips_done_and_retries_errored(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "OUT", tmp_path)
    h = P.current_design_hash()
    recs = [
        {"id": "a", "error": None, "design_hash": h},
        {"id": "b", "error": "HTTP 500", "design_hash": h},
        {"id": "c", "error": None, "design_hash": "0" * 64},  # another design: not done here
    ]
    tmp_path.joinpath("results.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
    assert set(P.load_done()) == {"a"}


def test_planned_ids_are_stable_and_rep_major():
    eps = P.planned(1, 2, ["claude-opus-5.5"])
    assert eps[0]["id"] == "claude-opus-5.5|price_coordination|silent|high|0"
    reps = [e["rep"] for e in eps]
    assert reps == sorted(reps)
    assert len(eps) == 2 * len(P.SCENARIOS) * len(P.STAGE_CELLS[1])
