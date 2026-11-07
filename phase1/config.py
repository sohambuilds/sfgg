"""Phase 1 settings. Phase 1 is an exploratory study: nothing here is pre-registered, and any of it can change
between rounds. Records keep the prompt and settings they ran under, so rounds stay separable."""

HARD_CAP = 30.0             # no paid command accepts a --budget above this, cumulative across Phase 1
DEFAULT_RUNS = 3            # runs per cell in a first round; `run --runs N` raises it where something moved
MAX_TURNS = 10              # a batch job with documents takes more turns than the sanity test's three items

NEUTRAL_SAMPLES = 3         # third-person legal question: samples per model and distinct set of documents
AUTHORITY_SAMPLES = 1       # how strongly each note insists: samples per model, scenario and level
COMPETENCE_RUNS = 3         # the legal, harmless, owner-gated act: runs per model and stance
PROBES_PER_GROUP = 5        # "was this an evaluation" probes per model, track and variant
NONACT_CODES = 5            # non-acts given process codes per model, beside every act
REALISM_PAIRS = 15          # Phase 1 against sanity-test records, each judged in both orders
