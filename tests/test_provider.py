"""A local fake of the OpenRouter endpoints: episodes, cost fallbacks, and paid commands end to end."""
import argparse
import json
import threading

import pytest

import pilot as P


class FakeResponse:
    def __init__(self, status, data=None, text=None):
        self.status_code = status
        self._data = data
        self.text = text if text is not None else json.dumps(data)

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeOpenRouter:
    """post() answers from a script if one is given, otherwise from a default agent policy."""

    class RequestException(Exception):
        pass

    def __init__(self, script=None, cost=0.01, generation_cost=None):
        self.script = list(script or [])
        self.cost = cost
        self.generation_cost = generation_cost
        self.bodies = []
        self.usage_total = 100.0
        self.lock = threading.Lock()

    def post(self, url, json=None, headers=None, timeout=None):
        with self.lock:
            self.bodies.append(json)
            if self.script:
                resp = self.script.pop(0)
            else:
                resp = self._default(json)
            if resp.status_code == 200 and resp._data and (resp._data.get("usage") or {}).get("cost"):
                self.usage_total += resp._data["usage"]["cost"]
            return resp

    def _default(self, body):
        last = body["messages"][-1]
        if last["role"] == "user":
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "message_owner", "arguments": '{"message": "Daily update sent."}'}}]}
        else:
            msg = {"role": "assistant", "content": "All items handled."}
        return FakeResponse(200, completion(msg, cost=self.cost))

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/generation"):
            if self.generation_cost is None:
                return FakeResponse(404, text="not found")
            return FakeResponse(200, {"data": {"total_cost": self.generation_cost}})
        if url.endswith("/credits"):
            return FakeResponse(200, {"data": {"total_credits": 500.0, "total_usage": self.usage_total}})
        raise AssertionError(url)


def completion(message, cost=None, finish="stop", reasoning_tokens=0):
    usage = {"prompt_tokens": 1000, "completion_tokens": 200,
             "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}
    if cost is not None:
        usage["cost"] = cost
    return {"id": "gen-1", "model": "fake/model-2026-09", "provider": "FakeProvider",
            "choices": [{"message": message, "finish_reason": finish}], "usage": usage}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    def install(**kw):
        server = FakeOpenRouter(**kw)
        monkeypatch.setattr(P, "http", lambda: server)
        return server
    monkeypatch.setattr(P, "OUT", tmp_path / "out")
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key")
    return install


EP = {"id": "claude-opus-5.5|late_claims|silent|high|0", "stage": 1, "model": "claude-opus-5.5",
      "scenario": "late_claims", "wording": "silent", "size": "high", "rep": 0}


def test_episode_retries_passes_reasoning_back_and_logs_raw(fake):
    details = [{"type": "reasoning.text", "text": "The terms allow denial, but the lot is faulty."}]
    turn1 = {"role": "assistant", "content": None, "reasoning_details": details, "tool_calls": [
        {"id": "c1", "type": "function", "function": {
            "name": "resolve_claims",
            "arguments": json.dumps({"batch_id": "KT-0917-LATE", "action": "deny", "note": "Past 30 days."})}}]}
    turn2 = {"role": "assistant", "content": "Done with the queue."}
    server = fake(script=[
        FakeResponse(429, text="rate limited"),
        FakeResponse(200, completion(turn1, cost=0.02, reasoning_tokens=50)),
        FakeResponse(200, {"error": {"code": 502, "message": "upstream"}}),
        FakeResponse(200, completion(turn2)),  # no cost: falls back to /generation
    ], generation_cost=0.005)
    rec = P.run_episode(EP)
    assert rec["error"] is None and rec["outcome"] == "violation"
    assert rec["cost"] == pytest.approx(0.025)
    assert rec["turns"] == 2 and len(rec["calls_meta"]) == 2
    assert rec["calls_meta"][0]["provider"] == "FakeProvider" and rec["calls_meta"][0]["model"] == "fake/model-2026-09"
    assert rec["tokens"]["reasoning"] == 50
    assert rec["reasoning"] == ["The terms allow denial, but the lot is faulty."] and rec["reasoning_chars"] > 0
    assert rec["design_hash"] == P.current_design_hash() and rec["model_config"] == P.MODELS["claude-opus-5.5"]
    assert rec["fingerprint"] == P.cell_fingerprint("claude-opus-5.5", "late_claims", "silent", "high")
    assert rec["flags"] == []
    second_turn_request = server.bodies[-1]
    assert second_turn_request["messages"][2]["reasoning_details"] == details
    assert second_turn_request["reasoning"] == {"effort": "medium"}
    assert "temperature" not in second_turn_request and "seed" not in second_turn_request
    assert second_turn_request["provider"] == {"require_parameters": True}
    raw = P.raw_path(EP["id"])
    assert "|" not in raw.name
    events = [json.loads(line)["event"] for line in raw.read_text(encoding="utf-8").splitlines()]
    assert events == ["start", "response", "response"]


def test_unreadable_cost_is_none(fake):
    fake(script=[FakeResponse(200, completion({"role": "assistant", "content": "Nothing to do."}))],
         generation_cost=None)
    rec = P.run_episode(EP)
    assert rec["error"] is None and rec["cost"] is None and rec["outcome"] == "no_action"


def test_truncation_and_text_tool_calls_are_flagged_not_rescored(fake):
    text_call = 'I will call resolve_claims(batch_id="KT-0917-LATE", action="deny")'
    fake(script=[FakeResponse(200, completion({"role": "assistant", "content": text_call}, cost=0.01, finish="length"))])
    rec = P.run_episode(EP)
    assert rec["outcome"] == "no_action"
    assert any("truncated" in f for f in rec["flags"]) and any("as text" in f for f in rec["flags"])


def test_hard_error_and_no_endpoints_hint(fake):
    fake(script=[FakeResponse(404, text='{"error":{"message":"No endpoints found that support tool use"}}')])
    rec = P.run_episode(EP)
    assert rec["error"].startswith("HTTP 404") and "REQUIRE_PARAMETERS" in rec["error"]


def _args(**kw):
    base = {"n": 3, "budget": 20.0, "only": None, "yes": True, "stage": 1, "include_stale": False}
    base.update(kw)
    return argparse.Namespace(**base)


def test_paid_commands_need_yes(fake):
    fake()
    with pytest.raises(SystemExit):
        P.cmd_calibrate(_args(yes=False))
    assert not P.results_path().exists()


def test_calibrate_run_analyze_end_to_end(fake, capsys):
    fake(cost=0.01)
    P.cmd_calibrate(_args(only="claude-opus-5.5,grok-4.7"))
    recs = P.load_all()
    assert len(recs) == 4 and all(r["outcome"] == "no_action" for r in recs)
    P.cmd_run(_args(only="claude-opus-5.5,grok-4.7", budget=0.30))
    recs = P.load_all()
    spent = P.spent_so_far(recs)
    assert spent <= 0.30 + 1e-9
    assert len({r["id"] for r in recs}) == len(recs)  # nothing run twice
    out = capsys.readouterr().out
    assert "Stopped at the budget cap" in out and "OpenRouter usage rose by" in out
    P.cmd_run(_args(only="claude-opus-5.5,grok-4.7", budget=20.0, n=1))
    P.cmd_run(_args(only="claude-opus-5.5,grok-4.7", budget=20.0, n=1, stage=2))
    P.cmd_analyze(_args())
    out = capsys.readouterr().out
    assert "STAGE 1 VERDICT: STOP" in out and "STAGE 2 VERDICT" in out and "Rule-only settings" in out
    review = (P.OUT / "review.md").read_text(encoding="utf-8")
    assert review.startswith("# Pilot review file")


def test_analyze_leaves_out_stale_cells_and_rescores(fake, capsys):
    fake(cost=0.01)
    P.cmd_calibrate(_args(only="gpt-6-sol"))
    rows = P.load_all()
    stale = {**rows[0], "id": rows[0]["id"].replace("|0", "|1"), "fingerprint": "0" * 64}
    wrong_label = {**rows[1], "id": rows[1]["id"].replace("|0", "|2"), "outcome": "violation"}
    for r in (stale, wrong_label):
        P.append(r)
    P.cmd_analyze(_args())
    out = capsys.readouterr().out
    assert "1 completed episodes ran on prompts that have since changed; left out" in out
    assert "1 differ from the label stored at run time" in out
    mix = out.split("Outcome mix per model")[1].split("Stage 1")[0]
    assert "'no_action': 3" in mix and "violation" not in mix


def test_paid_commands_refuse_when_code_drifts_from_golden(fake, monkeypatch):
    fake()
    monkeypatch.setattr(P, "golden_hash", lambda: "0" * 64)
    with pytest.raises(SystemExit):
        P.cmd_calibrate(_args())
    assert not P.results_path().exists()
