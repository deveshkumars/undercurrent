"""A fake llm.structured for simulation tests: deterministic, instant, with planted effects.

- Persona generation embeds PARTY=<party> in the transcript (read from the card in the task).
- Panel answers read PARTY back from the persona block. If the stimulus contains BOOST, Democrats'
  thermometer rises by 10; nobody else moves. Vote choice follows the thermometer.
- Backtest answers move vote choice by the planted demo effect when the event title is in the task.
- Social activations comment on the first post in the feed, or write a post when the feed is empty.
"""

from __future__ import annotations

import hashlib
import re
import threading
import types
import typing
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

BASE_THERM = {"democrat": 62, "republican": 30, "independent": 46}


def _h(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def generic(model: type[BaseModel], seed: str) -> BaseModel:
    data = {}
    for name, field in model.model_fields.items():
        data[name] = _value(field.annotation, f"{seed}:{name}")
    return model(**data)


def _value(ann: Any, seed: str) -> Any:
    origin = get_origin(ann)
    if origin is Literal:
        opts = get_args(ann)
        return opts[_h(seed) % len(opts)]
    if origin in (list, typing.List):
        (inner,) = get_args(ann) or (str,)
        return [_value(inner, f"{seed}:{i}") for i in range(2)]
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        return _value(args[0], seed)
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return generic(ann, seed)
    if ann is int:
        return 5
    if ann is float:
        return 0.4
    if ann is bool:
        return False
    return f"text {seed[-12:]}"


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._lock = threading.Lock()

    def __call__(self, task: str, output: type[BaseModel], dossier: str | None = None, effort: str | None = None, **kw: Any):
        blocks = kw.get("blocks") or ()
        context = "\n".join(b.text for b in blocks)
        with self._lock:
            self.calls.append({"output": output.__name__, "task": task, "context": context, **{k: v for k, v in kw.items() if k != "blocks"}})
        name = output.__name__
        if name == "PersonaOutput":
            obj = self._persona(task, output)
        elif name == "ReflectionsOutput":
            obj = generic(output, task[:50])
        elif name.startswith("PanelAnswers"):
            obj = self._panel(task, context, output)
        elif name == "RoutingOutput":
            ids = re.findall(r"^- ([a-z][a-z0-9_]*):", task, re.M)
            obj = output(routes=[{"question_id": i, "expert": "psychologist", "why": "fake"} for i in ids])
        elif name == "SocialActivation":
            obj = self._social(task, output)
        else:
            obj = generic(output, task[:80])
        usage = {"model": "fake", "input_tokens": len(task) // 4 + len(context) // 4, "output_tokens": 40,
                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "latency_ms": 1}
        return obj, usage

    def _persona(self, task: str, output: type[BaseModel]) -> BaseModel:
        m = re.search(r"Party identification: (\w+)", task)
        party = m.group(1) if m else "independent"
        refl = {k: [f"{k} note {i}" for i in range(3)] for k in ("psychologist", "behavioral_economist", "political_scientist", "demographer")}
        return output(first_name="Pat", identity="I live here and work hard.",
                      transcript=f"Interviewer: Tell me about yourself.\nRespondent: Not much to say. PARTY={party}",
                      reflections=refl)

    def _panel(self, task: str, context: str, output: type[BaseModel]) -> BaseModel:
        m = re.search(r"PARTY=(\w+)", context) or re.search(r"Party identification: (\w+)", context)
        party = m.group(1) if m else "independent"
        noise = _h(context[:400]) % 11 - 5
        therm = BASE_THERM.get(party, 45) + noise
        if "BOOST" in task and party == "democrat":
            therm += 10
        for title, effect in getattr(self, "event_effects", {}).items():
            if title in task:
                therm += effect
        data: dict[str, Any] = {}
        for fname, field in output.model_fields.items():
            ann = field.annotation
            if fname == "reasoning":
                data[fname] = "I thought about it briefly."
            elif fname == "q_thermometer":
                data[fname] = therm
            elif fname == "q_vote_choice":
                opts = get_args(ann)
                data[fname] = opts[0] if therm > 52 else opts[1] if therm < 40 else "undecided"
            elif get_origin(ann) is Literal:
                opts = get_args(ann)
                data[fname] = opts[_h(fname, context[:200]) % len(opts)]
            elif ann is int:
                data[fname] = 7
            else:
                data[fname] = "Honestly it didn't move me much."
        return output(**data)

    def _social(self, task: str, output: type[BaseModel]) -> BaseModel:
        ids = re.findall(r"^\[(p\d+)\]", task, re.M)
        expr = {"emotion_type": "angry", "emotion_intensity": "high", "stance": "oppose", "stance_intensity": "medium",
                "style": "sarcastic", "narrative": "labeling"}
        if ids:
            actions = [{"action_type": "short_comment", "target_id": ids[0], "expression": expr,
                        "content": {"text": "This is ridiculous.", "topics": ["outrage"]}},
                       {"action_type": "like", "target_id": ids[0], "expression": expr, "content": {"text": "", "topics": []}}]
        else:
            actions = [{"action_type": "short_post", "target_id": "", "expression": expr,
                        "content": {"text": "Did everyone see this?", "topics": ["news"]}}]
        return output(
            perception="Saw the news.",
            belief={"opinions": [{"subject": "Acme", "opinion": "They messed up.", "stance": -0.6, "reason": "the news"}],
                    "emotions": {"happy": 0.1, "sad": 0.2, "angry": 0.7, "fear": 0.1, "surprise": 0.3, "disgust": 0.4}},
            desire={"motive": "emotional_venting", "intensity": "high"},
            actions=actions,
        )
