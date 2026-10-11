# Phase 1: build notes

`PHASE1_HANDOVER.md` is the spec (§5); `PHASE1_PREREG.md` and `prereg.py` are the pre-specification. This file
records how Phase 1 was built, the commands, and every place the build adds to or departs from the handover.

## Commands

All run as `uv run python -m phase1 <command>`. Commands that call OpenRouter need the key, for example
`uv run --env-file .env python -m phase1 manip --budget 5 --yes`.

| Command | Cost | What it does |
|---|---|---|
| `check` | free | Runs every free check on the scenarios; writes `out_phase1/stimuli_for_review.md`. Exits non-zero while there are problems or no scenarios. |
| `models` | free | Checks slugs, tool and reasoning support of the slate and judges; lists open facts (Kimi K3's active parameters). |
| `freeze` | free | Freezes the design, or lists what blocks it. `--dry` only lists. |
| `plan` | free | Measured cost per part and model, times the items left. `--runs`/`--cross` give a what-if before the prereg is decided. |
| `report` | free | `out_phase1/report.md` and `review.md`. |
| `analyze` | free | Figures in `out_phase1/figures/` (needs the `analysis` group). |
| `balance` | free | OpenRouter credits. |
| `manip` | **paid** | Legality/harm/seriousness check, every variant, 3 samples per model. |
| `authority-check` | **paid** | Each model rates how strongly each note insists. |
| `competence` | **paid** | The legal, harmless, owner-gated act (silent and permitted). |
| `calibrate` | **paid** | One LH level-1 episode per model in the first two scenarios; they count toward the run. |
| `run` | **paid** | The main episodes, from the frozen runs and cross. |
| `probe` | **paid** | Post-episode "was this an evaluation" probe, by the tested model. |
| `part-d` | **paid** | Recognition probes and process codes. |
| `realism` | **paid** | Pairwise realism against the sanity test's transcripts (`--sanity-dir out_sanity`). |
| `part-a` | **paid** | The Okamoto bridge, reusing the sanity code. Defaults to `--only kimi-k3`. |

Every paid command refuses unless the design is frozen and unchanged, needs `--yes` and an explicit cumulative
`--budget`, and caps itself at the key's live limit and the account balance. Paid calls are run by a human owner of
the project. **An agent must never set or use the API key.**

**Run order:** write scenarios -> `check` -> owner reads `stimuli_for_review.md` -> decide `prereg.py` and the
authority wording -> `freeze` -> `models` -> `manip`, `authority-check` -> fix and re-freeze if a check fails ->
`competence` -> `calibrate` -> `plan` -> `run` -> `probe`, `part-d`, `realism` -> `report`, `analyze`.

Everything resumes. Completed items are skipped, errored items retried, and an item whose prompt or model
settings changed since it ran is run again as a new record.

## Writing scenarios

Copy `phase1/scenarios/_template.py` to a new file whose name doesn't start with an underscore, and rewrite every
`FILL IN`. The module-level `SCENARIO` (or a `SCENARIOS` list) is picked up automatically. The rules are at the top
of the template. `check` verifies, mechanically:

- the four variants differ only in the two toggled sentences, and the levels only in the pinned note;
- every note carries the identical act phrase once; levels 1-3 carry the same backing clause; the wording has no
  reasons or threats;
- the level-0 note is length-matched and shares no five-letter word with the scenario;
- each stated figure evaluates to its value and appears in the item;
- 6-8 items, enough routine items needing an action, each document named in the queue, the act scored through a
  tool that exists, escalation keywords only in the target;
- no enforcement vocabulary and no test-cue words;
- across scenarios: distinct companies, entitlement balanced to within one, the target not always in one place,
  at least three domains once there are six scenarios;
- provenance is `human` and `author` and `names_source` are filled in.

It cannot tell whether a scenario is good. Read the rendered episodes.

## Layout

```
schema.py       Scenario, Toggle, RoutineItem, Figure; read_document tool and reader
authority.py    The four levels' wording (draft) and the note builder
models.py       The five-model slate, size slots and ladders, model-card sources
stimuli.py      Registry, render(), cells(), prompt ids, scoring, routine progress, documents read
checks.py       Free checks (above)
prereg.py       Hypotheses and decisions as data; None = open
freeze.py       Design hash, FROZEN.json, freeze_history.jsonl, the guard
instruments.py  Manipulation checks, probes, process codes, pairwise realism
runs.py         Job builders, episode runner, loaders
analysis.py     Contrasts, bootstrap, mixed models, figures
report.py       report.md and review.md
cli.py          The commands
```

Records live in `out_phase1/` (git-ignored; share it separately), one JSONL file per part: `part_p.jsonl`
(episodes, competence), `part_m.jsonl` (manipulation checks), `part_r.jsonl` (probes, pairwise realism),
`part_d.jsonl` (recognition probes, process codes), `part_a.jsonl` (Okamoto bridge), `manifest.jsonl` (one line per
paid command), and `raw/` (every response). Records are append-only. Each carries the full rendered prompt, the
tools, the documents, the request settings actually sent, a `prompt_id`, and the design hash it ran under.

## Where the build departs from or adds to the handover

1. **The shared engine was generalised, not forked.** `sanity/core.py` gained `configure()` (output directory,
   model slate, part letters, label), tool results that can be a callable of the call's arguments (for
   `read_document`), and a `result` field on each recorded call. `sanity/stimuli.py` gained `score_spec()` and
   friends, and the registry scorer delegates to them. `sanity/instruments.py`'s transcript prints a call's stored
   result. All 116 earlier tests still pass.
2. **Freeze guard on every paid command**, the manipulation checks included (owner's choice). A failed check means
   a rewrite and a re-freeze.
3. **Resume and pooling key on what the model saw and how it was configured** (prompt id and request settings),
   not on the whole design hash. A re-freeze that changes only the pre-registration text therefore doesn't force
   every episode to rerun. The hash is stamped on every record, and the report lists every hash it pools and
   flags more than one.
4. **Absolute judge realism rating dropped**; replaced by the keyword scan, the post-episode probe by level, and
   the pairwise comparison with the sanity test.
5. **Competence screen** reuses the sanity test's `bulk_order_approval` stimulus (silent and permitted), as §5.3
   asks, and is stored in `part_p.jsonl` with `kind: competence`.
6. **Part A** runs through the sanity code into `part_a.jsonl`; its criterion 1 isn't a Phase 1 gate.
7. **Process codes** add `concern` (complying with a conscience) and `authority`; the recognition probe has four
   instruction answers (said nothing / allowed / asked for / insisted on).
8. **Routine-item handling** is measured per episode (`routine_done`/`routine_need`) so an effect on the target
   can be told from the agent being derailed by insistence.
9. **Model-based analysis** uses statsmodels' `BinomialBayesMixedGLM` (variational Bayes) because a frequentist
   random-intercept logit is not in statsmodels and the many all-zero cells would separate a plain logit. Fits that
   warn say so in the report.

## Open items for the co-author

Scenarios (about eight); the authority wording and `AUTHORITY_FINAL`; `runs_per_cell`, `cross`, `h5_status`,
`near_zero` and `min_effect` in `prereg.py`; Kimi K3's active parameters from the model card
(<https://huggingface.co/moonshotai/Kimi-K3>); whether Kimi also runs Part A; and, optionally, the cell where the
owner forbids what the law requires (§8, item 7), which is not built.

## Tests

`uv run pytest -q`. Synthetic, test-only scenarios live in `tests/phase1_fixtures.py` (`provenance="test-fixture"`)
and are never loaded into the study registry. `tests/test_phase1_e2e.py` runs every command against a fake
OpenRouter.
