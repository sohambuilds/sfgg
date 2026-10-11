"""A Phase 1 scenario: one business decision with two one-sentence toggles (legality, harm).

Scenarios are written by people (PHASE1_HANDOVER.md rule 6). This file only defines their shape.
"""
from dataclasses import dataclass, field

# Same vocabulary as the sanity test: I = illegal, L = legal, H = harms an identifiable party, X = harmless.
VARIANTS = ("LH", "LX", "IH", "IX")
PROVENANCE = ("human", "ai-draft", "test-fixture")


def variant_flags(variant):
    """(legal, harmful) for a variant label."""
    if variant not in VARIANTS:
        raise ValueError(variant)
    return variant[0] == "L", variant[1] == "H"


@dataclass(frozen=True)
class Toggle:
    """One sentence that flips one property. `on` is the legal / harmful form, `off` the illegal / harmless one.
    `facts_*` are the same sentences in the third person, for the manipulation check."""
    on: str
    off: str
    facts_on: str
    facts_off: str


@dataclass(frozen=True)
class RoutineItem:
    text: str                       # without the "Item N - " prefix
    expected_tool: str = ""         # tool a competent agent calls for it; "" if it needs no action


@dataclass(frozen=True)
class Figure:
    """A stated number: `expr` must evaluate to `value`, and `text` (as written in the item) must appear."""
    expr: str
    value: float
    text: str
    tol: float = 0.5


@dataclass(frozen=True)
class Scenario:
    key: str
    domain: str
    company: str
    owner: str                      # first name used in pinned notes
    system: str                     # operator prompt through the operating policies; no pinned notes
    header: str                     # first lines of the queue, before item 1
    routine_before: tuple           # RoutineItem, items before the target
    routine_after: tuple            # RoutineItem, items after the target
    target: str                     # the target item, with {legality} and {harm} slots; no "Item N - " prefix
    legality: Toggle
    harm: Toggle
    tools: tuple                    # tool definitions; must include message_owner and read_document
    tool_results: dict              # tool name -> result string (message_owner says the owner is away until Monday)
    documents: dict                 # name -> text, served by read_document
    topic: str                      # "I've seen the {topic}."
    act: str                        # identical at every authority level
    silent: str                     # body of the level-0 note, unrelated to everything else
    score: dict                     # tool, field, violation / partial / compliant values, requires, email_to
    keywords: tuple                 # a message to the owner mentioning one of these is about the target
    entitlement: bool               # legal variant rests on an explicit contract right (vs mere permissibility)
    facts: str                      # third-person description with {legality} and {harm} slots
    check_act: str                  # completes "Is it legal for {check_actor} to ..."
    check_actor: str
    figures: tuple = ()
    author: str = ""
    names_source: str = ""          # where the human chose names from (census list, real town, ...)
    provenance: str = "human"
    extra: dict = field(default_factory=dict)

    @property
    def target_position(self):
        return len(self.routine_before) + 1

    @property
    def n_items(self):
        return len(self.routine_before) + 1 + len(self.routine_after)

    def tool_names(self):
        return [t["function"]["name"] for t in self.tools]


def fn(name, description, properties, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required}}}


def read_document_tool():
    return fn("read_document", "Open a document from the company's document store by name.",
              {"name": {"type": "string"}}, ["name"])


def document_reader(documents):
    """Tool result for read_document: the stored text, or a plain miss."""
    index = {" ".join(k.casefold().split()): v for k, v in documents.items()}

    def read(args):
        name = " ".join(str(args.get("name", "")).casefold().split())
        return index.get(name, "No document with that name.")
    return read
