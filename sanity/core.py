"""Provider calls, the tool loop, storage and the budget for the sanity test.

Reuses the pilot's OpenRouter client, cost reading and budget holds. Records live in out_sanity/,
one JSONL file per part, and every record carries its full rendered prompt and the request
settings actually sent. Results are append-only.
"""
import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pilot

OUT = Path("out_sanity")
MODELS = pilot.MODELS
# Judges come from developers outside the five tested models. Dated snapshots, temperature 0.
JUDGES = {
    "qwen3.8-max-0902": {"slug": "qwen/qwen3.8-max-0902", "reasoning": None},
    "mistral-medium-3.5": {"slug": "mistralai/mistral-medium-3-5", "reasoning": None},
}
PRIMARY_JUDGE, SECOND_JUDGE = "qwen3.8-max-0902", "mistral-medium-3.5"
JUDGE_EXTRA = {"temperature": 0, "max_tokens": 4000}
PARTS = ("A", "B", "C", "D")
WORKERS = 4
LABEL = "Sanity-test"  # names the study in cost messages
_lock = threading.Lock()


def configure(out=None, models=None, parts=None, label=None):
    """Point the engine at another study (Phase 1) without forking it. Defaults stay the sanity test's."""
    global OUT, MODELS, PARTS, LABEL
    if out is not None:
        OUT = Path(out)
    if models is not None:
        MODELS = models
    if parts is not None:
        PARTS = tuple(parts)
    if label is not None:
        LABEL = label


def config(key):
    return MODELS[key] if key in MODELS else JUDGES[key]


def request_settings(key, tools, extra=None):
    """Everything sent besides the messages, for provenance."""
    cfg = config(key)
    sent = {"slug": cfg["slug"], "reasoning": cfg.get("reasoning"), "max_tokens": pilot.MAX_TOKENS,
            "require_parameters": pilot.REQUIRE_PARAMETERS, "tools": [t["function"]["name"] for t in tools],
            "temperature": "provider default", "top_p": "provider default", "seed": "not sent"}
    for k, v in (extra or {}).items():
        sent[k] = v
    return sent


# ---------------------------------------------------------------- storage

def part_path(part):
    return OUT / f"part_{part.lower()}.jsonl"


def append(part, rec):
    OUT.mkdir(exist_ok=True)
    with _lock, open(part_path(part), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def load(part):
    path = part_path(part)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_all():
    return [r for p in PARTS for r in load(p)]


def done_ids(part):
    return {r["id"] for r in load(part) if not r.get("error")}


def raw_path(rec_id):
    return OUT / "raw" / (re.sub(r'[|:<>"/\\?*]', "__", rec_id) + ".jsonl")


def log_raw(rec_id, entry):
    path = raw_path(rec_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------- calls

def _message_parts(data):
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if content is not None and not isinstance(content, str):
        content = json.dumps(content)
    rtext = msg.get("reasoning")
    if not rtext and msg.get("reasoning_details"):
        rtext = "\n".join(str(d.get("text") or d.get("summary") or "")
                          for d in msg["reasoning_details"] if isinstance(d, dict)).strip()
    return choice, msg, content, rtext


def _meta(data, choice, cost, latency, turn=0):
    return {"turn": turn, "id": data.get("id"), "model": data.get("model"), "provider": data.get("provider"),
            "finish_reason": choice.get("finish_reason"), "usage": data.get("usage") or {}, "cost": cost,
            "latency_s": round(latency, 3)}


def run_single(key, messages, rec_id, extra=None):
    """One call with no tools. Returns text, reasoning, metadata, cost and error."""
    cfg = config(key)
    log_raw(rec_id, {"event": "start", "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    data, err, latency = pilot.post_chat(cfg, messages, tools=[], extra=extra)
    if err:
        log_raw(rec_id, {"event": "error", "error": err})
        return {"error": err, "cost": 0.0}
    log_raw(rec_id, {"event": "response", "latency_s": latency, "response": data})
    cost = pilot.call_cost(data)
    choice, _, content, rtext = _message_parts(data)
    flags = ["truncated"] if choice.get("finish_reason") == "length" else []
    return {"error": None, "text": content or "", "reasoning": rtext or "", "calls_meta": [_meta(data, choice, cost, latency)],
            "flags": flags, "cost": cost}


def run_conversation(key, system, user, tools, tool_results, rec_id):
    """The pilot's episode loop with a given toolset: up to MAX_TURNS turns with fixed tool results.
    A tool result is a string, or a callable taking the call's arguments (for tools such as read_document).
    Each recorded call carries the result it was given."""
    cfg = config(key)
    names = "|".join(re.escape(t["function"]["name"]) for t in tools)
    text_call = re.compile(rf"<tool_call|<function[=\s>]|\"tool_calls\"|\b(?:{names})\s*\(|\"name\"\s*:\s*\"(?:{names})\"")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    calls, texts, reasoning, meta, flags, turn_texts = [], [], [], [], [], []
    cost, cost_known, turns = 0.0, True, 0
    log_raw(rec_id, {"event": "start", "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    for turn in range(pilot.MAX_TURNS):
        data, err, latency = pilot.post_chat(cfg, messages, tools=tools)
        if err:
            log_raw(rec_id, {"event": "error", "turn": turn, "error": err})
            return {"error": err, "calls": calls, "turns": turns, "calls_meta": meta, "cost": cost if cost_known else None}
        log_raw(rec_id, {"event": "response", "turn": turn, "latency_s": latency, "response": data})
        turns += 1
        c = pilot.call_cost(data)
        if c is None:
            cost_known = False
        else:
            cost += c
        choice, msg, content, rtext = _message_parts(data)
        meta.append(_meta(data, choice, c, latency, turn))
        if content:
            texts.append(content)
            turn_texts.append({"turn": turn, "text": content})
        if rtext:
            reasoning.append(rtext)
        if choice.get("finish_reason") == "length":
            flags.append(f"truncated at turn {turn}")
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            if content and text_call.search(content):
                flags.append(f"tool call written as text at turn {turn}")
            break
        kept = {"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls}
        if msg.get("reasoning_details"):
            kept["reasoning_details"] = msg["reasoning_details"]
        messages.append(kept)
        for tc in tool_calls:
            f = tc.get("function") or {}
            name = f.get("name", "")
            try:
                args = json.loads(f.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_unparsed": f.get("arguments")}
            if not isinstance(args, dict):
                args = {"_unparsed": args}
            result = tool_results.get(name, "Done.")
            result = result(args) if callable(result) else result
            calls.append({"name": name, "args": args, "turn": turn, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": result})
    else:
        flags.append("stopped at the turn limit with tool calls pending")
    return {"error": None, "calls": calls, "text": texts, "turn_texts": turn_texts, "reasoning": reasoning, "turns": turns,
            "calls_meta": meta, "flags": flags, "cost": cost if cost_known else None,
            "reasoning_chars": sum(len(x) for x in reasoning)}


# ---------------------------------------------------------------- budget and jobs

def spent(records=None):
    return sum(r.get("cost") or 0.0 for r in (load_all() if records is None else records))


def measured(records=None):
    """Measured costs per (part, model) from completed records."""
    out = {}
    for r in load_all() if records is None else records:
        if r.get("cost") is not None and not r.get("error"):
            out.setdefault((r["part"], r["model"]), []).append(r["cost"])
    return out


# Errors that mean no further call can succeed on this key; the runner stops instead of retrying them all.
OUT_OF_CREDIT = re.compile(r"key limit exceeded|insufficient credits|HTTP 402", re.I)
LIVE_MARGIN = 0.25  # dollars left unspent below the live key or account limit


def live_headroom():
    """Dollars this key can still spend right now: the smaller of the key's own remaining limit
    (GET /api/v1/key) and the account balance (GET /credits). None if neither can be read."""
    requests = pilot.http()
    headers = {"Authorization": f"Bearer {pilot.api_key()}"}
    found = {}
    try:
        r = requests.get(f"{pilot.API}/key", headers=headers, timeout=30)
        if r.status_code == 200:
            d = r.json().get("data") or {}
            if d.get("limit_remaining") is not None:
                found["key limit"] = float(d["limit_remaining"])
    except Exception:  # noqa: BLE001 - reported as unreadable
        pass
    got = pilot.credits()
    if got and got[0] is not None and got[1] is not None:
        found["account balance"] = float(got[0]) - float(got[1])
    return (min(found.values()), found) if found else (None, found)


def confirm_paid(args, what, jobs):
    """Every paid command states what it will run and needs --yes and an explicit --budget."""
    records = load_all()
    s = spent(records)
    costs = measured(records)
    models = sorted({(j["part"], j["model"]) for j in jobs})
    print(f"{what}: {len(jobs)} calls or episodes.")
    for part, m in models:
        n = sum(1 for j in jobs if (j["part"], j["model"]) == (part, m))
        c = costs.get((part, m))
        est = (f"measured mean ${statistics.mean(c):.4f} over {len(c)}, so about ${n * statistics.mean(c):.2f} for these"
               if c else "no measured cost yet; its first call runs alone to measure it")
        print(f"  part {part}  {m:<20} {n:>4}  {est}")
    print(f"{LABEL} spend so far ${s:.2f}; cap ${args.budget:.2f}.")
    if not args.yes:
        sys.exit("Nothing was run. Add --yes to spend money.")
    room, parts = live_headroom()
    if room is None:
        print("Could not read the key's limit or the account balance; only the --budget cap applies.")
        return args.budget
    detail = ", ".join(f"{k} ${v:.2f}" for k, v in parts.items())
    cap = min(args.budget, s + room - LIVE_MARGIN)
    print(f"Live: {detail}. Effective cap ${cap:.2f} (leaves ${LIVE_MARGIN:.2f} under the live limit).")
    if cap <= s:
        sys.exit("No room left under the key's limit or the account balance. Raise the key's limit or use a new key.")
    return cap


def run_jobs(jobs, cap):
    """jobs: dicts with id, part, model and run (a callable returning a record). Each (part, model)
    without a measured cost runs one job alone first; the rest run in parallel under budget holds.
    Records are appended as they finish. Returns (finished records, stopped at cap)."""
    records = load_all()
    costs = measured(records)
    budget = pilot.Budget(cap, spent(records), {k: max(v) for k, v in costs.items()})
    finished = []
    pending = []
    for j in jobs:
        k = (j["part"], j["model"])
        if k in budget.max_cost:
            pending.append(j)
            continue
        if budget.spent >= cap:
            return finished, True
        rec = j["run"]()
        append(j["part"], rec)
        finished.append(rec)
        budget.spent += rec.get("cost") or 0.0
        if OUT_OF_CREDIT.search(rec.get("error") or ""):
            print(f"  stopping: {rec['error'][:120]}")
            return finished, True
        if rec.get("cost") is not None and not rec.get("error"):
            budget.max_cost[k] = rec["cost"]
        else:
            known = [v for (p, _), v in budget.max_cost.items() if p == j["part"]]
            budget.max_cost[k] = max(known) if known else 0.25
            print(f"  note: no readable cost for {k}; holding ${budget.max_cost[k]:.2f} per job")
    capped = threading.Event()

    def work(j):
        if capped.is_set():
            return None
        k = (j["part"], j["model"])
        hold = budget.reserve(k)
        if hold is None:
            capped.set()
            return None
        rec = j["run"]()
        budget.settle(k, hold, rec.get("cost"))
        append(j["part"], rec)
        if OUT_OF_CREDIT.search(rec.get("error") or "") and not capped.is_set():
            print(f"  stopping: {rec['error'][:120]}")
            capped.set()
        return rec

    with ThreadPoolExecutor(WORKERS) as pool:
        for fut in as_completed([pool.submit(work, j) for j in pending]):
            rec = fut.result()
            if rec:
                finished.append(rec)
                if len(finished) % 20 == 0:
                    print(f"  {len(finished)} done, ${budget.spent:.2f} recorded")
    return finished, capped.is_set()


def summarize_run(finished, capped):
    errors = sum(1 for r in finished if r.get("error"))
    flagged = sum(1 for r in finished if r.get("flags"))
    print(f"Ran {len(finished)} ({errors} errors, {flagged} flagged); {LABEL.lower()} spend now ${spent():.2f}.")
    if capped:
        print("Stopped at the budget cap before finishing.")
    if errors:
        print("Run the same command again to retry errored items.")


def parse_json(text):
    """The first JSON object in a model's reply, or None."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
