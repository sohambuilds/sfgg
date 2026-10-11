"""Registry, rendering, cells and scoring for Phase 1 scenarios."""
import hashlib
import importlib
import json
import pkgutil
from collections import Counter

from phase1 import authority
from phase1.schema import VARIANTS, document_reader, variant_flags
from sanity import stimuli as sanity_stimuli

COMPETENCE_SETTING = "bulk_order_approval"          # the sanity test's legal, harmless, owner-gated act
COMPETENCE_STANCES = ("silent", "permitted")
READ_DOCUMENT_STATIC = "(the stored text of the document, or a plain miss)"


def load_scenarios():
    """Every module in phase1/scenarios whose name doesn't start with an underscore, via its SCENARIO(S)."""
    from phase1 import scenarios
    found = {}
    for info in pkgutil.iter_modules(scenarios.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"phase1.scenarios.{info.name}")
        items = getattr(mod, "SCENARIOS", None) or [mod.SCENARIO]
        for s in items:
            if s.key in found:
                raise ValueError(f"duplicate scenario key {s.key}")
            found[s.key] = s
    return found


SCENARIOS = load_scenarios()


def fill(template, legality, harm):
    return template.replace("{legality}", legality).replace("{harm}", harm)


def target_text(s, variant):
    legal, harmful = variant_flags(variant)
    return fill(s.target, s.legality.on if legal else s.legality.off, s.harm.on if harmful else s.harm.off)


def items_text(s, target):
    items = [i.text for i in s.routine_before] + [target] + [i.text for i in s.routine_after]
    return "\n\n".join(f"Item {n} - {t}" for n, t in enumerate(items, 1))


def render(key, variant, level):
    """The full stimulus: system, user, tools, documents, and tool results (read_document is a callable)."""
    s = SCENARIOS[key]
    system = s.system + "\n\nPinned notes:\n" + authority.note(s.owner, s, level)
    user = s.header + "\n\n" + items_text(s, target_text(s, variant))
    return {"system": system, "user": user, "tools": list(s.tools), "documents": dict(s.documents),
            "tool_results": {**s.tool_results, "read_document": document_reader(s.documents)},
            "tool_results_stored": {**s.tool_results, "read_document": READ_DOCUMENT_STATIC}}


def prompt_id(system, user, tools, documents=None):
    blob = json.dumps([system, user, tools, documents or {}], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def current_prompt_id(key, variant, level):
    r = render(key, variant, level)
    return prompt_id(r["system"], r["user"], r["tools"], r["documents"])


def cells(cross):
    """(variant, level) cells. Full: all 16. Trimmed: all four levels on LH and IX, levels 0-1 on IH and LX."""
    if cross == "full":
        return [(v, l) for v in VARIANTS for l in authority.LEVELS]
    if cross == "trimmed":
        return [(v, l) for v in VARIANTS for l in (authority.LEVELS if v in ("LH", "IX") else (0, 1))]
    raise ValueError(f"cross must be 'full' or 'trimmed', not {cross!r}")


def cell_id(key, variant, level):
    return f"{key}|{variant}|L{level}"


def score(key, calls):
    s = SCENARIOS[key]
    return sanity_stimuli.score_spec(s.score, s.keywords, calls)


def escalation_kind(key, calls):
    return sanity_stimuli.escalation_kind_for(SCENARIOS[key].keywords, calls)


def routine_progress(key, calls):
    """(routine items handled, routine items that need an action). A tool called once handles one item that
    expects it, so two items needing the same tool need two calls."""
    s = SCENARIOS[key]
    used = Counter(c["name"] for c in calls)
    need = Counter(i.expected_tool for i in s.routine_before + s.routine_after if i.expected_tool)
    return sum(min(used[t], n) for t, n in need.items()), sum(need.values())


def documents_read(key, calls):
    """Names of stored documents the agent opened (matched the way read_document matches them)."""
    s = SCENARIOS[key]
    index = {" ".join(k.casefold().split()): k for k in s.documents}
    seen = []
    for c in calls:
        if c["name"] == "read_document":
            name = index.get(" ".join(str(c["args"].get("name", "")).casefold().split()))
            if name and name not in seen:
                seen.append(name)
    return seen
