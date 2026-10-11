"""Phase 1 analysis on synthetic episodes with planted effects."""
import random

import pytest

from phase1 import analysis, authority


def eps(spec, scenarios=("s1", "s2", "s3", "s4"), runs=10, seed=0):
    """spec: {(model, variant, level): act probability}. Returns episode dicts."""
    rng = random.Random(seed)
    out = []
    for (model, variant, level), p in spec.items():
        for sc in scenarios:
            for i in range(runs):
                acts = rng.random() < p
                out.append({"id": f"{model}|{sc}|{variant}|{level}|{i}", "model": model, "scenario": sc,
                            "variant": variant, "level": level, "legal": variant[0] == "L", "harm": variant[1] == "H",
                            "entitlement": sc in ("s1", "s2"), "outcome": "violation" if acts else
                            ("escalated" if rng.random() < 0.5 else "no_action"), "escalation_kind": "asks"})
    return out


def planted():
    spec = {}
    for lvl in authority.LEVELS:
        spec[("claude-opus-5.5", "IX", lvl)] = 0.0
        spec[("claude-opus-5.5", "LH", lvl)] = [0.0, 0.3, 0.6, 0.9][lvl]
        spec[("claude-opus-5.5", "LX", lvl)] = [0.0, 0.9, 0.9, 0.9][lvl]
        spec[("deepseek-v4-flash", "IX", lvl)] = 1.0
        spec[("deepseek-v4-flash", "LH", lvl)] = 1.0
    return eps(spec)


def test_planted_effects_are_recovered_with_intervals():
    cons = analysis.contrasts(planted(), draws=300)
    c = cons["claude-opus-5.5"]
    assert c["H1 IX permission effect"][0] == 0 and c["H7 IX act rate at level 3"][0] == 0
    p, lo, hi = c["H2 LH permission effect"]
    assert 0.15 < p < 0.45 and lo < p < hi and lo > 0
    assert c["H3 LH minus IX permission effect"][0] == pytest.approx(p)
    assert c["H4 LX minus LH permission effect"][0] > 0.4          # harmless permission effect is larger
    assert c["H6 LH slope per level"][0] == pytest.approx(0.3, abs=0.08)
    d = cons["deepseek-v4-flash"]
    assert d["H1 IX permission effect"][0] == 0 and d["H7 IX act rate at level 3"][0] == 1.0
    assert list(cons) == ["deepseek-v4-flash", "claude-opus-5.5"]   # ordered by size slot


def test_bootstrap_is_deterministic_and_scenario_level():
    data = analysis.build(planted())["claude-opus-5.5"]
    stat = analysis.STATS["H2 LH permission effect"]
    assert analysis.bootstrap(data, stat, draws=200) == analysis.bootstrap(data, stat, draws=200)
    one = {k: v for k, v in data.items() if k == "s1"}
    point, lo, hi = analysis.bootstrap(one, stat, draws=200)
    assert point is not None and lo is None and hi is None  # one scenario: no interval claimed


def test_per_scenario_dissociation_and_gives_way():
    e = planted()
    ps = analysis.per_scenario_dissociation(e)
    assert all(v > 0 for v in ps["claude-opus-5.5"].values())
    R = analysis.rate_fn(analysis.pooled(analysis.build(e)["claude-opus-5.5"]))
    assert analysis.gives_way(R, "IX", 0.2) is None and analysis.gives_way(R, "LH", 0.2) == 1
    assert analysis.slope(lambda v, l: None, "LH") is None


def test_escalation_counts_asks_and_informs():
    e = [{"model": "m", "variant": "LH", "level": 3, "outcome": "escalated", "escalation_kind": "asks"},
         {"model": "m", "variant": "IX", "level": 3, "outcome": "escalated", "escalation_kind": "informs"},
         {"model": "m", "variant": "IH", "level": 3, "outcome": "escalated", "escalation_kind": "asks"},
         {"model": "m", "variant": "LH", "level": 3, "outcome": "violation"}]
    assert analysis.escalation(e) == {("m", 3): (1, 1, 3)}


def test_thresholds_fall_back_and_say_so(monkeypatch):
    from phase1 import prereg
    assert analysis.thresholds()[2] is True
    monkeypatch.setitem(prereg.DECISIONS, "near_zero", 0.1)
    monkeypatch.setitem(prereg.DECISIONS, "min_effect", 0.25)
    assert analysis.thresholds() == (0.1, 0.25, False)


@pytest.mark.skipif(not analysis.have_statsmodels(), reason="statsmodels not installed")
def test_mixed_model_runs_and_reports_separation_instead_of_crashing():
    fits = analysis.model_based(planted())
    assert "claude-opus-5.5: ordinal trend" in fits and "pooled: categories" in fits
    ordinal = fits["claude-opus-5.5: ordinal trend"]
    assert ordinal["slopes"]["LH"] > 0.5 and ordinal["slopes"]["LH"] > ordinal["slopes"]["IX"]
    assert "error" in fits["deepseek-v4-flash: categories"]  # never varies, so no estimate


@pytest.mark.skipif(not analysis.have_statsmodels(), reason="statsmodels not installed")
def test_fits_decline_degenerate_data():
    one_scenario = [e for e in planted() if e["scenario"] == "s1" and e["model"] == "claude-opus-5.5"]
    df = analysis.frame(one_scenario)
    assert "fewer than 2 scenarios" in analysis.fit_mixed(df, ordinal=True)["error"]


def test_figures_are_written(tmp_path):
    pytest.importorskip("matplotlib")
    written = analysis.figures(planted(), tmp_path / "f")
    assert {"permission_effect.png", "dose_response.svg", "escalation.png"} <= set(written)
    assert all((tmp_path / "f" / w).stat().st_size > 1000 for w in written)
    assert analysis.figures([], tmp_path / "g") == []
