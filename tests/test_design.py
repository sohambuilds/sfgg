"""The stimulus and preregistration: frozen, minimal pairs, consistent numbers."""
import json
import re

import pilot as P
from scenarios import NEUTRAL_LINE, QUEUE, SCENARIOS, TOOLS

WORDINGS = ("forbidden", "silent", "allowed")
SIZES = ("low", "high")
RUN_RATE = 11480


def test_golden_files_and_hash_reproduce_exactly():
    files = P.design_files()
    for name in P.DESIGN_FILES:
        assert (P.GOLDEN / name).read_bytes() == files[name].encode("utf-8"), name
    assert P.design_hash(files) == P.golden_hash() == P.current_design_hash()


def test_wordings_differ_in_exactly_one_system_line():
    for scn in SCENARIOS:
        for size in SIZES:
            systems = {w: P.render(scn, w, size)[0].splitlines() for w in WORDINGS}
            for a in WORDINGS:
                for b in WORDINGS:
                    if a < b:
                        diff = [i for i, (x, y) in enumerate(zip(systems[a], systems[b])) if x != y]
                        assert len(systems[a]) == len(systems[b]) and len(diff) == 1, (scn, size, a, b)


def test_user_message_does_not_depend_on_wording():
    for scn in SCENARIOS:
        for size in SIZES:
            assert len({P.render(scn, w, size)[1] for w in WORDINGS}) == 1, (scn, size)


def test_low_and_high_differ_only_inside_item_2():
    for scn in SCENARIOS:
        lo = P.render(scn, "silent", "low")[1].split("\n\n")
        hi = P.render(scn, "silent", "high")[1].split("\n\n")
        assert len(lo) == len(hi) == 4
        assert [lo[i] for i in (0, 1, 3)] == [hi[i] for i in (0, 1, 3)]
        assert lo[2] != hi[2] and lo[2].startswith("Item 2") and hi[2].startswith("Item 2")


def _long_words(text):
    return {w for w in re.findall(r"[a-z]+", text.casefold()) if len(w) >= 5}


def test_neutral_line_shares_no_long_word_with_queue_items_or_tools():
    stimulus = QUEUE + json.dumps(TOOLS)
    for scn in SCENARIOS:
        for size in SIZES:
            stimulus += P.render(scn, "silent", size)[1]
    assert not _long_words(NEUTRAL_LINE) & _long_words(stimulus)


def test_gains_match_run_rate_and_scale_with_counts():
    assert "$11,480" in QUEUE
    for scn, s in SCENARIOS.items():
        for size in SIZES:
            z = s["sizes"][size]
            assert round(100 * z["dollars"] / RUN_RATE) == z["pct"], (scn, size)
            assert f"${z['dollars']:,}" in P.render(scn, "silent", size)[1]
        lo, hi = s["sizes"]["low"], s["sizes"]["high"]
        if "count" in lo:
            per_lo, per_hi = lo["dollars"] / lo["count"], hi["dollars"] / hi["count"]
            assert abs(per_lo - per_hi) / per_hi < 0.01, scn


def test_late_claims_timing_is_consistent_at_both_sizes():
    # The switch fails at about five weeks, so every reported claim is past the 30-day window.
    for size in SIZES:
        count = SCENARIOS["late_claims"]["sizes"][size]["count"]
        item = P.render("late_claims", "silent", size)[1]
        assert f"{count} customers have reported" in item and f"all {count} of these arrived after day 30" in item


def test_allowed_lines_mirror_forbidden_as_plain_permissions():
    for scn, s in SCENARIOS.items():
        assert not re.search(r"\bwhen (?:that|they) (?:improves|protect)", s["allowed"]), scn
        assert " may " in f" {s['allowed']} " or s["allowed"].endswith("are allowed."), scn


def test_escalation_keywords_hit_their_item_and_nothing_routine():
    # Items 1 and 3 and a routine note to Dana; the role description in OPERATOR names
    # claims and listings in general, which is not a message about any item.
    routine = [QUEUE.split("{target}")[0], QUEUE.split("{target}")[1], NEUTRAL_LINE,
               "Replied to ticket 5581 about the oat bars. Coordinated with Ohio Vend Service on the "
               "Kiosk 7 coin jam. Will send the weekly summary on Friday."]
    for scn, words in P.ESCALATION_KEYWORDS.items():
        item = P.render(scn, "silent", "high")[1].split("\n\n")[2].casefold()
        assert any(w in item for w in words), scn
        for text in routine:
            hits = [w for w in words if w in text.casefold()]
            assert not hits, (scn, hits)


def test_families_and_gate():
    assert {s["family"] for s in SCENARIOS.values()} == {"harm", "rule_only"}
    assert len(P.gate_settings()) == 6
    assert "location_pricing" not in P.gate_settings()
    assert set(P.CALIBRATION_SCENARIOS) <= set(P.gate_settings())


def test_preregistration_pins_models_and_sampling():
    prereg = json.loads(P.design_files()["preregistration.json"])
    assert prereg["models"] == P.MODELS
    assert all(cfg["reasoning"] for cfg in P.MODELS.values())
    assert "temperature" not in json.dumps(P.MODELS)
    assert prereg["stage2"]["alpha"] == P.STAGE2_ALPHA


def test_no_experiment_cues_in_any_prompt():
    cue = re.compile(r"\b(test|experiment|session|episode|condition|evaluation|simulat\w*|scenario)\b", re.I)
    for scn in SCENARIOS:
        for w in WORDINGS:
            for size in SIZES:
                system, user = P.render(scn, w, size)
                assert not cue.search(system), (scn, w, size)
                # "ad test" and "checkout test" are business A/B tests stated in the original items.
                assert not cue.search(re.sub(r"\b(?:ad|the|last week's ad) test\b|Checkout test", "", user)), (scn, w, size)
