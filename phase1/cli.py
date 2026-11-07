"""Phase 1 commands.   uv run python -m phase1 <command>

Free:  check, models, plan, report, analyze, balance
Paid:  neutral, authority-check, competence, calibrate, run, codes, probe, realism, part-a
       Each needs --yes and an explicit --budget: the cap on all Phase 1 spend so far plus this command, at most
       $30. Paid commands are run by a human owner of the project, never by an agent.

Order: write scenarios -> check -> read out_phase1/stimuli_for_review.md -> models -> neutral -> competence ->
       calibrate -> plan -> run -> report, read out_phase1/review.md -> change something -> run again ->
       codes, probe, realism when there are breaks worth explaining
"""
import argparse
import statistics
import sys

import pilot
from phase1 import analysis, authority, checks, config, models, report, runs, stimuli
from sanity import cli as sanity_cli
from sanity import core
from sanity import runs as sanity_runs

OUT_DIR = "out_phase1"
PARTS = ("A", "M", "P", "R", "D")


def setup():
    """Point the shared engine at Phase 1: its output directory, model slate and part letters."""
    core.configure(out=OUT_DIR, models=models.MODELS, parts=PARTS, label="Phase 1")


def selected_scenarios(args):
    keys = [k.strip() for k in args.settings.split(",")] if getattr(args, "settings", None) else sorted(stimuli.SCENARIOS)
    bad = [k for k in keys if k not in stimuli.SCENARIOS]
    if bad:
        sys.exit(f"Unknown scenarios: {bad}. Known: {sorted(stimuli.SCENARIOS)}")
    track = getattr(args, "track", None)
    if track:
        keys = [k for k in keys if stimuli.SCENARIOS[k].track == track]
    if not keys:
        sys.exit("No scenarios selected. Write them in phase1/scenarios/ from _template.py.")
    return keys


def selected_models(args):
    return models.order(sanity_cli.selected(args))


def selected_variants(args):
    return tuple(v.strip() for v in args.variants.split(",")) if getattr(args, "variants", None) else None


def selected_levels(args):
    return tuple(int(l) for l in args.levels.split(",")) if getattr(args, "levels", None) else None


# ---------------------------------------------------------------- free commands

def cmd_check(args):
    problems = checks.all_problems()
    for k, v in problems.items():
        print(f"PROBLEM {k}")
        for x in v:
            print(f"   {x}")
    n_cells = sum(len(stimuli.cells(k)) for k in stimuli.SCENARIOS)
    n_opt = sum(len(stimuli.all_cells(k)) for k in stimuli.SCENARIOS) - n_cells
    tracks = {t: len(stimuli.keys_in(t)) for t in ("illegal", "harm")}
    print(f"{len(stimuli.SCENARIOS)} scenarios ({tracks['illegal']} illegal, {tracks['harm']} harm); {n_cells} cells, plus "
          f"{n_opt} in optional variants. Design version {runs.design_version() if stimuli.SCENARIOS else 'none'}.")
    if stimuli.SCENARIOS:
        core.OUT.mkdir(exist_ok=True)
        path = core.OUT / "stimuli_for_review.md"
        path.write_text(review_text(), encoding="utf-8")
        print(f"Wrote {path} for review.")
    print("Checks clean." if not problems else f"{len(problems)} groups of problems.")
    if problems:
        sys.exit(1)


def review_text():
    lines = ["# Phase 1 stimuli for review", "",
             "Read each scenario for realism, internal consistency, whether the right answer is clear, and anything "
             "that looks like a test. Everything marked ai-draft was drafted by Claude.", ""]
    for key, s in sorted(stimuli.SCENARIOS.items()):
        base = s.variants[1]  # hard or embedded: nothing spotlighted
        lines += [f"## {key} ({s.track} track; {s.domain}; {'contract right' if s.entitlement else 'no contract right'}; "
                  f"{s.provenance} by {s.author or '?'}; names from {s.names_source or '?'})", "",
                  f"**The issue:** {s.crux}", "",
                  f"**Neutral question:** is it legal for {s.check_actor} to {s.check_act}?", "",
                  f"**Target:** {s.score['target']}  **Decoys:** {s.score.get('decoys', [])}  **Controls:** {s.score['controls']}", "",
                  "**Pinned notes**"]
        lines += [f"- L{l} {authority.NAMES[l]}: {authority.note_for(s, base, l)}" for l in sorted(set(base.levels) | {1, 3})]
        lines += ["", "**Variants**"]
        for v in s.variants:
            lines.append(f"- `{v.name}`{' (optional)' if v.optional else ''}: legal={v.legal}, harmful={v.harmful}, levels {v.levels}")
            if v.spotlight:
                lines.append(f"  - spotlight: {v.spotlight}")
            if v.act:
                lines.append(f"  - note's act: {v.act}")
            for where, old, new in v.edits:
                lines.append(f"  - in {where}: \"{old}\" becomes \"{new}\"")
        r = stimuli.render(key, base.name, 1)
        lines += ["", f"**Full episode, `{base.name}` at level 1**", "", "```", r["system"], "", r["user"], "```", ""]
        for name, text in r["documents"].items():
            lines += [f"**Document: {name}**", "", "```", text, "```", ""]
        lines += ["Tools: " + ", ".join(s.tool_names()), ""]
    return "\n".join(lines) + "\n"


def cmd_models(args):
    sanity_cli.cmd_models(args)
    for g in models.gaps():
        print(f"GAP {g}")


def plan_jobs(models_, keys, runs_n, variants, levels):
    eps = runs.episodes()
    return {
        "M": runs.neutral_jobs(models_, keys, config.NEUTRAL_SAMPLES),
        "P": runs.episode_jobs(models_, keys, runs_n, variants, levels) + runs.competence_jobs(models_, config.COMPETENCE_RUNS),
        "R": runs.eval_probe_jobs(eps, config.PROBES_PER_GROUP),
        "D": runs.code_jobs(eps, config.NONACT_CODES),
    }


def cmd_plan(args):
    runs_n = getattr(args, "runs", None) or config.DEFAULT_RUNS
    models_ = selected_models(args)
    keys = selected_scenarios(args)
    costs = core.measured()
    spent = core.spent()
    print(f"Phase 1 spend so far: ${spent:.2f} of the ${config.HARD_CAP:.2f} cap. {runs_n} runs per cell. Projections use "
          "measured costs per part and model only.")
    total = 0.0
    for part, jobs in plan_jobs(models_, keys, runs_n, selected_variants(args), selected_levels(args)).items():
        by = {}
        for j in jobs:
            by[j["model"]] = by.get(j["model"], 0) + 1
        for m, n in sorted(by.items()):
            c = costs.get((part, m))
            if c:
                total += n * statistics.mean(c)
                print(f"  part {part}  {m:<22} {n:>5} left  mean ${statistics.mean(c):.4f}  -> ${n * statistics.mean(c):.2f}")
            else:
                print(f"  part {part}  {m:<22} {n:>5} left  no measured cost yet")
    print(f"Measured projection for what is left: ${total:.2f}, so ${spent + total:.2f} in all (parts without measured "
          "costs not included). Parts R and D depend on the episodes that exist when they run.")
    if spent + total > config.HARD_CAP:
        print(f"That is over the ${config.HARD_CAP:.2f} cap: lower --runs, or use --settings, --variants or --levels.")


def cmd_report(args):
    text, review_file = report.build()
    core.OUT.mkdir(exist_ok=True)
    (core.OUT / "report.md").write_text(text, encoding="utf-8")
    (core.OUT / "review.md").write_text(review_file, encoding="utf-8")
    print(text)
    print(f"Wrote {core.OUT / 'report.md'} and {core.OUT / 'review.md'}.")


def cmd_analyze(args):
    eps = runs.episodes()
    if not eps:
        sys.exit("No Phase 1 episodes yet.")
    written = analysis.figures(eps, core.OUT / "figures")
    print("Wrote " + ", ".join(written) if written else "matplotlib isn't installed (`uv sync --group analysis`).")


def cmd_balance(args):
    pilot.cmd_balance(args)


# ---------------------------------------------------------------- paid commands

def _paid(args, what, jobs):
    if args.budget > config.HARD_CAP:
        sys.exit(f"--budget ${args.budget:.2f} is over the ${config.HARD_CAP:.2f} cap in phase1/config.py. Nothing was run.")
    if not jobs:
        print(f"{what}: nothing left to run.")
        return
    version = runs.design_version()
    jobs = runs.stamped(jobs, version)
    cap = core.confirm_paid(args, what, jobs)
    runs.append_manifest(args.cmd_name, {"what": what, "n_jobs": len(jobs), "budget": args.budget, "note": getattr(args, "note", None),
                                         "models": sorted({j["model"] for j in jobs})}, version)
    before = pilot.credits()
    finished, capped = core.run_jobs(jobs, cap)
    core.summarize_run(finished, capped)
    after = pilot.credits()
    if before and after and before[1] is not None and after[1] is not None:
        print(f"OpenRouter usage rose by ${after[1] - before[1]:.4f} during this command.")


def cmd_neutral(args):
    _paid(args, "Neutral question: legality, harm, seriousness",
          runs.neutral_jobs(selected_models(args), selected_scenarios(args), config.NEUTRAL_SAMPLES, selected_variants(args)))


def cmd_authority_check(args):
    _paid(args, "How strongly each note insists",
          runs.authority_jobs(selected_models(args), selected_scenarios(args), config.AUTHORITY_SAMPLES))


def cmd_competence(args):
    _paid(args, "Competence screen (legal, harmless, owner-gated act)",
          runs.competence_jobs(selected_models(args), config.COMPETENCE_RUNS))


def cmd_calibrate(args):
    _paid(args, "Calibration (1 level-1 episode per model in the first scenario of each track; counts toward the run)",
          runs.calibration_jobs(selected_models(args), selected_scenarios(args)))
    cmd_plan(args)


def cmd_run(args):
    runs_n = args.runs or config.DEFAULT_RUNS
    _paid(args, f"Phase 1 episodes, {runs_n} runs per cell",
          runs.episode_jobs(selected_models(args), selected_scenarios(args), runs_n, selected_variants(args), selected_levels(args)))


def cmd_codes(args):
    _paid(args, "Process codes on every act and a sample of non-acts", runs.code_jobs(runs.episodes(), config.NONACT_CODES))


def cmd_probe(args):
    _paid(args, "Post-episode evaluation probes", runs.eval_probe_jobs(runs.episodes(), config.PROBES_PER_GROUP))


def cmd_realism(args):
    sanity_eps = runs.load_sanity_episodes(args.sanity_dir)
    if not sanity_eps:
        print(f"No sanity-test episodes found in {args.sanity_dir}/part_b.jsonl; pairwise realism needs them "
              "(the directory is git-ignored; the owner shares it separately).")
        return
    _paid(args, "Pairwise realism: Phase 1 against the sanity test",
          runs.realism_jobs(runs.episodes(), sanity_eps, config.REALISM_PAIRS))


def cmd_part_a(args):
    """The Okamoto bridge, reusing the sanity code and stored in out_phase1/part_a.jsonl (default: Kimi K3 only)."""
    _paid(args, "Part A (Okamoto bridge)", sanity_runs.part_a_jobs(selected_models(args), args.trials))
    jobs = sanity_runs.part_a_judge_jobs()
    if jobs:
        print("Judging replies that don't name exactly one vendor, and the second-judge sample:")
        _paid(args, "Part A judging", jobs)


# ---------------------------------------------------------------- entry point

PAID = {"neutral": cmd_neutral, "authority-check": cmd_authority_check, "competence": cmd_competence,
        "calibrate": cmd_calibrate, "run": cmd_run, "codes": cmd_codes, "probe": cmd_probe, "realism": cmd_realism,
        "part-a": cmd_part_a}
FREE = {"check": cmd_check, "models": cmd_models, "plan": cmd_plan, "report": cmd_report, "analyze": cmd_analyze,
        "balance": cmd_balance}


def _selection(p):
    p.add_argument("--only", default=None, help="comma-separated tested-model keys")
    p.add_argument("--settings", default=None, help="comma-separated scenario keys")
    p.add_argument("--track", choices=["illegal", "harm"], default=None)


def _cells(p):
    p.add_argument("--runs", type=int, default=None, help=f"runs per cell (default {config.DEFAULT_RUNS}); already-run reps are skipped")
    p.add_argument("--variants", default=None, help="comma-separated variant names; names optional variants too")
    p.add_argument("--levels", default=None, help="comma-separated note levels, overriding each variant's own")


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m phase1", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="free: stimulus checks; writes the review file")
    sub.add_parser("models", help="free: check slate and judge slugs, list open facts")
    sub.add_parser("balance", help="free: OpenRouter credits (needs the key)")
    p = sub.add_parser("plan", help="free: measured-cost projection")
    _selection(p)
    _cells(p)
    sub.add_parser("report", help="free: tables and review.md")
    sub.add_parser("analyze", help="free: figures")
    helps = {"neutral": "paid: the neutral legal question", "authority-check": "paid: how strongly each note insists",
             "competence": "paid: competence screen", "calibrate": "paid: 1 episode per model per track",
             "run": "paid: the main episodes", "codes": "paid: process codes on acts",
             "probe": "paid: post-episode evaluation probes", "realism": "paid: pairwise realism vs the sanity test",
             "part-a": "paid: Okamoto bridge (default: Kimi K3 only)"}
    for name, helptext in helps.items():
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--budget", type=float, required=True, help=f"cap on all Phase 1 spend, cumulative, USD (at most {config.HARD_CAP:.0f})")
        p.add_argument("--yes", action="store_true", help="confirm spending money")
        p.add_argument("--note", default=None, help="what this round is trying, kept in manifest.jsonl")
        if name == "part-a":
            p.add_argument("--only", default="kimi-k3", help="comma-separated tested-model keys")
            p.add_argument("--trials", type=int, default=25)
        else:
            _selection(p)
        if name in ("run", "calibrate"):
            _cells(p)
        if name == "neutral":
            p.add_argument("--variants", default=None, help="comma-separated variant names; names optional variants too")
        if name == "realism":
            p.add_argument("--sanity-dir", default="out_sanity")
    return ap


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    setup()
    args = build_parser().parse_args(argv)
    args.cmd_name = args.cmd
    {**FREE, **PAID}[args.cmd](args)
