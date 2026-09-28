"""Job builders and runners for each part. Every job resumes: completed items are skipped, errored
items retried, and items whose prompt has changed since they ran are run again as new records."""
import functools
import random

import pilot
from sanity import core, instruments, okamoto, stimuli
from sanity.schema import POLICY_STANCE

FRONTIER = ("claude-opus-5.5", "gpt-6-sol", "grok-4.7")


def _current(part, is_current):
    return {r["id"] for r in core.load(part) if not r.get("error") and is_current(r)}


# ---------------------------------------------------------------- Part A

def run_a(model, cell, trial, rec_id):
    system, user = okamoto.system_prompt(cell), okamoto.user_message(cell, trial)
    out = core.run_single(model, [{"role": "system", "content": system}, {"role": "user", "content": user}], rec_id)
    return {"id": rec_id, "part": "A", "kind": "trial", "model": model, "cell": cell, "trial": trial,
            "seed": okamoto.seed(cell, trial), "vendor_order": [v[0] for v in okamoto.vendor_order(cell, trial)],
            "system": system, "user": user, "prompt_id": stimuli.prompt_id(system, user, []),
            "request": core.request_settings(model, []), **out,
            "deterministic_choice": None if out.get("error") else okamoto.deterministic_choice(out.get("text"))}


def a_is_current(r):
    if r.get("kind") != "trial":
        return True
    return r["prompt_id"] == stimuli.prompt_id(okamoto.system_prompt(r["cell"]),
                                               okamoto.user_message(r["cell"], r["trial"]), [])


def part_a_jobs(models, trials):
    done = _current("A", a_is_current)
    return [{"id": rid, "part": "A", "model": m, "run": functools.partial(run_a, m, cell, t, rid)}
            for t in range(trials) for m in models for cell in okamoto.CELLS
            for rid in [f"A|{m}|{cell}|{t}"] if rid not in done]


def run_a_judge(judge, trial, rec_id):
    out = instruments.judge_call(judge, rec_id, okamoto.JUDGE_SYSTEM, okamoto.judge_prompt(trial.get("text")))
    p = out.get("parsed") or {}
    rec = str(p.get("recommended", "")).strip()
    name = next((n for n in okamoto.VENDOR_NAMES if n.casefold() == rec.casefold()), None)
    return {"id": rec_id, "part": "A", "kind": "judge", "model": judge, "trial_id": trial["id"],
            "request": core.request_settings(judge, [], core.JUDGE_EXTRA), **out,
            "recommended": name or "NONE", "defers": instruments._yes(p.get("defers"))}


def part_a_judge_jobs():
    trials = [r for r in core.load("A") if r.get("kind") == "trial" and not r.get("error") and a_is_current(r)]
    done = core.done_ids("A")
    jobs = []
    for t in trials:
        judges = []
        if t.get("deterministic_choice") is None or instruments.second_judge_sample(t["id"]):
            judges.append(core.PRIMARY_JUDGE)
        if instruments.second_judge_sample(t["id"]):
            judges.append(core.SECOND_JUDGE)
        for j in judges:
            rid = f"A-judge|{j}|{t['id']}"
            if rid not in done:
                jobs.append({"id": rid, "part": "A", "model": j, "run": functools.partial(run_a_judge, j, t, rid)})
    return jobs


# ---------------------------------------------------------------- Parts B and E

def run_b(model, key, stance, rep, rec_id):
    s = stimuli.SETTINGS[key]
    r = stimuli.render(key, stance)
    out = core.run_conversation(model, r["system"], r["user"], r["tools"], r["tool_results"], rec_id)
    rec = {"id": rec_id, "part": "B", "kind": "episode", "model": model, "setting": key, "stance": stance,
           "rep": rep, "cell": s.cell, "family": s.part, "business": s.business,
           "system": r["system"], "user": r["user"], "tools": r["tools"], "tool_results": r["tool_results"],
           "prompt_id": stimuli.prompt_id(r["system"], r["user"], r["tools"]),
           "request": core.request_settings(model, r["tools"]), **out}
    if not out.get("error"):
        outcome, review = stimuli.score(key, out["calls"])
        blob = "\n".join((out.get("text") or []) + (out.get("reasoning") or []))
        rec.update(outcome=outcome, review=review,
                   escalation_kind=stimuli.escalation_kind(key, out["calls"]) if outcome == "escalated" else None,
                   eval_aware=len(pilot.EVAL_PAT.findall(blob)))
    return rec


def b_is_current(r):
    return (r.get("setting") in stimuli.SETTINGS
            and r["prompt_id"] == stimuli.current_prompt_id(r["setting"], r["stance"]))


def part_b_jobs(models, keys, runs, stances=None):
    done = _current("B", b_is_current)
    return [{"id": rid, "part": "B", "model": m, "run": functools.partial(run_b, m, k, st, rep, rid)}
            for rep in range(runs) for m in models for k in keys for st in stimuli.stances(k)
            if stances is None or st in stances
            for rid in [f"B|{m}|{k}|{st}|{rep}"] if rid not in done]


def episodes():
    """Completed Part B and E episodes on current prompts, rescored with the current scorer."""
    out = []
    for r in core.load("B"):
        if r.get("error") or not b_is_current(r):
            continue
        outcome, review = stimuli.score(r["setting"], r["calls"])
        out.append({**r, "stored_outcome": r.get("outcome"), "outcome": outcome, "review": review,
                    "escalation_kind": stimuli.escalation_kind(r["setting"], r["calls"]) if outcome == "escalated" else None})
    # Retries append new records under the same id; keep the latest.
    return list({r["id"]: r for r in out}.values())


# ---------------------------------------------------------------- Part C

def c_is_current(r):
    return r.get("setting") in stimuli.SETTINGS and r["prompt_id"] == stimuli.prompt_id(
        "", instruments.check_prompt(r["setting"]), [])


def part_c_jobs(models, keys, samples):
    done = _current("C", c_is_current)
    return [{"id": rid, "part": "C", "model": m, "run": functools.partial(instruments.run_check, m, k, n, rid)}
            for n in range(samples) for m in models for k in keys
            for rid in [f"C|{m}|{k}|{n}"] if rid not in done]


# ---------------------------------------------------------------- Part D

def probe_set(eps, per_model=10, seed=0):
    """Every violation under forbidden or permitted, plus a fixed sample of non-violations per model."""
    rng = random.Random(seed)
    chosen = [e for e in eps if e["outcome"] == "violation" and e["stance"] != "silent"]
    for m in core.MODELS:
        pool = sorted((e for e in eps if e["model"] == m and e["outcome"] != "violation" and e["stance"] != "silent"),
                      key=lambda e: e["id"])
        chosen += rng.sample(pool, min(per_model, len(pool)))
    return chosen


def part_d_jobs():
    eps = episodes()
    done = core.done_ids("D")
    jobs = []

    def add(rid, model, fn):
        if rid not in done:
            jobs.append({"id": rid, "part": "D", "model": model, "run": fn})

    for e in eps:
        for j in (core.PRIMARY_JUDGE,) + ((core.SECOND_JUDGE,) if instruments.second_judge_sample(e["id"]) else ()):
            rid = f"D-sus|{j}|{e['id']}"
            add(rid, j, functools.partial(instruments.run_suspicion, j, e, rid))
    for e in probe_set(eps):
        rid = f"D-probe|{e['id']}"
        add(rid, e["model"], functools.partial(instruments.run_probe, e, rid))
        for j in (core.PRIMARY_JUDGE,) + ((core.SECOND_JUDGE,) if instruments.second_judge_sample(e["id"]) else ()):
            rid = f"D-proc|{j}|{e['id']}"
            add(rid, j, functools.partial(instruments.run_process, j, e, rid))
    return jobs


CALIBRATION = ("supplier_cancellation", "pet_claim_lapse")


def calibration_jobs(models):
    return [j for j in part_b_jobs(models, CALIBRATION, 1, stances=("silent",))]
