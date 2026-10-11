import statistics
from datetime import date, timedelta

from backend.app import analytics as A
from backend.app.sample_data import DEMO_EVENTS, build_demo


def _poll(d, value, pollster="P", n=1000, segment="All", opp=None, metric="vote_share"):
    return {
        "id": f"{pollster}-{d}-{segment}",
        "date": d.isoformat(),
        "pollster": pollster,
        "sample_size": n,
        "metric": metric,
        "segment": segment,
        "value": value,
        "opponent_value": opp,
    }


def test_step_change_is_detected_at_the_event():
    start = date(2026, 1, 1)
    polls = []
    for i in range(60):
        d = start + timedelta(days=i)
        polls.append(_poll(d, 40.0 if i < 30 else 44.0, pollster=f"P{i % 3}", n=1500))
    event = {"id": "e1", "date": (start + timedelta(days=30)).isoformat(), "title": "Big speech", "type": "speech", "topics": ["economy"]}
    res = A.analyze(polls, [event], window=14)
    imp = res["events"][0]["impact"]
    assert abs(imp["delta"] - 4.0) < 0.3
    assert imp["signal"] == "strong"


def test_no_change_reads_as_noise():
    start = date(2026, 1, 1)
    polls = [_poll(start + timedelta(days=i), 45.0 + (0.5 if i % 2 else -0.5), pollster=f"P{i % 4}") for i in range(40)]
    event = {"id": "e1", "date": (start + timedelta(days=20)).isoformat(), "title": "Quiet day", "type": "statement", "topics": []}
    imp = A.analyze(polls, [event])["events"][0]["impact"]
    assert imp["signal"] in ("none", "weak")
    assert abs(imp["delta"]) < 1.0


def test_insufficient_when_no_polls_after():
    start = date(2026, 1, 1)
    polls = [_poll(start + timedelta(days=i), 45.0) for i in range(10)]
    event = {"id": "e1", "date": (start + timedelta(days=30)).isoformat(), "title": "Later", "type": "ad", "topics": []}
    assert A.analyze(polls, [event])["events"][0]["impact"]["signal"] == "insufficient"


def test_house_effects_are_recovered_and_centered():
    start = date(2026, 1, 1)
    polls = []
    for i in range(90):
        d = start + timedelta(days=i)
        polls.append(_poll(d, 47.0, pollster="High"))
        polls.append(_poll(d, 43.0, pollster="Low"))
    _, table = A.adjust_polls(polls)
    effects = {row["pollster"]: row["effect"] for row in table}
    assert effects["High"] > 1.8 and effects["Low"] < -1.8
    assert abs(effects["High"] + effects["Low"]) < 0.05


def test_average_is_causal():
    """A jump on day 30 must not show up in the average before day 30."""
    start = date(2026, 1, 1)
    polls = [_poll(start + timedelta(days=i), 40.0 if i < 30 else 50.0, pollster=f"P{i % 3}") for i in range(40)]
    trend = {row["date"]: row["value"] for row in A.analyze(polls, [])["trend"]}
    assert trend[(start + timedelta(days=29)).isoformat()] < 40.5


def test_demo_effects_are_recovered():
    _, polls, events = build_demo()
    res = A.analyze(polls, events, "vote_share", "All", 14)
    truth = {e["title"]: e["effects"]["All"] for e in DEMO_EVENTS}
    pairs = [(truth[e["title"]], e["impact"]["delta"]) for e in res["events"] if e["impact"]["delta"] is not None]
    assert statistics.correlation([t for t, _ in pairs], [m for _, m in pairs]) > 0.7
    themes = {t["label"]: t["mean_delta"] for t in res["themes"]}
    assert themes["housing"] > 0 > themes["character"]


def test_analogs_prefer_matching_topics_and_shrink_toward_zero():
    _, polls, events = build_demo()
    scored = A.analyze(polls, events)["events"]
    out = A.find_analogs(scored, ["housing"], "policy")
    assert out["analogs"][0]["topics"] and "housing" in out["analogs"][0]["topics"]
    raw = [a["delta"] for a in out["analogs"]]
    assert min(raw) - 0.01 <= out["prior_mean"] <= max(raw) + 0.01
    assert out["range_80"][0] < out["prior_mean"] < out["range_80"][1]


def test_dimensions_and_metric_fallback():
    start = date(2026, 1, 1)
    polls = [_poll(start + timedelta(days=i), 40.0, metric="approval") for i in range(10)]
    res = A.analyze(polls, [], metric="vote_share")
    assert res["metric"] == "approval"
    assert res["stats"]["poll_count"] == 10
