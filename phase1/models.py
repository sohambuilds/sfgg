"""The Phase 1 model slate (PHASE1_HANDOVER.md §5.3), ordered by size slot.

Closed-model sizes are unpublished, so slots are ordinal and only within a ladder: smaller open < larger
open, and medium closed < large closed. The two frontier closed models share a rank. Each slot is a
different developer, so a slot difference describes these models; it is not an effect of size.
The four earlier models are built from the pilot's table, so their slugs and reasoning settings are identical.
"""
from dataclasses import dataclass

import pilot


@dataclass(frozen=True)
class ModelInfo:
    key: str
    slug: str
    reasoning: dict
    ladder: str                 # "open" or "closed"
    rank: int                   # order within the ladder
    slot: str
    total_params: str = ""
    active_params: str = ""     # "" until read from the model card
    source_url: str = ""
    new_in_phase1: bool = False

    def config(self):
        return {"slug": self.slug, "reasoning": self.reasoning}


def _old(key, **kw):
    cfg = pilot.MODELS[key]
    return ModelInfo(key=key, slug=cfg["slug"], reasoning=cfg["reasoning"], **kw)


SLATE = [
    _old("deepseek-v4-flash", ladder="open", rank=1, slot="smaller open-weight", total_params="284B",
         active_params="13B", source_url="https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash"),
    ModelInfo(key="kimi-k3", slug="moonshotai/kimi-k3", reasoning={"effort": "medium"}, ladder="open", rank=2,
              slot="larger open-weight", total_params="2.8T", active_params="",
              source_url="https://huggingface.co/moonshotai/Kimi-K3", new_in_phase1=True),
    _old("gpt-6-sol", ladder="closed", rank=1, slot="medium closed"),
    _old("claude-opus-5.5", ladder="closed", rank=2, slot="large frontier closed"),
    _old("grok-4.7", ladder="closed", rank=2, slot="large frontier closed"),
]
BY_KEY = {m.key: m for m in SLATE}
MODELS = {m.key: m.config() for m in SLATE}
FRONTIER = ("claude-opus-5.5", "grok-4.7", "gpt-6-sol")  # models whose behaviour carries the showcase claims
# Judges stay as in the sanity test (sanity.core.JUDGES); neither developer is in the slate.
SLATE_DEVELOPERS = {m.slug.split("/")[0] for m in SLATE}


def order(keys):
    """Keys sorted by ladder (open first) then rank, then key."""
    return sorted(keys, key=lambda k: (BY_KEY[k].ladder != "open", BY_KEY[k].rank, k))


def gaps():
    """Facts still to be read from a model card; `freeze` shows them but they don't block."""
    return [f"{m.key}: active parameters not recorded (see {m.source_url})" for m in SLATE
            if m.ladder == "open" and not m.active_params]
