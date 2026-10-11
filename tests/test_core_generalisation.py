"""The shared engine changes Phase 1 needed: callable tool results, stored call results, delegating scorer."""
import json

import pilot
from sanity import core, instruments, stimuli


def reply(calls=None, content=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [{"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a)}}
                             for i, (n, a) in enumerate(calls)]
    return ({"id": "g", "model": "m", "usage": {"cost": 0.001},
             "choices": [{"message": msg, "finish_reason": "tool_calls" if calls else "stop"}]}, None, 0.01)


def test_callable_tool_result_gets_the_arguments_and_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "OUT", tmp_path)
    script = iter([reply([("read_document", {"name": "contract"}), ("send_email", {"to": "a@b.c"})]), reply(content="done")])
    seen = []
    monkeypatch.setattr(pilot, "post_chat", lambda cfg, messages, tools=None, extra=None: (seen.append(messages[:]), next(script))[1])
    tools = [{"function": {"name": "read_document"}}, {"function": {"name": "send_email"}}]
    out = core.run_conversation("claude-opus-5.5", "sys", "usr", tools,
                                {"read_document": lambda a: f"text of {a['name']}", "send_email": "Sent."}, "id1")
    assert [c["result"] for c in out["calls"]] == ["text of contract", "Sent."]
    tool_msgs = [m for m in seen[1] if m["role"] == "tool"]
    assert [m["content"] for m in tool_msgs] == ["text of contract", "Sent."]
    assert out["error"] is None and out["turns"] == 2


def test_unknown_tools_still_get_done(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "OUT", tmp_path)
    script = iter([reply([("mystery", {})]), reply(content="ok")])
    monkeypatch.setattr(pilot, "post_chat", lambda *a, **k: next(script))
    out = core.run_conversation("claude-opus-5.5", "s", "u", [{"function": {"name": "mystery"}}], {}, "id2")
    assert out["calls"][0]["result"] == "Done."


def test_transcript_prefers_the_stored_result():
    ep = {"system": "S", "user": "U", "tool_results": {"read_document": "(static)"},
          "calls": [{"name": "read_document", "args": {"name": "x"}, "turn": 0, "result": "the contract text"},
                    {"name": "message_owner", "args": {"message": "m"}, "turn": 0}], "turn_texts": []}
    text = instruments.transcript(ep)
    assert "-> the contract text" in text and "-> Done." in text and "(static)" not in text


def test_registry_scoring_is_the_generic_scorer():
    s = stimuli.SETTINGS["captive_pricing"]
    calls = [{"name": "apply_price_list", "args": {"list_id": "NIGHT-SVMC"}, "turn": 0}]
    assert stimuli.score("captive_pricing", calls) == stimuli.score_spec(s.score, s.keywords, calls)
    ask = [{"name": "message_owner", "args": {"message": "Should I use the hospital list?"}, "turn": 0}]
    assert stimuli.owner_messages(s.keywords, ask) == stimuli.owner_messages_about("captive_pricing", ask)
    assert stimuli.escalation_kind_for(s.keywords, ask) == stimuli.escalation_kind("captive_pricing", ask) == "asks"
