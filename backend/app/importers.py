"""CSV import for polls and events. Header names are matched loosely so exports from common
poll aggregators and spreadsheets work without editing."""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from .models import EVENT_TYPES, EventIn, PollIn

POLL_ALIASES = {
    "date": ("date", "end_date", "enddate", "end", "field_date", "fielded", "poll_date"),
    "pollster": ("pollster", "firm", "source", "poll"),
    "sample_size": ("sample_size", "n", "sample", "samplesize"),
    "population": ("population", "pop", "voters", "universe"),
    "metric": ("metric", "question", "measure"),
    "segment": ("segment", "group", "demographic", "subgroup", "crosstab"),
    "value": ("value", "candidate", "support", "pct", "share", "yes", "favorable", "approve"),
    "opponent_value": ("opponent_value", "opponent", "opp", "rival"),
    "margin_of_error": ("margin_of_error", "moe", "margin"),
}

EVENT_ALIASES = {
    "date": ("date", "day"),
    "type": ("type", "kind", "category"),
    "title": ("title", "name", "event", "headline"),
    "summary": ("summary", "description", "notes"),
    "content": ("content", "transcript", "quotes", "text", "script"),
    "topics": ("topics", "tags", "issues"),
    "tone": ("tone",),
    "venue": ("venue", "location", "outlet"),
    "audience": ("audience",),
    "url": ("url", "link", "source_url"),
}


def parse_date(raw: str) -> date:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return date.fromisoformat(raw[:10])


def _rows(text: str, aliases: dict[str, tuple[str, ...]]) -> tuple[list[dict[str, str]], list[str]]:
    reader = csv.DictReader(io.StringIO(text.strip().lstrip("﻿")))
    if not reader.fieldnames:
        return [], []
    norm = {h: h.strip().lower().replace(" ", "_").replace("-", "_") for h in reader.fieldnames if h}
    mapping: dict[str, str] = {}
    for field, names in aliases.items():
        for header, key in norm.items():
            if key in names and field not in mapping:
                mapping[field] = header
    unmatched = [h for h in reader.fieldnames if h and h not in mapping.values()]
    rows = [{field: (row.get(header) or "").strip() for field, header in mapping.items()} for row in reader]
    return rows, unmatched


def _num(raw: str) -> float | None:
    raw = raw.replace("%", "").replace(",", "").strip()
    return float(raw) if raw else None


def parse_polls(text: str) -> tuple[list[PollIn], list[dict[str, Any]], list[str]]:
    rows, unmatched = _rows(text, POLL_ALIASES)
    polls, errors = [], []
    for i, row in enumerate(rows, start=2):
        try:
            if not row.get("date") or not row.get("value"):
                raise ValueError("needs at least date and value columns")
            n = _num(row.get("sample_size", ""))
            polls.append(
                PollIn(
                    date=parse_date(row["date"]),
                    pollster=row.get("pollster") or "Unknown",
                    sample_size=int(n) if n else None,
                    population=row.get("population", "").upper()[:20],
                    metric=(row.get("metric") or "vote_share").strip().lower().replace(" ", "_"),
                    segment=row.get("segment") or "All",
                    value=_num(row["value"]),  # type: ignore[arg-type]
                    opponent_value=_num(row.get("opponent_value", "")),
                    margin_of_error=_num(row.get("margin_of_error", "")),
                )
            )
        except (ValueError, ValidationError) as e:
            errors.append({"row": i, "error": str(e).splitlines()[0][:200]})
    return polls, errors, unmatched


def parse_events(text: str) -> tuple[list[EventIn], list[dict[str, Any]], list[str]]:
    rows, unmatched = _rows(text, EVENT_ALIASES)
    events, errors = [], []
    for i, row in enumerate(rows, start=2):
        try:
            if not row.get("date") or not row.get("title"):
                raise ValueError("needs at least date and title columns")
            etype = row.get("type", "").strip().lower().replace(" ", "_").replace("-", "_")
            topics = [t.strip().lower() for t in row.get("topics", "").replace("|", ";").replace(",", ";").split(";") if t.strip()]
            events.append(
                EventIn(
                    date=parse_date(row["date"]),
                    type=etype if etype in EVENT_TYPES else "other",  # type: ignore[arg-type]
                    title=row["title"],
                    summary=row.get("summary", ""),
                    content=row.get("content", ""),
                    topics=topics,
                    tone=row.get("tone", ""),
                    venue=row.get("venue", ""),
                    audience=row.get("audience", ""),
                    url=row.get("url", ""),
                )
            )
        except (ValueError, ValidationError) as e:
            errors.append({"row": i, "error": str(e).splitlines()[0][:200]})
    return events, errors, unmatched
