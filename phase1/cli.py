"""Phase 1 commands.   uv run python -m phase1 <command>

Free:  check, models, freeze, plan, report, analyze, balance
Paid:  manip, authority-check, competence, calibrate, run, probe, part-d, realism, part-a
       Each needs a frozen design (`freeze`), --yes, and an explicit --budget: the cap on all Phase 1 spend so far
       plus this command. Paid commands are run by a human owner of the project, never by an agent.

Order: write scenarios -> check -> owner review of out_phase1/stimuli_for_review.md -> decide phase1/prereg.py ->
       freeze -> models -> manip, authority-check -> competence -> calibrate -> plan -> run -> probe, part-d,
       realism -> report, analyze
"""
import argparse
import statistics
import sys

import pilot
from phase1 import analysis, authority, checks, freeze, models, prereg, report, runs, stimuli
from phase1.schema import VARIANTS
from sanity import cli as sanity_cli
from sanity import core
from sanity import runs as sanity_runs

OUT_DIR = "out_phase1"
PARTS = ("A", "M", "P", "R", "D")


def setup():
    """Point the shared engine at Phase 1: its output directory, five-model slate and part letters."""
    core.configure(out=OUT_DIR, models=models.MODELS, parts=PARTS, label="Phase 1")


def selected_scenarios(args):
    keys = [k.strip() for k in args.settings.split(",")] if getattr(args, "settings", None) else sorted(stimuli.SCENARIOS)
    bad = [k for k in keys if k not in stimuli.SCENARIOS]
    if bad:
        sys.exit(f"Unknown scenarios: {bad}. Known: {sorted(stimuli.SCENARIOS)}")
    if not keys:
        sys.exit("No scenarios yet: write them in phase1/scenarios/ from _template.py.")
    return keys


def selected_models(args):
    return models.order(sanity_cli.selected(args))


# ---------------------------------------------------------------- free commands

def cmd_check(args):
    problems = checks.all_problems()
    for k, v in problems.items():
        print(f"PROBLEM {k}")
        for x in v:
            print(f"   {x}")
    n = len(stimuli.SCENARIOS)
    print(f"{n} scenarios; {n * len(VARIANTS) * len(authority.LEVELS)} cells in the full cross "
          f"({n * len(stimuli.cells('trimmed'))} trimmed).")
    if n:
        core.OUT.mkdir(exist_ok=True)
        lines = ["# Phase 1 stimuli for review", "",
                 "Read each scenario for realism, internal consistency, legal accuracy and anything that looks like a "
                 "test. Names should be chosen by a person. The authority wording below is the draft.", ""]
        for key, s in stimuli.SCENARIOS.items():
            lines += [f"## {key} ({s.domain}; entitlement={'contract right' if s.entitlement else 'mere permissibility'}; "
                      f"author {s.author or '?'}; names from {s.names_source or '?'})", "",
                      f"Legality toggle: **legal** \"{s.legality.on}\" / **illegal** \"{s.legality.off}\"",
                      f"Harm toggle: **harmful** \"{s.harm.on}\" / **harmless** \"{s.harm.off}\"", "",
                      "Pinned notes:"]
            lines += [f"- L{l} {authority.NAMES[l]}: {authority.note(s.owner, s, l)}" for l in authority.LEVELS]
            lines += ["", "Documents: " + ", ".join(s.documents), "",
                      f"Manipulation-check question (LH): {s.check_actor} to {s.check_act}", ""]
            r = stimuli.render(key, "LH", 1)
            lines += ["Full episode, LH at level 1:", "", "```", r["system"], "", r["user"], "```", "",
                      "Tools: " + ", ".join(s.tool_names()), ""]
        path = core.OUT / "stimuli_for_review.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Wrote {path} for the owner's review.")
    print("Checks clean." if not problems else f"{len(problems)} groups of problems.")
    if problems:
        sys.exit(1)


def cmd_models(args):
    sanity_cli.cmd_models(args)
    for g in models.gaps():
        print(f"GAP {g}")


def cmd_freeze(args):
    if args.dry:
        blockers = freeze.blockers()
        print(f"Design hash now: {freeze.design_hash()[:16]}; frozen: {(freeze.frozen_hash() or 'not frozen')[:16]}")
        print("Blocking a freeze:\n  " + "\n  ".join(blockers) if blockers else "Nothing blocks a freeze.")
        return
    entry = freeze.freeze(args.note or "")
    print(f"Frozen {entry['hash'][:16]} ({entry['n_cells']} cells, {len(entry['scenarios'])} scenarios).")
    for g in models.gaps():
        print(f"note: {g}")


def plan_jobs(models_, keys, runs_n, cross):
    inst = prereg.INSTRUMENTS
    eps, _ = runs.episodes()
    by_model = {m: prereg.RUNS_OVERRIDE.get(m, runs_n) for m in models_}
    return {
        "M": runs.manip_jobs(models_, keys, inst["manip_samples"]) + runs.authority_jobs(models_, keys, inst["manip_samples"]),
        "P": runs.episode_jobs(models_, keys, by_model, cross) + runs.competence_jobs(models_, inst["competence_runs"]),
        "R": runs.eval_probe_jobs(eps, inst["probe_per_cell"]),
        "D": runs.part_d_jobs(eps, inst["nonviolation_probes"]),
    }


def cmd_plan(args):
    cross = args.cross or prereg.DECISIONS["cross"]
    runs_n = args.runs or prereg.DECISIONS["runs_per_cell"]
    if cross is None or runs_n is None:
        cross, runs_n = cross or "trimmed", runs_n or 5
        print(f"What-if plan: the pre-specification hasn't decided runs and cross, so this uses {runs_n} runs and the "
              f"{cross} cross.")
    models_ = selected_models(args)
    keys = selected_scenarios(args)
    costs = core.measured()
    print(f"Phase 1 spend so far: ${core.spent():.2f}. Projections use measured costs per part and model only.")
    total = 0.0
    for part, jobs in plan_jobs(models_, keys, runs_n, cross).items():
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
    print(f"Measured projection for what is left: ${total:.2f} (parts without measured costs not included). Parts R and "
          "D depend on the episodes that exist when they run.")


def cmd_report(args):
    text, review_text = report.build(args.hash)
    core.OUT.mkdir(exist_ok=True)
    (core.OUT / "report.md").write_text(text, encoding="utf-8")
    (core.OUT / "review.md").write_text(review_text, encoding="utf-8")
    print(text)
    print(f"Wrote {core.OUT / 'report.md'} and {core.OUT / 'review.md'}.")


def cmd_analyze(args):
    eps, _ = runs.episodes(args.hash)
    if not eps:
        sys.exit("No Phase 1 episodes yet.")
    written = analysis.figures(eps, core.OUT / "figures")
    print("Wrote " + ", ".join(written) if written else "matplotlib isn't installed (`uv sync --group analysis`).")


def cmd_balance(args):
    pilot.cmd_balance(args)


# ---------------------------------------------------------------- paid commands

def _paid(args, what, jobs, design_hash):
    if not jobs:
        print(f"{what}: nothing left to run.")
        return
    jobs = runs.stamped(jobs, design_hash)
    cap = core.confirm_paid(args, what, jobs)
    runs.append_manifest(args.cmd_name, {"what": what, "n_jobs": len(jobs), "budget": args.budget,
                                         "models": sorted({j["model"] for j in jobs})}, design_hash)
    before = pilot.credits()
    finished, capped = core.run_jobs(jobs, cap)
    core.summarize_run(finished, capped)
    after = pilot.credits()
    if before and after and before[1] is not None and after[1] is not None:
        print(f"OpenRouter usage rose by ${after[1] - before[1]:.4f} during this command.")


def cmd_manip(args):
    dh = freeze.guard()
    _paid(args, "Manipulation check: legality, harm, seriousness",
          runs.manip_jobs(selected_models(args), selected_scenarios(args), prereg.INSTRUMENTS["manip_samples"]), dh)


def cmd_authority_check(args):
    dh = freeze.guard()
    _paid(args, "Manipulation check: how strongly each note insists",
          runs.authority_jobs(selected_models(args), selected_scenarios(args), prereg.INSTRUMENTS["manip_samples"]), dh)


def cmd_competence(args):
    dh = freeze.guard()
    _paid(args, "Competence screen (legal, harmless, owner-gated act)",
          runs.competence_jobs(selected_models(args), prereg.INSTRUMENTS["competence_runs"]), dh)


def cmd_calibrate(args):
    dh = freeze.guard()
    _paid(args, "Calibration (1 legal-harmful level-1 episode per model in the first two scenarios; counts toward the run)",
          runs.calibration_jobs(selected_models(args), selected_scenarios(args)), dh)
    cmd_plan(args)


def cmd_run(args):
    dh = freeze.guard()
    models_ = selected_models(args)
    by_model = {m: prereg.runs_for(m) for m in models_}
    _paid(args, f"Phase 1 episodes ({prereg.DECISIONS['cross']} cross)",
          runs.episode_jobs(models_, selected_scenarios(args), by_model, prereg.DECISIONS["cross"]), dh)


def cmd_probe(args):
    dh = freeze.guard()
    eps, _ = runs.episodes()
    _paid(args, "Post-episode evaluation probes", runs.eval_probe_jobs(eps, prereg.INSTRUMENTS["probe_per_cell"]), dh)


def cmd_part_d(args):
    dh = freeze.guard()
    eps, _ = runs.episodes()
    _paid(args, "Recognition probes and process codes", runs.part_d_jobs(eps, prereg.INSTRUMENTS["nonviolation_probes"]), dh)


def cmd_realism(args):
    dh = freeze.guard()
    eps, _ = runs.episodes()
    sanity_eps = runs.load_sanity_episodes(args.sanity_dir)
    if not sanity_eps:
        print(f"No sanity-test episodes found in {args.sanity_dir}/part_b.jsonl; pairwise realism needs them "
              "(the directory is git-ignored; the owner shares it separately).")
        return
    _paid(args, "Pairwise realism: Phase 1 against the sanity test",
          runs.realism_jobs(eps, sanity_eps, prereg.INSTRUMENTS["realism_pairs"]), dh)


def cmd_part_a(args):
    """The Okamoto bridge, reusing the sanity code and stored in out_phase1/part_a.jsonl (default: Kimi K3 only)."""
    dh = freeze.guard()
    _paid(args, "Part A (Okamoto bridge)", sanity_runs.part_a_jobs(selected_models(args), args.trials), dh)
    jobs = sanity_runs.part_a_judge_jobs()
    if jobs:
        print("Judging replies that don't name exactly one vendor, and the second-judge sample:")
        _paid(args, "Part A judging", jobs, dh)


# ---------------------------------------------------------------- entry point

PAID = {"manip": cmd_manip, "authority-check": cmd_authority_check, "competence": cmd_competence,
        "calibrate": cmd_calibrate, "run": cmd_run, "probe": cmd_probe, "part-d": cmd_part_d, "realism": cmd_realism,
        "part-a": cmd_part_a}
FREE = {"check": cmd_check, "models": cmd_models, "freeze": cmd_freeze, "plan": cmd_plan, "report": cmd_report,
        "analyze": cmd_analyze, "balance": cmd_balance}


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m phase1", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="free: stimulus checks; writes the owner's review file")
    sub.add_parser("models", help="free: check slate and judge slugs, list open facts")
    sub.add_parser("balance", help="free: OpenRouter credits (needs the key)")
    p = sub.add_parser("freeze", help="free: freeze the design (needs every prereg item decided)")
    p.add_argument("--note", default=None)
    p.add_argument("--dry", action="store_true", help="only list what blocks a freeze")
    p = sub.add_parser("plan", help="free: measured-cost projection")
    p.add_argument("--only", default=None)
    p.add_argument("--settings", default=None)
    p.add_argument("--runs", type=int, default=None, help="what-if runs per cell")
    p.add_argument("--cross", choices=["full", "trimmed"], default=None)
    for name in ("report", "analyze"):
        p = sub.add_parser(name, help="free: " + ("tables, hypotheses, review.md" if name == "report" else "figures"))
        p.add_argument("--hash", default=None, help="restrict to episodes run under one design hash")
    helps = {"manip": "paid: legality and harm manipulation check", "authority-check": "paid: authority manipulation check",
             "competence": "paid: competence screen", "calibrate": "paid: 1 episode per model in 2 scenarios",
             "run": "paid: the main episodes", "probe": "paid: post-episode evaluation probes",
             "part-d": "paid: recognition probes and process codes", "realism": "paid: pairwise realism vs the sanity test",
             "part-a": "paid: Okamoto bridge (default: Kimi K3 only)"}
    for name, helptext in helps.items():
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--budget", type=float, required=True, help="cap on all Phase 1 spend, cumulative, USD")
        p.add_argument("--yes", action="store_true", help="confirm spending money")
        p.add_argument("--only", default="kimi-k3" if name == "part-a" else None, help="comma-separated tested-model keys")
        if name in ("manip", "authority-check", "calibrate", "run"):
            p.add_argument("--settings", default=None, help="comma-separated scenario keys")
        if name == "calibrate":
            p.add_argument("--runs", type=int, default=None)
            p.add_argument("--cross", choices=["full", "trimmed"], default=None)
        if name == "realism":
            p.add_argument("--sanity-dir", default="out_sanity")
        if name == "part-a":
            p.add_argument("--trials", type=int, default=25)
    return ap


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    setup()
    args = build_parser().parse_args(argv)
    args.cmd_name = args.cmd
    {**FREE, **PAID}[args.cmd](args)
