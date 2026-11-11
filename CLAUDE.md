# Notes for AI agents working in this repository

Read `PHASE1_PROJECT_STATUS.md` first, section 0 in particular. It records the owner's decisions and the current
plan. Then read `reports/phase1_case_studies.txt`, `reports/phase1_test_cues.txt` and `SCENARIO_GUIDE.md`.

## Standing rules

- **Paid calls are run only by the project owner.** Never read, print, set or use the API key, and never open
  `.env`. You may run the free commands (`check`, `report`, `analyze`, `plan`, `models`, `pytest`). For paid ones,
  write out the exact command for the owner.
- **Budget.** Phase 1's hard cap is $30, enforced in `phase1/config.py`. Never raise it without the owner's say-so.
- **Commit or push only when asked.**
- **Records are append-only.** Never edit anything in `out/`, `out_sanity/` or `out_phase1/`.
- **Quote only what the records say.** Before a quote goes into any document, check it word for word against
  `out_phase1/`.
- **Claude-family models stay out of the tested slate** while Claude drafts or edits scenarios. Scenario authorship
  must be recorded (`provenance`, `author`). For co-author drafts written with LLM help, also record the drafting
  and checking models, which the drafts state.

## How to work

- **The work is exploratory.** The aim is to find what moves models, not to run a fixed protocol to completion.
  Think like a researcher solving a problem. Question the design, read transcripts before computing rates, and
  suspect the instrument first when a result surprises you. Drop work that won't change a decision.
- **Look at stimuli from the tested model's side before running anything.** Ask what would tell a model it is being
  tested, and fix it first. The cue list is in `reports/phase1_test_cues.txt`.
- **Prefer interventions to interpretations.** What a model writes about its decision is weaker evidence than a
  change in the input that changes its behaviour.
- **Write plainly and neutrally** in reports and docs. Avoid dramatic reveal lines and rhetorical "X, not Y"
  constructions. Say what is a finding and what is a lead.
