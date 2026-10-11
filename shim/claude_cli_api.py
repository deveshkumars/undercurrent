"""Local-testing shim: exposes the Claude Code CLI as an Anthropic Messages API endpoint.

    uvicorn shim.claude_cli_api:app --port 8788

Then point any Anthropic SDK client at it (base_url="http://127.0.0.1:8788"). Undercurrent does
this automatically when LLM_BACKEND=claude-cli. It uses whatever account `claude` is logged into,
so you can test without an API key. For testing only: it implements the subset of /v1/messages
Undercurrent uses (text content, system prompt, structured outputs via output_config.format,
effort, streaming) and runs each request as a fresh, tool-less `claude -p` session.

Environment:
    CLAUDE_BIN             path to the claude executable (default: "claude" on PATH)
    SHIM_MODEL             force a model for every request (e.g. "sonnet"); default: use the request's model
    SHIM_TIMEOUT           seconds before a CLI call is killed (default 300)
    SHIM_MAX_CONCURRENCY   parallel CLI processes (default 3)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

log = logging.getLogger("claude-cli-shim")
logging.basicConfig(level=logging.INFO, format="%(asctime)s shim %(levelname)s %(message)s")

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
FORCED_MODEL = os.environ.get("SHIM_MODEL") or None
TIMEOUT = float(os.environ.get("SHIM_TIMEOUT", "300"))
_semaphore = asyncio.Semaphore(int(os.environ.get("SHIM_MAX_CONCURRENCY", "3")))
# Run the CLI from an empty directory so no project CLAUDE.md or settings leak into prompts.
_WORKDIR = tempfile.mkdtemp(prefix="claude-cli-shim-")

app = FastAPI(title="Claude CLI → Messages API shim")


def _error(status: int, kind: str, message: str) -> JSONResponse:
    # Same envelope as the real API so SDK clients raise the matching exception types.
    return JSONResponse({"type": "error", "error": {"type": kind, "message": message}}, status_code=status)


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype in ("thinking", "redacted_thinking"):
            continue
        else:
            raise ValueError(f"content block type '{btype}' is not supported by the CLI shim")
    return "\n\n".join(parts)


def _build_prompt(messages: list[dict]) -> str:
    """A single user turn passes through untouched; longer histories become a labeled transcript."""
    if len(messages) == 1 and messages[0].get("role") == "user":
        return _text_of(messages[0].get("content"))
    lines = ["Continue this conversation. Reply only as the assistant to the final user message.", ""]
    for m in messages:
        role = m.get("role", "user")
        if role == "system":
            lines.append(f"<system_note>\n{_text_of(m.get('content'))}\n</system_note>")
        else:
            lines.append(f"<{role}>\n{_text_of(m.get('content'))}\n</{role}>")
    return "\n".join(lines)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "claude_bin": shutil.which(CLAUDE_BIN), "forced_model": FORCED_MODEL}


class ShimError(Exception):
    def __init__(self, status: int, kind: str, message: str):
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message


def _prepare(body: dict) -> tuple[list[str], str, str]:
    """Validate the request and build the CLI argv. Raises ShimError for anything unsupported."""
    if body.get("tools"):
        raise ShimError(400, "invalid_request_error", "The CLI shim does not support client tools")
    if not shutil.which(CLAUDE_BIN):
        raise ShimError(500, "api_error", f"'{CLAUDE_BIN}' not found on PATH; install Claude Code or set CLAUDE_BIN")
    try:
        prompt = _build_prompt(body.get("messages") or [])
        system = _text_of(body.get("system") or "")
    except ValueError as e:
        raise ShimError(400, "invalid_request_error", str(e)) from e

    model = FORCED_MODEL or body.get("model") or "haiku"
    output_config = body.get("output_config") or {}
    fmt = output_config.get("format") or {}
    args = [
        CLAUDE_BIN, "-p",
        "--output-format", "json",
        "--model", model,
        "--tools", "",
        "--safe-mode",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--disable-slash-commands",
    ]
    if system:
        args += ["--system-prompt", system]
    if fmt.get("type") == "json_schema" and fmt.get("schema"):
        args += ["--json-schema", json.dumps(fmt["schema"])]
    if output_config.get("effort"):
        args += ["--effort", output_config["effort"]]
    return args, prompt, model


async def _run_cli(args: list[str], prompt: str, model: str) -> dict:
    """Run one `claude -p` call and return an Anthropic Message dict."""
    started = time.monotonic()
    async with _semaphore:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=_WORKDIR,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=TIMEOUT)
        except asyncio.TimeoutError as e:
            proc.kill()
            raise ShimError(504, "timeout_error", f"claude CLI did not finish within {TIMEOUT:.0f}s") from e

    elapsed = time.monotonic() - started
    try:
        result = json.loads(stdout.decode() or "{}")
    except json.JSONDecodeError as e:
        log.error("unparseable CLI output: %s | stderr: %s", stdout[:500], stderr[:500])
        raise ShimError(500, "api_error", f"claude CLI returned non-JSON output (exit {proc.returncode})") from e

    if result.get("is_error") or proc.returncode != 0:
        message = result.get("result") or stderr.decode()[-500:] or "claude CLI failed"
        log.error("CLI error after %.1fs: %s", elapsed, message)
        raise ShimError(500, "api_error", f"claude CLI error: {message}")

    if result.get("structured_output") is not None:
        text = json.dumps(result["structured_output"])
    else:
        text = result.get("result") or ""

    usage = result.get("usage") or {}
    log.info("model=%s %.1fs in=%s out=%s", model, elapsed, usage.get("input_tokens"), usage.get("output_tokens"))
    return {
        "id": f"msg_cli_{uuid.uuid4().hex[:20]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        # The CLI reports tool_use when it satisfied --json-schema through its internal tool;
        # from the caller's point of view the turn simply ended.
        "stop_reason": "max_tokens" if result.get("stop_reason") == "max_tokens" else "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        },
    }


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def _stream(args: list[str], prompt: str, model: str) -> AsyncIterator[bytes]:
    """Replay the finished CLI result as the Messages API SSE sequence, with pings while waiting."""
    msg_id = f"msg_cli_{uuid.uuid4().hex[:20]}"
    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    task = asyncio.create_task(_run_cli(args, prompt, model))
    while True:
        done, _ = await asyncio.wait({task}, timeout=10)
        if done:
            break
        yield _sse("ping", {"type": "ping"})
    try:
        message = task.result()
    except ShimError as e:
        yield _sse("error", {"type": "error", "error": {"type": e.kind, "message": e.message}})
        return
    text = message["content"][0]["text"]
    yield _sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
    yield _sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}})
    yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
        "usage": message["usage"],
    })
    yield _sse("message_stop", {"type": "message_stop"})


@app.post("/v1/messages", response_model=None)
async def messages(request: Request) -> JSONResponse | StreamingResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _error(400, "invalid_request_error", "Body must be JSON")
    try:
        args, prompt, model = _prepare(body)
        if body.get("stream"):
            return StreamingResponse(_stream(args, prompt, model), media_type="text/event-stream")
        return JSONResponse(await _run_cli(args, prompt, model))
    except ShimError as e:
        return _error(e.status, e.kind, e.message)
