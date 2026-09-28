"""The Stage 2 exact test and the descriptive bootstrap."""
import pytest

import pilot as P


def test_single_stratum_matches_two_sided_fisher():
    # 3/3 vs 0/3: the hypergeometric puts 1/20 on each extreme.
    assert P.stratified_exact_p([(3, 3, 0, 3)]) == pytest.approx(0.1)
    assert P.stratified_exact_p([(0, 3, 3, 3)]) == pytest.approx(0.1)


def test_floor_and_ceiling_strata_carry_no_information():
    base = [(3, 3, 0, 3)]
    padded = base + [(0, 3, 0, 3)] * 4 + [(3, 3, 3, 3)]
    assert P.stratified_exact_p(padded) == pytest.approx(P.stratified_exact_p(base))


def test_no_difference_gives_p_one():
    assert P.stratified_exact_p([(1, 3, 1, 3), (2, 3, 2, 3)]) == pytest.approx(1.0)
    assert P.stratified_exact_p([(0, 3, 0, 3)]) == pytest.approx(1.0)


def test_consistent_effect_across_strata_is_stronger_than_one():
    one = P.stratified_exact_p([(3, 3, 0, 3)])
    two = P.stratified_exact_p([(3, 3, 0, 3), (3, 3, 0, 3)])
    assert two < one


def test_contrast_verdict_requires_agreeing_settings():
    one_setting = [("a", 3, 3, 0, 3)] + [(s, 0, 3, 0, 3) for s in "bcdef"]
    res = P.contrast_verdict(one_setting)
    assert res["agree"] == 1 and not res["ok"]
    two_settings = [("a", 3, 3, 0, 3), ("b", 3, 3, 0, 3)] + [(s, 0, 3, 0, 3) for s in "cdef"]
    res = P.contrast_verdict(two_settings)
    assert res["agree"] == 2 and res["p"] <= P.STAGE2_ALPHA and res["ok"]
    assert res["diff"] == pytest.approx(6 / 18)


def test_payoff_strata_pool_wordings_within_a_setting():
    strata = [("a", 2, 3, 0, 3), ("a", 1, 3, 0, 3), ("a", 0, 3, 1, 3)]
    res = P.contrast_verdict(strata)
    assert res["agree"] == 1  # setting a counts once, pooled over its wordings


def test_scenario_bootstrap_brackets_a_constant():
    lo, hi = P.scenario_bootstrap(lambda ss: 0.25, ["a", "b", "c"], draws=200)
    assert lo == hi == 0.25
    lo, hi = P.scenario_bootstrap(lambda ss: sum(1 for s in ss if s == "a") / len(ss), ["a", "b"], draws=500)
    assert 0 <= lo < 0.5 < hi <= 1
