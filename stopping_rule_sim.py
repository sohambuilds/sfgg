#!/usr/bin/env python3
"""Operating characteristics of the Stage 2 stop rule, by simulation. Free; no model calls.

Draws violation counts for 5 models x 6 harm settings x 6 cells x 3 runs from known true rates
and reports how often each rule says CONTINUE. "old" is the rule in design a0c19c15 (pooled
difference >= 20 points and the same direction in >= 3 of 6 settings); "current" is the rule
in pilot.py. Used to choose STAGE2_ALPHA; the table is copied into RESEARCH.md section 13.

    python stopping_rule_sim.py [--sims 3000]
"""
import argparse
import random

import pilot as P

SETTINGS, RUNS, MODELS = 6, 3, 5
WORDINGS = ("forbidden", "silent", "allowed")
CELLS = [(w, z) for w in WORDINGS for z in ("low", "high")]


def world(f):
    return {c: [f(c, s) for s in range(SETTINGS)] for c in CELLS}


WORLDS = {
    "no effect, p=.3 everywhere": world(lambda c, s: .3),
    "no effect, p=.5 everywhere": world(lambda c, s: .5),
    "no effect, settings at 0,0,.1,.3,.6,.9": world(lambda c, s: [0, 0, .1, .3, .6, .9][s]),
    "wording 40pt in 2 settings, floor elsewhere": world(
        lambda c, s: (.5 if c[0] == "allowed" else .1) if s < 2 else 0),
    "wording 30pt in all 6": world(lambda c, s: .45 if c[0] == "allowed" else .15),
    "wording 20pt in all 6": world(lambda c, s: .35 if c[0] == "allowed" else .15),
    "payoff 30pt in 3 settings, floor elsewhere": world(
        lambda c, s: (.4 if c[1] == "high" else .1) if s < 3 else 0),
    "one setting only, near 3/3 vs 0/3": world(
        lambda c, s: (.95 if c[0] == "allowed" else .02) if s == 0 else 0),
}


def strata(cnt):
    wording = [(s, cnt[("allowed", "high")][s], RUNS, cnt[("forbidden", "high")][s], RUNS)
               for s in range(SETTINGS)]
    payoff = [(s, cnt[(w, "high")][s], RUNS, cnt[(w, "low")][s], RUNS)
              for s in range(SETTINGS) for w in WORDINGS]
    return wording, payoff


def old_rule(st):
    va, na = sum(x[1] for x in st), sum(x[2] for x in st)
    vb, nb = sum(x[3] for x in st), sum(x[4] for x in st)
    diff = va / na - vb / nb
    per = {}
    for s, a, n_a, b, n_b in st:
        per[s] = per.get(s, 0) + a / n_a - b / n_b
    return abs(diff) >= 0.20 and sum(1 for d in per.values() if d * diff > 0) >= 3


def current_rule(st):
    return P.contrast_verdict(st)["ok"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    rules = {"old": old_rule, f"current (alpha={P.STAGE2_ALPHA})": current_rule}
    print(f"P(CONTINUE) over {args.sims} simulated pilots; CONTINUE needs >= {P.STAGE2_MIN_MODELS} "
          f"of {MODELS} models to pass either contrast")
    print(f"{'true world':<46}" + "".join(f"{r:>24}" for r in rules))
    for name, rates in WORLDS.items():
        hits = dict.fromkeys(rules, 0)
        for _ in range(args.sims):
            passes = dict.fromkeys(rules, 0)
            for _ in range(MODELS):
                cnt = {c: [sum(rng.random() < rates[c][s] for _ in range(RUNS)) for s in range(SETTINGS)]
                       for c in CELLS}
                wording, payoff = strata(cnt)
                for r, rule in rules.items():
                    passes[r] += rule(wording) or rule(payoff)
            for r in rules:
                hits[r] += passes[r] >= P.STAGE2_MIN_MODELS
        print(f"{name:<46}" + "".join(f"{hits[r] / args.sims:>24.2f}" for r in rules))


if __name__ == "__main__":
    main()
