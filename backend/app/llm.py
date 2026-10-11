"""Claude access. The app always talks the Anthropic Messages API through the official SDK;
LLM_BACKEND=claude-cli just points that SDK at the local shim (shim/claude_cli_api.py)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal, Sequence, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .config import get_settings
from .prompts import SYSTEM_PROMPT

log = logging.getLogger("undercurrent.llm")

T = TypeVar("T", bound=BaseModel)

MAX_CACHE_BREAKPOINTS = 4


class LLMError(Exception):
    def __init__(self, message: str, status_code: int = 502, retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        # True for rate limits, timeouts and 5xx: the same request may succeed later.
        self.retryable = retryable


@dataclass(frozen=True)
class Block:
    """One text block of the user turn. ``cache=True`` puts a cache breakpoint after it."""

    text: str
    cache: bool = False


@lru_cache
def get_client() -> anthropic.Anthropic:
    s = get_settings()
    if s.llm_backend == "claude-cli":
        # The shim ignores the key; the CLI uses whatever login `claude` already has.
        return anthropic.Anthropic(api_key="claude-cli-shim", base_url=s.claude_cli_shim_url, timeout=600.0, max_retries=0)
    if not s.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set. Add it to .env (or set LLM_BACKEND=claude-cli for local testing).", 503)
    return anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=240.0, max_retries=2)


def thinking_param(model: str, mode: Literal["adaptive", "off"] | None) -> dict | None:
    """Translate a thinking preference into the request field this model accepts (None = omit)."""
    if mode is None:
        return None
    if mode == "adaptive":
        return {"type": "adaptive"}
    m = model.lower()
    if m.startswith("claude-sonnet-5-5"):
        return {"type": "between_tools"}
    if m.startswith(("claude-opus-5-5", "claude-fable", "claude-mythos")):
        return None  # thinking can't be turned off on these; low effort keeps it short
    return {"type": "disabled"}


def structured(
    task: str,
    output: type[T],
    dossier: str | None = None,
    effort: str | None = None,
    *,
    system: str | None = None,
    cache_system: bool = False,
    blocks: Sequence[Block] = (),
    thinking: Literal["adaptive", "off"] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    log_level: int = logging.INFO,
) -> tuple[T, dict]:
    """One Messages API call whose reply is validated against ``output``.

    The dossier goes first with a cache breakpoint so insights, forecasts and recommendations
    for the same candidate reuse it; the task-specific instructions come after it. Simulation
    calls pass their own ``system`` prompt and ``blocks`` (e.g. a cached persona) instead.
    """
    s = get_settings()
    parts = ([Block(dossier, cache=True)] if dossier else []) + list(blocks)
    breakpoints = sum(b.cache for b in parts) + (1 if cache_system else 0)
    if breakpoints > MAX_CACHE_BREAKPOINTS:
        raise ValueError(f"at most {MAX_CACHE_BREAKPOINTS} cache breakpoints per request, got {breakpoints}")

    content: list[dict] = []
    for b in parts:
        block: dict = {"type": "text", "text": b.text}
        if b.cache:
            block["cache_control"] = {"type": "ephemeral"}
        content.append(block)
    content.append({"type": "text", "text": task})

    system_text = SYSTEM_PROMPT if system is None else system
    system_field: str | list[dict] = (
        [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}] if cache_system else system_text
    )
    model_id = model or s.llm_model
    kwargs: dict = {}
    thinking_field = thinking_param(model_id, thinking)
    if thinking_field is not None:
        kwargs["thinking"] = thinking_field

    client = get_client()
    opts: dict = {}
    if timeout is not None:
        opts["timeout"] = timeout
    if max_retries is not None and s.llm_backend != "claude-cli":
        opts["max_retries"] = max_retries
    if opts:
        client = client.with_options(**opts)

    started = time.monotonic()
    try:
        # Streaming keeps long, thinking-heavy responses clear of HTTP timeouts.
        with client.messages.stream(
            model=model_id,
            max_tokens=max_tokens or s.llm_max_tokens,
            system=system_field,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": effort or s.llm_effort},
            output_format=output,
            **kwargs,
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise LLMError("The Anthropic API rejected the API key.", 502) from e
    except anthropic.RateLimitError as e:
        raise LLMError("Rate limited by the Anthropic API; try again shortly.", 429, retryable=True) from e
    except anthropic.BadRequestError as e:
        raise LLMError(f"The model request was invalid: {e.message}", 502) from e
    except anthropic.APITimeoutError as e:
        raise LLMError("The model request timed out.", 504, retryable=True) from e
    except anthropic.APIConnectionError as e:
        hint = (
            f" Is the claude-cli shim running at {s.claude_cli_shim_url}? Start it with `make shim`."
            if s.llm_backend == "claude-cli"
            else ""
        )
        raise LLMError("Could not reach the model backend." + hint, 502, retryable=True) from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Model backend error ({e.status_code}): {e.message}", 502, retryable=e.status_code >= 500) from e
    except anthropic.APIError as e:
        raise LLMError(f"Model backend error: {e.message}", 502) from e
    except (ValidationError, ValueError) as e:
        raise LLMError("The model returned output that did not match the expected format; try again.", 502) from e

    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request. Try rephrasing the input.", 422)
    if response.stop_reason == "max_tokens":
        raise LLMError("The model ran out of output tokens before finishing; raise LLM_MAX_TOKENS.", 502)
    if response.parsed_output is None:
        raise LLMError("The model returned output that did not match the expected format.", 502)

    u = response.usage
    usage = {
        "model": response.model,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", None) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", None) or 0,
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    log.log(log_level, "llm call %s: %s", output.__name__, usage)
    return response.parsed_output, usage
