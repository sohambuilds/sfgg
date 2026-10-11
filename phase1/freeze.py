"""Freezing the Phase 1 design (PHASE1_HANDOVER.md §5.4, "Pre-specification").

The design hash covers everything that decides what a paid call sends or how it is read: the pre-specification
values and PHASE1_PREREG.md, every rendered prompt of every cell, the authority wording, the model slate, the
request settings and the judges. Every paid command refuses to run unless the live hash equals FROZEN.json,
and every record is stamped with it. Records under different hashes are never pooled silently.
"""
import hashlib
import json
import time
from pathlib import Path

import pilot
from phase1 import authority, checks, models, prereg, stimuli
from phase1.schema import VARIANTS
from sanity import core

HERE = Path(__file__).resolve().parent
FROZEN_PATH = HERE / "FROZEN.json"
HISTORY_PATH = HERE / "freeze_history.jsonl"
PREREG_MD = HERE.parent / "PHASE1_PREREG.md"


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def design():
    """The canonical description of the design, as plain data."""
    md = PREREG_MD.read_text(encoding="utf-8") if PREREG_MD.exists() else ""
    cells = {stimuli.cell_id(k, v, l): stimuli.current_prompt_id(k, v, l)
             for k in sorted(stimuli.SCENARIOS) for v in VARIANTS for l in authority.LEVELS}
    competence = {st: sanity_current(st) for st in stimuli.COMPETENCE_STANCES}
    return {
        "prereg": prereg.as_dict(), "prereg_md_sha256": _sha(md),
        "authority": {"insistence": authority.INSISTENCE, "backing": authority.BACKING, "day": authority.NOTE_DAY,
                      "final": authority.AUTHORITY_FINAL},
        "models": {m.key: {"slug": m.slug, "reasoning": m.reasoning, "ladder": m.ladder, "rank": m.rank,
                           "active_params": m.active_params} for m in models.SLATE},
        "settings": {"max_tokens": pilot.MAX_TOKENS, "max_turns": pilot.MAX_TURNS,
                     "require_parameters": pilot.REQUIRE_PARAMETERS, "judge_extra": core.JUDGE_EXTRA,
                     "judges": {k: v["slug"] for k, v in core.JUDGES.items()}},
        "cells": cells, "competence": competence,
    }


def sanity_current(stance):
    from sanity import stimuli as sanity_stimuli
    return sanity_stimuli.current_prompt_id(stimuli.COMPETENCE_SETTING, stance)


def design_hash():
    return _sha(json.dumps(design(), sort_keys=True, ensure_ascii=False, default=str))


def blockers():
    """Reasons the design can't be frozen yet."""
    out = []
    for k, v in checks.all_problems().items():
        out += [f"{k}: {p}" for p in v]
    out += [f"undecided in prereg.py: {k}" for k in prereg.undecided()]
    if prereg.DECISIONS["cross"] not in (None, "full", "trimmed"):
        out.append("prereg cross must be 'full' or 'trimmed'")
    if prereg.DECISIONS["h5_status"] not in (None, "confirmatory", "exploratory"):
        out.append("prereg h5_status must be 'confirmatory' or 'exploratory'")
    if not authority.AUTHORITY_FINAL:
        out.append("authority wording is still the draft (set authority.AUTHORITY_FINAL after sign-off)")
    if not PREREG_MD.exists():
        out.append("PHASE1_PREREG.md is missing")
    return out


def freeze(note=""):
    """Write FROZEN.json and a history line, or raise SystemExit listing what blocks it."""
    problems = blockers()
    if problems:
        raise SystemExit("Cannot freeze yet:\n  " + "\n  ".join(problems))
    h = design_hash()
    entry = {"hash": h, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "note": note,
             "scenarios": sorted(stimuli.SCENARIOS), "n_cells": len(stimuli.SCENARIOS) * len(VARIANTS) * len(authority.LEVELS)}
    FROZEN_PATH.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def frozen_hash():
    if not FROZEN_PATH.exists():
        return None
    return json.loads(FROZEN_PATH.read_text(encoding="utf-8")).get("hash")


def guard():
    """The hash to stamp on records, or SystemExit if the design isn't frozen or has drifted since."""
    frozen = frozen_hash()
    if frozen is None:
        raise SystemExit("The Phase 1 design is not frozen. Run `python -m phase1 freeze` first (it lists what is "
                         "still open). Paid commands need a frozen design.")
    live = design_hash()
    if live != frozen:
        raise SystemExit(f"The design has changed since it was frozen (frozen {frozen[:12]}, now {live[:12]}). "
                         "Re-run `python -m phase1 freeze` after an owner-approved change; earlier records stay "
                         "under their own hash.")
    return live
