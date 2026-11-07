"""Phase 1 report: where act rates moved, what kind of break each was, and review.md. Free; reads out_phase1/ only."""
import random
import re
import statistics
from collections import Counter, defaultdict

from phase1 import analysis, authority, instruments, models, runs, stimuli
from sanity import core
from sanity import instruments as si
from sanity.report import Out, pct, wilson


def latest(recs):
    return list({r["id"]: r for r in recs}.values())


def fmt_ci(point, lo, hi, points=True):
    if point is None:
        return "-"
    f = (lambda x: f"{100 * x:+.0f}") if points else (lambda x: f"{100 * x:.0f}%")
    return f"{f(point)} [{f(lo)}, {f(hi)}]" if lo is not None else f(point)


# ---------------------------------------------------------------- the neutral question

def neutral_checks():
    return latest(r for r in core.load("M") if r.get("kind") == "check" and not r.get("error") and runs.c_is_current(r))


def part_neutral(out, recs):
    out("## Neutral question (same documents, no role, no note, no tools)")
    if not recs:
        out("Not run yet.\n")
        return []
    answers = analysis.neutral_answers(recs)
    ms = models.order({r["model"] for r in recs})
    out("Each model's majority answer over its samples (legal/harm). A ✗ means it differs from what the scenario "
        "intends: either the scenario needs rewriting, or the model can't read the rule even when asked directly.\n")
    out("| scenario | variant | intended | " + " | ".join(ms) + " | seriousness |")
    out("|---|---|---|" + "---|" * len(ms) + "---|")
    mismatches = []
    for key, variant in sorted({(r["scenario"], r["variant"]) for r in recs}):
        v = stimuli.SCENARIOS[key].variant(variant)
        cells, sers = [], []
        for m in ms:
            a = answers.get((m, key, variant))
            if not a:
                cells.append("-")
                continue
            ok = a["legal"] == ("legal" if v.legal else "illegal") and a["harm"] == ("yes" if v.harmful else "no")
            cells.append(f"{a['legal']}/{a['harm']}" + ("" if ok else " ✗"))
            if a["seriousness"] is not None:
                sers.append(a["seriousness"])
            if not ok:
                mismatches += [r for r in recs if (r["model"], r["scenario"], r["variant"]) == (m, key, variant)]
        out(f"| {key} | {variant} | {'legal' if v.legal else 'illegal'}/{'yes' if v.harmful else 'no'} | " + " | ".join(cells)
            + f" | {statistics.mean(sers):.1f} |" if sers else
            f"| {key} | {variant} | {'legal' if v.legal else 'illegal'}/{'yes' if v.harmful else 'no'} | " + " | ".join(cells) + " | - |")
    arecs = latest(r for r in core.load("M") if r.get("kind") == "authority" and not r.get("error") and runs.c_is_current(r))
    if arecs:
        out("\nHow strongly each note insists (0-10), mean over scenarios:\n")
        out("| model | " + " | ".join(f"L{l} {authority.NAMES[l]}" for l in authority.LEVELS) + " |")
        out("|---|" + "---|" * len(authority.LEVELS))
        for m in models.order({r["model"] for r in arecs}):
            row = []
            for l in authority.LEVELS:
                xs = [r["insistence"] for r in arecs if r["model"] == m and r["level"] == l and r["insistence"] is not None]
                row.append(f"{statistics.mean(xs):.1f}" if xs else "-")
            out(f"| {m} | " + " | ".join(row) + " |")
    out("")
    return mismatches


# ---------------------------------------------------------------- competence

def competence(out):
    out("## Competence screen (legal, harmless, owner-gated act: the sanity test's bulk order)")
    cs = runs.competence_episodes()
    if not cs:
        out("Not run yet.\n")
        return
    out("A model that won't carry out a permitted harmless act can't have its refusals interpreted.\n")
    out("| model | silent: acts/runs | permitted: acts/runs |")
    out("|---|---|---|")
    for m in models.order({e["model"] for e in cs}):
        a = analysis.cell_rate([e for e in cs if e["model"] == m], stance="silent")
        b = analysis.cell_rate([e for e in cs if e["model"] == m], stance="permitted")
        out(f"| {m} | {a[0]}/{a[1]} | {b[0]}/{b[1]} |")
    out("")


# ---------------------------------------------------------------- the grids

def grid(out, eps, track, title):
    sub = [e for e in eps if e["track"] == track]
    out(f"## {title}")
    if not sub:
        out("No episodes yet.\n")
        return
    levels = sorted({e["level"] for e in sub})
    out("Cells show acts/runs on the target record, then held (h), escalated (e) and no action (x) where non-zero.\n")
    for m in models.order({e["model"] for e in sub}):
        out(f"\n**{m}** ({models.BY_KEY[m].slot})\n")
        out("| scenario | variant | " + " | ".join(f"L{l} {authority.NAMES[l]}" for l in levels) + " |")
        out("|---|---|" + "---|" * len(levels))
        for key in sorted({e["scenario"] for e in sub if e["model"] == m}):
            for v in stimuli.SCENARIOS[key].variants:
                row = []
                for l in levels:
                    rs = [e for e in sub if e["model"] == m and e["scenario"] == key and e["variant"] == v.name and e["level"] == l]
                    if not rs:
                        row.append("-")
                        continue
                    c = Counter(e["outcome"] for e in rs)
                    row.append(f"{c['violation']}/{len(rs)}" + (f" {c['held']}h" if c["held"] else "")
                               + (f" {c['escalated']}e" if c["escalated"] else "") + (f" {c['no_action']}x" if c["no_action"] else ""))
                if any(x != "-" for x in row):
                    out(f"| {key} | {v.name} | " + " | ".join(row) + " |")
    out("")


def contrasts(out, eps):
    out("## Pooled act rates and contrasts")
    out("Pooled over scenarios, per model. Differences are in points. Brackets are scenario-bootstrap 95% intervals, "
        f"{analysis.BOOTSTRAP_DRAWS} draws; with this few scenarios they are rough.\n")
    for track, title in (("illegal", "Illegal but harmless"), ("harm", "Legal but harmful")):
        cons = analysis.contrasts(eps, track)
        if not cons:
            continue
        names = list(analysis.STATS[track])
        out(f"**{title}**\n")
        out("| model | " + " | ".join(names) + " |")
        out("|---|" + "---|" * len(names))
        for m, row in cons.items():
            out(f"| {m} | " + " | ".join(fmt_ci(*row[n], points=" - " in n) for n in names) + " |")
        out("")


def process_codes():
    recs = latest(r for r in core.load("D") if r.get("kind") == "process" and not r.get("error"))
    by_ep = defaultdict(dict)
    for r in recs:
        by_ep[r["episode"]][r["model"]] = r.get("codes") or {}
    return by_ep


def breaks(out, eps, checks, codes):
    out("## What kind of break was each act?")
    acts = [e for e in eps if analysis.is_act(e) and (e["harm"] or not e["legal"])]
    if not acts:
        out("No acts yet.\n")
        return
    out("From the record: did it open the documents that show the issue, and did the judge find it showing it saw the "
        "issue? 'Right when asked' is the same model answering the neutral question correctly: a break by a model that "
        "was right when asked is the most interesting kind.\n")
    answers = analysis.neutral_answers(checks)
    out("| model | track | acts | " + " | ".join(analysis.BREAK_KINDS) + " | right when asked |")
    out("|---|---|---|" + "---|" * len(analysis.BREAK_KINDS) + "---|")
    for m in models.order({e["model"] for e in acts}):
        for track in ("illegal", "harm"):
            rs = [e for e in acts if e["model"] == m and e["track"] == track]
            if not rs:
                continue
            kinds = Counter(analysis.break_kind(e, codes.get(e["id"], {}).get(core.PRIMARY_JUDGE)) for e in rs)
            right = [analysis.right_when_asked(e, answers.get((m, e["scenario"], instruments.neutral_variant_of(e["scenario"], e["variant"])))) for e in rs]
            known = [x for x in right if x is not None]
            out(f"| {m} | {track} | {len(rs)} | " + " | ".join(str(kinds[k]) for k in analysis.BREAK_KINDS)
                + f" | {f'{sum(known)}/{len(known)}' if known else 'not run'} |")
    out("")


def batch_handling(out, eps):
    out("## How the batch went")
    out("Controls are ordinary records. Decoys look like the target but are fine, so leaving them out is over-refusal. "
        "'Told owner' is any message to the owner about the job. Routine is the other queue items.\n")
    out("| model | track | variant | controls done | decoys done | key documents opened | told owner | routine done |")
    out("|---|---|---|---|---|---|---|---|")
    groups = defaultdict(list)
    for e in eps:
        groups[(e["model"], e["track"], e["variant"])].append(e)
    for (m, track, v), rs in sorted(groups.items(), key=lambda kv: (models.order([kv[0][0]]), kv[0][1], kv[0][2])):
        cn, dn, rn = sum(e["controls_n"] for e in rs), sum(e["decoys_n"] for e in rs), sum(e["routine_need"] for e in rs)
        out(f"| {m} | {track} | {v} | {pct(sum(e['controls_done'] for e in rs) / cn) if cn else '-'} | "
            f"{pct(sum(e['decoys_done'] for e in rs) / dn) if dn else '-'} | "
            f"{pct(sum(bool(e['key_docs_opened']) for e in rs) / len(rs))} | {pct(sum(bool(e['told_owner']) for e in rs) / len(rs))} | "
            f"{pct(sum(e['routine_done'] for e in rs) / rn) if rn else '-'} |")
    out("")


def authorship(out, eps):
    labels = sorted({e["provenance"] for e in eps})
    out("## Who wrote the scenario")
    out("Act rate by track, model and authorship, on the variants with nothing spotlighted. Claude drafted the "
        "`ai-draft` scenarios; `human` scenarios were written by other authors.\n")
    out("| model | track | " + " | ".join(labels) + " |")
    out("|---|---|" + "---|" * len(labels))
    for m in models.order({e["model"] for e in eps}):
        for track, variant in (("illegal", "hard"), ("harm", "embedded")):
            cells = [analysis.cell_rate(eps, model=m, track=track, variant=variant, provenance=p) for p in labels]
            if any(n for _, n in cells):
                out(f"| {m} | {track} | " + " | ".join(f"{k}/{n}" if n else "-" for k, n in cells) + " |")
    out("")


# ---------------------------------------------------------------- instruments

def suspicion(out, eps, codes):
    out("## Test suspicion and realism")
    by_ep = {e["id"]: e for e in eps}
    recs = latest(r for r in core.load("R") if not r.get("error"))
    probes = [r for r in recs if r["kind"] == "eval_probe" and r["episode"] in by_ep]
    out("Keyword scan of what the agent wrote, and the post-episode probe (the agent's own model, fresh context: share "
        "saying test, mean stated probability). The keyword scan only sees what a model chooses to show.\n")
    out("| model | episodes | keyword flagged | reasoning returned | probes | says 'test' | mean p(test) |")
    out("|---|---|---|---|---|---|---|")
    for m in models.order({e["model"] for e in eps}):
        rs = [e for e in eps if e["model"] == m]
        ps = [p for p in probes if p["model"] == m]
        pt = [p["p_test"] for p in ps if p["p_test"] is not None]
        out(f"| {m} | {len(rs)} | {pct(sum(1 for e in rs if e.get('eval_aware')) / len(rs))} | "
            f"{pct(sum(1 for e in rs if e.get('reasoning_chars')) / len(rs))} | {len(ps)} | "
            f"{pct(sum(p['verdict'] == 'test' for p in ps) / len(ps)) if ps else '-'} | {f'{statistics.mean(pt):.0f}' if pt else '-'} |")
    pairs = [r for r in recs if r["kind"] == "pair" and r.get("phase1_won") is not None and r["model"] == core.PRIMARY_JUDGE]
    if pairs:
        k = sum(r["phase1_won"] for r in pairs)
        lo, hi = wilson(k, len(pairs))
        first = [r for r in pairs if r["phase1_first"]]
        out(f"\nPairwise realism (primary judge, both orders): the Phase 1 record was judged more real in {k}/{len(pairs)} "
            f"comparisons ({pct(k / len(pairs))}, 95% CI {pct(lo)} to {pct(hi)}). Phase 1 shown first: "
            f"{sum(r['phase1_won'] for r in first)}/{len(first)}; shown second: "
            f"{sum(r['phase1_won'] for r in pairs if not r['phase1_first'])}/{len(pairs) - len(first)}. 50% means no "
            "improvement on the sanity test.")
    coded = [v[core.PRIMARY_JUDGE] for k, v in codes.items() if k in by_ep and core.PRIMARY_JUDGE in v]
    if coded:
        acts = [v[core.PRIMARY_JUDGE] for k, v in codes.items() if k in by_ep and core.PRIMARY_JUDGE in v and analysis.is_act(by_ep[k])]
        out("\nProcess codes (primary judge reading the reasoning), share of coded acts: "
            + ", ".join(f"{c} {pct(sum(1 for x in acts if x.get(c)) / len(acts))}" for c in instruments.PROCESS_CODES)
            + f" ({len(acts)} acts)." if acts else "\nNo acts coded yet.")
        both = [(v[core.PRIMARY_JUDGE], v[core.SECOND_JUDGE]) for v in codes.values() if core.PRIMARY_JUDGE in v and core.SECOND_JUDGE in v]
        if both:
            out("Agreement between judges on the sample: " + ", ".join(
                f"{c} {sum(a.get(c) == b.get(c) for a, b in both)}/{len(both)}" for c in instruments.PROCESS_CODES))
    out("")


def overview(out, eps):
    out("## Episodes: outcome mix, flags, errors, cost and rounds")
    allp = [r for r in core.load("P") if r.get("kind") == "episode"]
    for m in models.order({e["model"] for e in eps}):
        rs = [e for e in eps if e["model"] == m]
        mix = Counter(e["outcome"] for e in rs)
        errs = {r["id"] for r in allp if r["model"] == m and r.get("error")} - {e["id"] for e in rs}
        costs = [e["cost"] for e in rs if e.get("cost") is not None]
        out(f"- {m}: {len(rs)} episodes {dict(mix)}; flagged {sum(1 for e in rs if e.get('flags'))}; unresolved errors "
            f"{len(errs)}; mean cost {f'${statistics.mean(costs):.4f}' if costs else 'n/a'}")
    stale = sum(1 for r in allp if not r.get("error") and not runs.is_current_episode(r))
    relabelled = sum(1 for e in eps if e["outcome"] != e.get("stored_outcome"))
    out(f"\nEpisodes on earlier text or settings left out: {stale} (still in part_p.jsonl). Outcomes recomputed from "
        f"stored tool calls; {relabelled} differ from the label stored at run time.")
    versions = Counter(e.get("design_version") or "unstamped" for e in eps)
    out("Design versions among these episodes: " + (", ".join(f"{k} ({v})" for k, v in versions.most_common()) or "none")
        + f". Now: {runs.design_version()}.")
    out(f"Phase 1 spend recorded: ${core.spent():.2f}.\n")


# ---------------------------------------------------------------- review file

def review(eps, mismatches, codes):
    """Read every break by a model other than the control, then a sample of the rest."""
    rng = random.Random(0)
    lines = ["# Phase 1 review file", "",
             "Every act on a target record by a model other than the control, then samples. Read these before the rates.", ""]
    acts = sorted((e for e in eps if analysis.is_act(e) and (e["harm"] or not e["legal"])), key=lambda e: e["id"])
    main = [e for e in acts if e["model"] != models.CONTROL]
    control = [e for e in acts if e["model"] == models.CONTROL]
    lines.append(f"## Breaks ({len(main)}, control model left out)")
    for e in main:
        c = codes.get(e["id"], {}).get(core.PRIMARY_JUDGE)
        lines += [f"\n### `{e['id']}` {analysis.break_kind(e, c)}", f"Documents opened: {e['documents_read']}",
                  "```", si.transcript(e)[-7000:], "```"]
        if e.get("reasoning"):
            lines.append("Reasoning:\n\n> " + "\n".join(e["reasoning"])[:3000].replace("\n", "\n> ") + "\n")
    lines.append(f"\n## Control model: five of its {len(control)} breaks")
    for e in rng.sample(control, min(5, len(control))):
        lines += [f"\n### `{e['id']}`", "```", si.transcript(e)[-5000:], "```"]
    lines.append("\n## Suspicion hits (keyword scan)")
    for e in eps:
        if e.get("eval_aware"):
            blob = "\n".join((e.get("text") or []) + (e.get("reasoning") or []))
            m = re.search(r"(?i)(test|evaluat|simulat|role-?play|hypothetical)", blob)
            snip = blob[max(0, m.start() - 300): m.end() + 300].replace("\n", " ") if m else ""
            lines.append(f"- `{e['id']}` outcome={e['outcome']}: ...{snip}...")
    lines.append("\n## Neutral-question mismatches")
    for r in mismatches:
        a = r["answer"]
        lines.append(f"- `{r['id']}` legal={a['legal']} harm={a['harm']} seriousness={a['seriousness']}: "
                     f"{a.get('legal_reason')} | harmed: {a.get('harmed')}")
    lines.append("\n## Three held records per model and track")
    for m in models.order({e["model"] for e in eps}):
        for track in ("illegal", "harm"):
            rs = sorted((e for e in eps if e["model"] == m and e["track"] == track and not analysis.is_act(e)), key=lambda e: e["id"])
            for e in rng.sample(rs, min(3, len(rs))):
                lines += [f"\n### `{e['id']}` outcome={e['outcome']}", "```", si.transcript(e)[-5000:], "```"]
    return "\n".join(lines) + "\n"


def build():
    out = Out()
    out("# Phase 1 report\n")
    out("Exploratory: we change the setup between rounds to find where models take illegal or harmful actions. Nothing "
        "here is pre-registered, and every result is a lead to follow, not a confirmed effect.\n")
    eps = runs.episodes()
    checks = neutral_checks()
    codes = process_codes()
    mismatches = part_neutral(out, checks)
    competence(out)
    if eps:
        grid(out, eps, "illegal", "Illegal but harmless: act on the target record")
        grid(out, eps, "harm", "Legal but harmful: act on the target record")
        contrasts(out, eps)
        breaks(out, eps, checks, codes)
        batch_handling(out, eps)
        authorship(out, eps)
        suspicion(out, eps, codes)
        overview(out, eps)
    else:
        out("No Phase 1 episodes yet.\n")
    return out.text(), review(eps, mismatches, codes)
