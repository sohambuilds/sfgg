"""Job builders and runners for Phase 1. Every job resumes: completed items are skipped, errored items retried,
and items whose prompt or model settings have changed since they ran are run again as new records. Every record
carries the design hash it ran under; the report lists the hashes it pools."""
import functools
import json
import random
import time
import zlib
from pathlib import Path

import pilot
from phase1 import authority, instruments, prereg, stimuli
from phase1.schema import VARIANTS, variant_flags
from sanity import core
from sanity import instruments as si
from sanity import stimuli as sanity_stimuli


def _current(part, is_current):
    return {r["id"] for r in core.load(part) if not r.get("error") and is_current(r)}


def stamped(jobs, design_hash):
    """Wrap each job so the record it returns carries the design hash."""
    def wrap(job):
        run = job["run"]

        def go():
            rec = run()
            rec["design_hash"] = design_hash
            return rec
        return {**job, "run": go}
    return [wrap(j) for j in jobs]


def append_manifest(command, details, design_hash):
    core.OUT.mkdir(exist_ok=True)
    with open(core.OUT / "manifest.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "command": command,
                            "design_hash": design_hash, **details}) + "\n")


# ---------------------------------------------------------------- episodes

def episode_id(model, key, variant, level, rep):
    return f"P|{model}|{key}|{variant}|L{level}|{rep}"


def run_episode(model, key, variant, level, rep, rec_id):
    s = stimuli.SCENARIOS[key]
    r = stimuli.render(key, variant, level)
    out = core.run_conversation(model, r["system"], r["user"], r["tools"], r["tool_results"], rec_id)
    legal, harmful = variant_flags(variant)
    rec = {"id": rec_id, "part": "P", "kind": "episode", "model": model, "scenario": key, "variant": variant,
           "legal": legal, "harm": harmful, "level": level, "rep": rep, "domain": s.domain,
           "entitlement": s.entitlement, "owner": s.owner, "act": s.act,
           "system": r["system"], "user": r["user"], "tools": r["tools"], "documents": r["documents"],
           "tool_results": r["tool_results_stored"],
           "prompt_id": stimuli.prompt_id(r["system"], r["user"], r["tools"], r["documents"]),
           "request": core.request_settings(model, r["tools"]), **out}
    if not out.get("error"):
        rec.update(derived(key, out))
    return rec


def derived(key, out):
    """Outcome and descriptive fields computed from an episode's stored output."""
    outcome, review = stimuli.score(key, out["calls"])
    blob = "\n".join((out.get("text") or []) + (out.get("reasoning") or []))
    done, need = stimuli.routine_progress(key, out["calls"])
    return {"outcome": outcome, "review": review,
            "escalation_kind": stimuli.escalation_kind(key, out["calls"]) if outcome == "escalated" else None,
            "eval_aware": len(pilot.EVAL_PAT.findall(blob)), "documents_read": stimuli.documents_read(key, out["calls"]),
            "routine_done": done, "routine_need": need}


def request_matches(r):
    """The record was sent with the model settings now in force (slug, reasoning, token limit, routing)."""
    if r.get("model") not in core.MODELS:
        return False
    cur = core.request_settings(r["model"], r.get("tools") or [])
    return all(r.get("request", {}).get(k) == cur[k] for k in ("slug", "reasoning", "max_tokens", "require_parameters"))


def is_current_episode(r):
    """Pooling and resume key on what the model saw and how it was set up, not on the whole design hash: a
    re-freeze that changes only the pre-registration text must not force every episode to rerun. The hash stays
    on the record, and the report lists every hash it pools."""
    if r.get("kind") != "episode":
        return True
    return (r.get("scenario") in stimuli.SCENARIOS and request_matches(r)
            and r["prompt_id"] == stimuli.current_prompt_id(r["scenario"], r["variant"], r["level"]))


def episode_jobs(models, keys, runs_by_model, cross, cell_filter=None):
    done = _current("P", is_current_episode)
    cells = [c for c in stimuli.cells(cross) if cell_filter is None or c in cell_filter]
    top = max(runs_by_model.values(), default=0)
    return [{"id": rid, "part": "P", "model": m,
             "run": functools.partial(run_episode, m, k, v, l, rep, rid)}
            for rep in range(top) for m in models if rep < runs_by_model.get(m, 0)
            for k in keys for v, l in cells
            for rid in [episode_id(m, k, v, l, rep)] if rid not in done]


def calibration_jobs(models, keys):
    """One episode per model in the first two scenarios, legal-harmful at level 1. They count toward the run."""
    return episode_jobs(models, sorted(keys)[:2], {m: 1 for m in models}, "trimmed", cell_filter={("LH", 1)})


# ---------------------------------------------------------------- competence screen (legal, harmless, owner-gated)

def run_competence(model, stance, rep, rec_id):
    r = sanity_stimuli.render(stimuli.COMPETENCE_SETTING, stance)
    out = core.run_conversation(model, r["system"], r["user"], r["tools"], r["tool_results"], rec_id)
    rec = {"id": rec_id, "part": "P", "kind": "competence", "model": model, "setting": stimuli.COMPETENCE_SETTING,
           "stance": stance, "rep": rep, "system": r["system"], "user": r["user"], "tools": r["tools"],
           "tool_results": r["tool_results"],
           "prompt_id": sanity_stimuli.prompt_id(r["system"], r["user"], r["tools"]),
           "request": core.request_settings(model, r["tools"]), **out}
    if not out.get("error"):
        outcome, review = sanity_stimuli.score(stimuli.COMPETENCE_SETTING, out["calls"])
        rec.update(outcome=outcome, review=review)
    return rec


def is_current_competence(r):
    return (r.get("kind") != "competence" or
            (request_matches(r) and
             r["prompt_id"] == sanity_stimuli.current_prompt_id(stimuli.COMPETENCE_SETTING, r["stance"])))


def competence_jobs(models, runs):
    done = _current("P", is_current_competence)
    return [{"id": rid, "part": "P", "model": m, "run": functools.partial(run_competence, m, st, rep, rid)}
            for rep in range(runs) for m in models for st in stimuli.COMPETENCE_STANCES
            for rid in [f"P|{m}|competence|{st}|{rep}"] if rid not in done]


# ---------------------------------------------------------------- manipulation checks

def c_is_current(r):
    if r.get("kind") == "check":
        return (r.get("scenario") in stimuli.SCENARIOS and
                r["prompt_id"] == stimuli.prompt_id("", instruments.check_prompt(r["scenario"], r["variant"]), []))
    if r.get("kind") == "authority":
        return (r.get("scenario") in stimuli.SCENARIOS and
                r["prompt_id"] == stimuli.prompt_id("", instruments.authority_prompt(r["scenario"], r["level"]), []))
    return True


def manip_jobs(models, keys, samples):
    done = _current("M", c_is_current)
    return [{"id": rid, "part": "M", "model": m, "run": functools.partial(instruments.run_check, m, k, v, n, rid)}
            for n in range(samples) for m in models for k in keys for v in VARIANTS
            for rid in [f"M|check|{m}|{k}|{v}|{n}"] if rid not in done]


def authority_jobs(models, keys, samples):
    done = _current("M", c_is_current)
    return [{"id": rid, "part": "M", "model": m, "run": functools.partial(instruments.run_authority, m, k, l, n, rid)}
            for n in range(samples) for m in models for k in keys for l in authority.LEVELS
            for rid in [f"M|authority|{m}|{k}|L{l}|{n}"] if rid not in done]


# ---------------------------------------------------------------- loading episodes for reports and instruments

def episodes(design_hash=None):
    """Completed episodes whose prompt and model settings are current, rescored with the current scorer.
    design_hash: None for all of them, or one hash to restrict to. Retries under the same id keep the latest
    record. Returns (episodes, design hashes among them)."""
    recs = [r for r in core.load("P") if r.get("kind") == "episode" and not r.get("error")]
    out = []
    for r in recs:
        if not is_current_episode(r):
            continue
        if design_hash and r.get("design_hash") != design_hash:
            continue
        outcome, review = stimuli.score(r["scenario"], r["calls"])
        done, need = stimuli.routine_progress(r["scenario"], r["calls"])
        out.append({**r, "stored_outcome": r.get("outcome"), "outcome": outcome, "review": review,
                    "escalation_kind": stimuli.escalation_kind(r["scenario"], r["calls"]) if outcome == "escalated" else None,
                    "routine_done": done, "routine_need": need,
                    "documents_read": stimuli.documents_read(r["scenario"], r["calls"])})
    out = list({r["id"]: r for r in out}.values())
    return out, sorted({r.get("design_hash") or "unstamped" for r in out})


def competence_episodes():
    recs = [r for r in core.load("P") if r.get("kind") == "competence" and not r.get("error")
            and is_current_competence(r)]
    out = []
    for r in recs:
        outcome, review = sanity_stimuli.score(stimuli.COMPETENCE_SETTING, r["calls"])
        out.append({**r, "outcome": outcome, "review": review})
    return list({r["id"]: r for r in out}.values())


# ---------------------------------------------------------------- instruments over stored episodes

def crc_pick(items, key, n):
    """The n items with the smallest CRC of their key: a deterministic sample."""
    return sorted(items, key=lambda x: zlib.crc32(key(x).encode()))[:n]


def eval_probe_jobs(eps, per_cell):
    done = core.done_ids("R")
    cells = {}
    for e in eps:
        cells.setdefault((e["model"], e["scenario"], e["variant"], e["level"]), []).append(e)
    chosen = [e for group in cells.values() for e in crc_pick(group, lambda x: x["id"], per_cell)]
    return [{"id": rid, "part": "R", "model": e["model"], "run": functools.partial(instruments.run_eval_probe, e, rid)}
            for e in sorted(chosen, key=lambda x: x["id"]) for rid in [f"R-eval|{e['id']}"] if rid not in done]


def probe_set(eps, per_model, seed=0):
    """Every violation (at any level), plus a fixed sample of non-violations per model at level 1 or above."""
    rng = random.Random(seed)
    chosen = [e for e in eps if e["outcome"] == "violation"]
    for m in sorted({e["model"] for e in eps}):
        pool = sorted((e for e in eps if e["model"] == m and e["outcome"] != "violation" and e["level"] >= 1),
                      key=lambda e: e["id"])
        chosen += rng.sample(pool, min(per_model, len(pool)))
    return chosen


def part_d_jobs(eps, per_model):
    done = core.done_ids("D")
    jobs = []
    for e in probe_set(eps, per_model):
        rid = f"D-probe|{e['id']}"
        if rid not in done:
            jobs.append({"id": rid, "part": "D", "model": e["model"], "run": functools.partial(instruments.run_probe, e, rid)})
        for j in (core.PRIMARY_JUDGE,) + ((core.SECOND_JUDGE,) if si.second_judge_sample(e["id"]) else ()):
            rid = f"D-proc|{j}|{e['id']}"
            if rid not in done:
                jobs.append({"id": rid, "part": "D", "model": j, "run": functools.partial(instruments.run_process, j, e, rid)})
    return jobs


def load_sanity_episodes(sanity_dir):
    """Permitted-stance Part B and E episodes from the sanity test's results, if the directory exists."""
    path = Path(sanity_dir) / "part_b.jsonl"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        recs = [json.loads(line) for line in f if line.strip()]
    return [r for r in recs if not r.get("error") and r.get("stance") == "permitted" and r.get("calls") is not None]


def realism_jobs(eps, sanity_eps, pairs, seed=0):
    """Phase 1 level-1 episodes against sanity permitted episodes, each pair judged in both orders."""
    done = core.done_ids("R")
    p1 = sorted((e for e in eps if e["level"] == 1), key=lambda e: e["id"])
    sa = sorted(sanity_eps, key=lambda e: e["id"])
    if not p1 or not sa:
        return []
    rng = random.Random(seed)
    jobs = []
    for _ in range(pairs):
        a, b = rng.choice(p1), rng.choice(sa)
        for first in (True, False):
            for j in (core.PRIMARY_JUDGE,) + ((core.SECOND_JUDGE,) if si.second_judge_sample(a["id"] + b["id"]) else ()):
                rid = f"R-pair|{j}|{a['id']}|{b['id']}|{'p1first' if first else 'p1second'}"
                if rid not in done and not any(x["id"] == rid for x in jobs):
                    jobs.append({"id": rid, "part": "R", "model": j,
                                 "run": functools.partial(instruments.run_pair, j, a, b, first, rid)})
    return jobs
