import json

import pytest
from fastapi.testclient import TestClient

from shim import claude_cli_api as shim


class FakeProc:
    def __init__(self, payload: dict, returncode: int = 0):
        self.payload = payload
        self.returncode = returncode
        self.stdin_seen = b""

    async def communicate(self, data: bytes):
        self.stdin_seen = data
        # stream-json: init/assistant events, then the result event last
        events = [{"type": "system", "subtype": "init"}, {"type": "assistant"}, {"type": "result", **self.payload}]
        return "\n".join(json.dumps(e) for e in events).encode(), b""

    def kill(self):
        pass


@pytest.fixture()
def fake_cli(monkeypatch):
    calls = []

    async def fake_exec(*args, **kwargs):
        proc = FakeProc({"is_error": False, "result": "hi", "structured_output": {"score": 7}, "stop_reason": "tool_use", "usage": {"input_tokens": 3, "output_tokens": 5, "cache_read_input_tokens": 40, "cache_creation_input_tokens": 9, "cache_creation": {"ephemeral_1h_input_tokens": 9, "ephemeral_5m_input_tokens": 0}}})
        calls.append((args, proc))
        return proc

    monkeypatch.setattr(shim.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(shim.shutil, "which", lambda _: "/usr/bin/claude")
    return calls


def test_structured_output_round_trip(fake_cli):
    body = {
        "model": "claude-haiku-5-5",
        "max_tokens": 100,
        "system": [{"type": "text", "text": "Be terse."}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "Rate it", "cache_control": {"type": "ephemeral"}}]}],
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}},
    }
    r = TestClient(shim.app).post("/v1/messages", json=body)
    assert r.status_code == 200
    msg = r.json()
    assert msg["content"][0]["text"] == '{"score": 7}'
    assert msg["stop_reason"] == "end_turn"
    args, proc = fake_cli[0]
    assert "--json-schema" in args and "--effort" in args and args[args.index("--system-prompt") + 1] == "Be terse."
    line = json.loads(proc.stdin_seen)
    assert line["type"] == "user" and "--input-format" in args
    # blocks and breakpoints survive; the CLI caches for an hour, so every breakpoint is sent with ttl=1h
    assert line["message"]["content"] == [{"type": "text", "text": "Rate it", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert msg["usage"]["cache_read_input_tokens"] == 40
    assert msg["usage"]["cache_creation"]["ephemeral_1h_input_tokens"] == 9


def test_streaming_emits_message_events(fake_cli):
    body = {"model": "m", "max_tokens": 10, "stream": True, "messages": [{"role": "user", "content": "hello"}]}
    r = TestClient(shim.app).post("/v1/messages", json=body)
    events = [line.split(": ", 1)[1] for line in r.text.splitlines() if line.startswith("event: ")]
    assert events == ["message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_delta", "message_stop"]


def test_sdk_client_can_parse_through_shim(fake_cli):
    """The official SDK, pointed at the shim, gets a validated object back."""
    import anthropic
    from pydantic import BaseModel

    class Score(BaseModel):
        score: int

    http = TestClient(shim.app)
    client = anthropic.Anthropic(api_key="x", base_url="http://testserver", http_client=anthropic.DefaultHttpxClient(transport=http._transport))
    with client.messages.stream(model="m", max_tokens=100, messages=[{"role": "user", "content": "go"}], output_format=Score) as stream:
        final = stream.get_final_message()
    assert final.parsed_output == Score(score=7)


def test_multi_turn_becomes_transcript():
    prompt = shim._build_prompt([
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ])
    assert "<user>\na\n</user>" in prompt and "<assistant>\nb\n</assistant>" in prompt


def test_rejects_tools(fake_cli):
    r = TestClient(shim.app).post("/v1/messages", json={"model": "m", "max_tokens": 5, "messages": [], "tools": [{"name": "x"}]})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"
