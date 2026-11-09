"""Job builders and runners for Phase 1. Every job resumes: completed items are skipped, errored items retried,
and items whose prompt or model settings have changed since they ran are run again as new records. Every record
carries the design version it ran under, and changed text never pools with earlier records."""
import functools
import hashlib
import json
import random
import time
import zlib
from pathlib import Path

import pilot
from phase1 import authority, config, instruments, stimuli
from sanity import core
from sanity import instruments as si
from sanity import stimuli as sanity_stimuli


def _current(part, is_current):
    return {r["id"] for r in core.load(part) if not r.get("error") and is_current(r)}


def design_version():
    """A short stamp over every prompt, the slate and the settings. It's a label for a round, not a gate."""
    blob = {"cells": {k: {f"{v}|L{l}": stimuli.current_prompt_id(k, v, l) for v, l in stimuli.all_cells(k)}
                      for k in sorted(stimuli.SCENARIOS)},
            "models": core.MODELS, "max_turns": config.MAX_TURNS, "max_tokens": pilot.MAX_TOKENS}
    return hashlib.sha256(json.dumps(blob, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]


def stamped(jobs, version):
    """Wrap each job so the record it returns carries the design version."""
    def wrap(job):
        run = job["run"]

        def go():
            rec = run()
            rec["design_version"] = version
            return rec
        return {**job, "run": go}
    return [wrap(j) for j in jobs]


def append_manifest(command, details, version):
    core.OUT.mkdir(exist_ok=True)
    with open(core.OUT / "manifest.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "command": command,
                            "design_version": version, **details}) + "\n")


# ---------------------------------------------------------------- episodes

def episode_id(model, key, variant, level, rep):
    return f"P|{model}|{key}|{variant}|L{level}|{rep}"


def request(model, tools):
    return core.request_settings(model, tools, {"max_turns": config.MAX_TURNS})


def run_episode(model, key, variant, level, rep, rec_id):
    s = stimuli.SCENARIOS[key]
    v = s.variant(variant)
    r = stimuli.render(key, variant, level)
    out = core.run_conversation(model, r["system"], r["user"], r["tools"], r["tool_results"], rec_id,
                                max_turns=config.MAX_TURNS)
    rec = {"id": rec_id, "part": "P", "kind": "episode", "model": model, "scenario": key, "track": s.track,
           "variant": variant, "legal": v.legal, "harm": v.harmful, "level": level, "rep": rep, "domain": s.domain,
           "entitlement": s.entitlement, "provenance": s.provenance, "author": s.author, "owner": s.owner,
           "system": r["system"], "user": r["user"], "tools": r["tools"], "documents": r["documents"],
           "tool_results": r["tool_results_stored"],
           "prompt_id": stimuli.prompt_id(r["system"], r["user"], r["tools"], r["documents"]),
           "request": request(model, r["tools"]), **out}
    if not out.get("error"):
        rec.update(derived(key, out))
    return rec


def derived(key, out):
    """Outcome and descriptive fields computed from an episode's stored output."""
    calls = out["calls"]
    outcome, review = stimuli.score(key, calls)
    blob = "\n".join((out.get("text") or []) + (out.get("reasoning") or []))
    done, need = stimuli.routine_progress(key, calls)
    return {"outcome": outcome, "review": review,
            "escalation_kind": stimuli.escalation_kind(key, calls) if outcome == "escalated" else None,
            "eval_aware": len(pilot.EVAL_PAT.findall(blob)), "documents_read": stimuli.documents_read(key, calls),
            "key_docs_opened": stimuli.key_documents_opened(key, calls), "told_owner": stimuli.told_owner(key, calls),
            "mentions_target": stimuli.mentions_target(key, out), "routine_done": done, "routine_need": need,
            **stimuli.job_progress(key, calls)}


def request_matches(r):
    """The record was sent with the model settings now in force (slug, reasoning, limits, routing)."""
    if r.get("model") not in core.MODELS:
        return False
    cur = request(r["model"], r.get("tools") or [])
    return all(r.get("request", {}).get(k) == cur[k] for k in ("slug", "reasoning", "max_tokens", "require_parameters", "max_turns"))


def is_current_episode(r):
    """Pooling and resume key on what the model saw and how it was set up."""
    if r.get("kind") != "episode":
        return True
    s = stimuli.SCENARIOS.get(r.get("scenario"))
    if s is None or r["variant"] not in [v.name for v in s.variants]:
        return False
    return request_matches(r) and r["prompt_id"] == stimuli.current_prompt_id(r["scenario"], r["variant"], r["level"])


def episode_jobs(models, keys, runs_n, variants=None, levels=None):
    """Reps run outermost, so a budget stop leaves every cell with about the same number of runs."""
    done = _current("P", is_current_episode)
    return [{"id": rid, "part": "P", "model": m,
             "run": functools.partial(run_episode, m, k, v, l, rep, rid)}
            for rep in range(runs_n) for m in models
            for k in keys for v, l in stimuli.cells(k, variants, levels)
            for rid in [episode_id(m, k, v, l, rep)] if rid not in done]


def calibration_jobs(models, keys):
    """One level-1 episode per model in the first scenario of each track. They count toward the run."""
    jobs = []
    for track, variant in (("illegal", "hard"), ("harm", "embedded")):
        first = [k for k in keys if stimuli.SCENARIOS[k].track == track][:1]
        jobs += episode_jobs(models, first, 1, variants=(variant,), levels=(1,))
    return jobs


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
    if r.get("kind") != "competence":
        return True
    cfg = core.MODELS.get(r["model"])
    return (cfg is not None and r.get("request", {}).get("slug") == cfg["slug"]
            and r["prompt_id"] == sanity_stimuli.current_prompt_id(stimuli.COMPETENCE_SETTING, r["stance"]))


def competence_jobs(models, runs):
    done = _current("P", is_current_competence)
    return [{"id": rid, "part": "P", "model": m, "run": functools.partial(run_competence, m, st, rep, rid)}
            for rep in range(runs) for m in models for st in stimuli.COMPETENCE_STANCES
            for rid in [f"P|{m}|competence|{st}|{rep}"] if rid not in done]


# ---------------------------------------------------------------- neutral question and note ratings

def c_is_current(r):
    if r.get("scenario") not in stimuli.SCENARIOS:
        return r.get("kind") not in ("check", "authority")
    if r.get("kind") == "check":
        return r["prompt_id"] == stimuli.prompt_id("", instruments.check_prompt(r["scenario"], r["variant"]), [])
    if r.get("kind") == "authority":
        return r["prompt_id"] == stimuli.prompt_id("", instruments.authority_prompt(r["scenario"], r["level"]), [])
    return True


def neutral_jobs(models, keys, samples, variants=None):
    """An answer that couldn't be parsed (round 1: three empty replies) is asked again."""
    done = _current("M", lambda r: c_is_current(r) and not r.get("unparsed"))
    return [{"id": rid, "part": "M", "model": m, "run": functools.partial(instruments.run_check, m, k, v, n, rid)}
            for n in range(samples) for m in models for k in keys for v in instruments.neutral_variants(k, variants)
            for rid in [f"M|check|{m}|{k}|{v}|{n}"] if rid not in done]


def authority_jobs(models, keys, samples):
    done = _current("M", c_is_current)
    return [{"id": rid, "part": "M", "model": m, "run": functools.partial(instruments.run_authority, m, k, l, n, rid)}
            for n in range(samples) for m in models for k in keys for l in authority.LEVELS
            for rid in [f"M|authority|{m}|{k}|L{l}|{n}"] if rid not in done]


# ---------------------------------------------------------------- loading episodes for reports and instruments

def episodes():
    """Completed episodes whose prompt and model settings are current, rescored with the current scorer. Retries
    under the same id keep the latest record."""
    recs = [r for r in core.load("P") if r.get("kind") == "episode" and not r.get("error")]
    out = []
    for r in recs:
        if is_current_episode(r):
            out.append({**r, "stored_outcome": r.get("outcome"), **derived(r["scenario"], r)})
    return list({r["id"]: r for r in out}.values())


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


def eval_probe_jobs(eps, per_group):
    done = core.done_ids("R")
    groups = {}
    for e in eps:
        groups.setdefault((e["model"], e["track"], e["variant"]), []).append(e)
    chosen = [e for group in groups.values() for e in crc_pick(group, lambda x: x["id"], per_group)]
    return [{"id": rid, "part": "R", "model": e["model"], "run": functools.partial(instruments.run_eval_probe, e, rid)}
            for e in sorted(chosen, key=lambda x: x["id"]) for rid in [f"R-eval|{e['id']}"] if rid not in done]


def coding_set(eps, nonacts, seed=0):
    """Every act where the crux applies (not the harmless twins or rule-free variants), plus a fixed sample of
    non-acts per model."""
    relevant = [e for e in eps if e["harm"] or not e["legal"]]
    chosen = [e for e in relevant if e["outcome"] == "violation"]
    rng = random.Random(seed)
    for m in sorted({e["model"] for e in relevant}):
        pool = sorted((e for e in relevant if e["model"] == m and e["outcome"] != "violation"), key=lambda e: e["id"])
        chosen += rng.sample(pool, min(nonacts, len(pool)))
    return chosen


def code_jobs(eps, nonacts):
    done = core.done_ids("D")
    jobs = []
    for e in coding_set(eps, nonacts):
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
