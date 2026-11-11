# Rule-price pilot

Do LLM agents doing routine work for a business hold back from illegal acts, and from legal acts that harm a specific
person? How does that change when the owner permits or insists? This repository holds the experiments, from the first
pilot to Phase 1, which is also the team's minor project.

**Start with `PHASE1_PROJECT_STATUS.md`.** It says where the project stands, what was decided, and what comes next.

## Where things are

| Path | What it is |
|---|---|
| `PHASE1_PROJECT_STATUS.md` | Status, decisions, findings, open work, plan for the full study |
| `SCENARIO_GUIDE.md` | How co-authors write new scenarios (with a draft template) |
| `scenario_drafts/` | Where scenario drafts go |
| `phase1/` | The Phase 1 harness; `phase1/README.md` explains commands and design |
| `reports/phase1_case_studies.txt` | What each model did in each scenario, with verified quotes |
| `reports/phase1_test_cues.txt` | What tells a model it is being tested |
| `reports/phase1_as_run.html` | The Phase 1 setup as run, and every result, in plain language |
| `reports/main.tex`, `reports/fig/` | The minor-project report (KIIT format) and its figures |
| `pilot.py`, `scenarios.py`, `golden/` | The first pilot (finished; `phase1` imports its model table) |
| `sanity/` | The sanity test (finished; `phase1` is built on its engine) |
| `tests/` | `uv run pytest -q`, free |

Results live in `out/` (pilot), `out_sanity/` and `out_phase1/`. All three are git-ignored, append-only, and exist
only on the owner's machine, so back them up.

## Costs and keys

Free commands (`check`, `report`, `analyze`, `plan`, `models`) can be run by anyone. Paid commands call OpenRouter and
are run only by the project owner, with the key in a git-ignored `.env`:

```
uv run --env-file .env python -m phase1 <command> --budget <cumulative cap> --yes
```

Phase 1's cap is $30 (`phase1/config.py`). Spend so far is $23.20, and the credit ran out on 9 November 2026.

Documents for the pilot and the sanity test (`HANDOFF.md`, `RESEARCH.md`, `SANITY_TEST.md`, `PHASE1_HANDOVER.md`,
`PHASE1_PREREG.md`) were removed on 10 November 2026. They are in git history (`git show 1c4a2ad:<file>`).
