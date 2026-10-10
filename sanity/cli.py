"""Sanity test commands.

Free:  check, models, plan, report
Paid:  part-c, part-a, calibrate, part-b, part-d   (each needs --yes and an explicit --budget, the
       cap on all sanity-test spend so far plus this command)

Order: check -> owner reviews out_sanity/stimuli_for_review.md -> part-c -> part-a -> calibrate -> plan
       -> part-b -> part-d -> report
"""
import argparse
import statistics
import sys

import pilot
from sanity import checks, core, okamoto, report, runs, stimuli
from sanity.schema import POLICY_STANCE, STANCES, note


def selected(args):
    keys = [k.strip() for k in args.only.split(",")] if getattr(args, "only", None) else list(core.MODELS)
    bad = [k for k in keys if k not in core.MODELS]
    if bad:
        sys.exit(f"Unknown model keys: {bad}. Known: {list(core.MODELS)}")
    return keys


def selected_settings(args):
    fam = getattr(args, "family", "all")
    keys = {"B": stimuli.PART_B, "E": stimuli.PART_E, "all": stimuli.PART_B + stimuli.PART_E}[fam]
    if getattr(args, "settings", None):
        keys = [k.strip() for k in args.settings.split(",")]
        bad = [k for k in keys if k not in stimuli.SETTINGS]
        if bad:
            sys.exit(f"Unknown settings: {bad}")
    return keys


def cmd_check(args):
    problems = checks.all_problems()
    for k, v in problems.items():
        print(f"PROBLEM {k}")
        for x in v:
            print(f"   {x}")
    for h in checks.enforcement_hits():
        if h["reviewed"]:
            print(f"reviewed enforcement word: {h['setting']}/{h['stance']} '{h['word']}' ({h['reviewed']})")
    n_b = sum(len(stimuli.stances(k)) for k in stimuli.PART_B)
    n_e = sum(len(stimuli.stances(k)) for k in stimuli.PART_E)
    print(f"{len(stimuli.PART_B)} Part B settings ({n_b} setting-stance cells), {len(stimuli.PART_E)} Part E settings "
          f"({n_e} cells), {len(okamoto.CELLS)} Part A cells.")
    core.OUT.mkdir(exist_ok=True)
    lines = ["# Stimuli for review", "", "Every new setting's item, its three pinned notes, and one full rendered "
             "episode per business. Read for realism, internal consistency, legal accuracy and anything that "
             "looks like a test.", ""]
    for key, s in stimuli.SETTINGS.items():
        b = stimuli.BUSINESSES[s.business]
        lines += [f"## {key} (Part {s.part}, {s.cell}: intended {'legal' if s.legal else 'illegal'}, "
                  f"{'harmful' if s.harm else 'no identifiable victim'})", "", s.target, ""]
        for st in STANCES:
            lines += [f"- **{st}:** {note(b.owner, s, st)}"]
        if s.policy_allowed:
            lines += [f"- **{POLICY_STANCE}:** policy 3 reads \"{s.policy_allowed}\" and there is no pinned note"]
        lines += ["", f"Part C question: {s.check_facts} Is it legal for {s.check_actor} to {s.check_act}?", ""]
    seen = set()
    for key, s in stimuli.SETTINGS.items():
        if s.business in seen:
            continue
        seen.add(s.business)
        r = stimuli.render(key, "permitted")
        lines += [f"## Full episode: {s.business} ({key}, permitted)", "", "```", r["system"], "", r["user"], "```",
                  "", "Tools: " + ", ".join(t["function"]["name"] for t in r["tools"]), ""]
    lines += ["## Part A: info_manager, trial 0", "", "```", okamoto.system_prompt("info_manager"), "",
              okamoto.user_message("info_manager", 0), "```", ""]
    path = core.OUT / "stimuli_for_review.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {path} for the owner's review.")
    print("Checks clean." if not problems else f"{len(problems)} groups of problems.")
    if problems:
        sys.exit(1)


def cmd_models(args):
    requests = pilot.http()
    r = requests.get(f"{pilot.API}/models", timeout=60)
    r.raise_for_status()
    by_id = {m["id"]: m for m in r.json().get("data", [])}
    for k, cfg in {**core.MODELS, **core.JUDGES}.items():
        m = by_id.get(cfg["slug"])
        role = "judge" if k in core.JUDGES else "tested"
        if not m:
            print(f"MISSING {role} {k}: {cfg['slug']}")
            continue
        params = m.get("supported_parameters") or []
        need = ["reasoning"] if cfg.get("reasoning") else []
        need += ["temperature"] if k in core.JUDGES else []
        missing = [p for p in need if p not in params]
        print(f"ok  {role:<6} {k:<20} {cfg['slug']:<34} tools={'yes' if 'tools' in params else 'no'}"
              + (f"  MISSING PARAMS {missing}" if missing else ""))


def _paid(args, what, jobs):
    if not jobs:
        print(f"{what}: nothing left to run.")
        return
    cap = core.confirm_paid(args, what, jobs)
    before = pilot.credits()
    finished, capped = core.run_jobs(jobs, cap)
    core.summarize_run(finished, capped)
    after = pilot.credits()
    if before and after and before[1] is not None and after[1] is not None:
        print(f"OpenRouter usage rose by ${after[1] - before[1]:.4f} during this command.")


def cmd_part_c(args):
    _paid(args, "Part C (manipulation check)", runs.part_c_jobs(selected(args), selected_settings(args), args.samples))


def cmd_part_a(args):
    _paid(args, "Part A (Okamoto bridge)", runs.part_a_jobs(selected(args), args.trials))
    jobs = runs.part_a_judge_jobs()
    if jobs:
        print("Judging replies that don't name exactly one vendor, and the second-judge sample:")
        _paid(args, "Part A judging", jobs)


def cmd_calibrate(args):
    _paid(args, "Calibration (1 silent episode per model in supplier_cancellation and pet_claim_lapse; "
                "they count toward Parts B and E)", runs.calibration_jobs(selected(args)))
    cmd_plan(args)


def cmd_part_b(args):
    stances = tuple(s.strip() for s in args.stances.split(",")) if args.stances else None
    _paid(args, f"Parts B/E episodes ({args.family})",
          runs.part_b_jobs(selected(args), selected_settings(args), args.runs, stances))


def cmd_part_d(args):
    _paid(args, "Part D (suspicion ratings, recognition probes, process codes)", runs.part_d_jobs())


def cmd_plan(args):
    costs = core.measured()
    models = selected(args)
    plans = {
        "C": runs.part_c_jobs(models, stimuli.PART_B + stimuli.PART_E, 3),
        "A": runs.part_a_jobs(models, 25),
        "B": runs.part_b_jobs(models, stimuli.PART_B + stimuli.PART_E, 5),
        "D": runs.part_d_jobs(),
    }
    print(f"Sanity-test spend so far: ${core.spent():.2f}. Projections use measured costs per part and model only.")
    total = 0.0
    for part, jobs in plans.items():
        by = {}
        for j in jobs:
            by.setdefault(j["model"], 0)
            by[j["model"]] += 1
        for m, n in sorted(by.items()):
            c = costs.get((part, m))
            if c:
                total += n * statistics.mean(c)
                print(f"  part {part}  {m:<20} {n:>4} left  mean ${statistics.mean(c):.4f}  -> ${n * statistics.mean(c):.2f}")
            else:
                print(f"  part {part}  {m:<20} {n:>4} left  no measured cost yet")
    print(f"Measured projection for what is left: ${total:.2f} (parts without measured costs not included). "
          "Part D's size depends on Part B's results.")


def cmd_report(args):
    text, review_text = report.build()
    core.OUT.mkdir(exist_ok=True)
    (core.OUT / "report.md").write_text(text, encoding="utf-8")
    (core.OUT / "review.md").write_text(review_text, encoding="utf-8")
    print(text)
    print(f"Wrote {core.OUT / 'report.md'} and {core.OUT / 'review.md'}.")


def cmd_balance(args):
    pilot.cmd_balance(args)


def main():
    # Reports contain non-ASCII marks; Windows terminals and pipes may not default to UTF-8.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m sanity", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="free: stimulus checks; writes the owner's review file")
    sub.add_parser("models", help="free: check tested-model and judge slugs")
    sub.add_parser("report", help="free: tables, pass criteria, review.md")
    sub.add_parser("balance", help="free: OpenRouter credits (needs the key)")
    p = sub.add_parser("plan", help="free: measured-cost projection")
    p.add_argument("--only", default=None)
    for name, helptext in (("part-c", "paid: manipulation check"), ("part-a", "paid: Okamoto bridge"),
                           ("calibrate", "paid: 2 episodes per model"), ("part-b", "paid: Parts B and E episodes"),
                           ("part-d", "paid: judge instruments and recognition probes")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--budget", type=float, required=True, help="cap on all sanity-test spend, cumulative, USD")
        p.add_argument("--yes", action="store_true", help="confirm spending money")
        p.add_argument("--only", default=None, help="comma-separated tested-model keys")
        if name == "part-c":
            p.add_argument("--samples", type=int, default=3)
            p.add_argument("--family", choices=["B", "E", "all"], default="all")
            p.add_argument("--settings", default=None)
        if name == "part-a":
            p.add_argument("--trials", type=int, default=25)
        if name == "part-b":
            p.add_argument("--runs", type=int, default=5)
            p.add_argument("--family", choices=["B", "E", "all"], default="all")
            p.add_argument("--settings", default=None)
            p.add_argument("--stances", default=None, help="comma-separated, e.g. silent,permitted")
    args = ap.parse_args()
    {"check": cmd_check, "models": cmd_models, "report": cmd_report, "balance": cmd_balance, "plan": cmd_plan,
     "part-c": cmd_part_c, "part-a": cmd_part_a, "calibrate": cmd_calibrate, "part-b": cmd_part_b,
     "part-d": cmd_part_d}[args.cmd](args)
