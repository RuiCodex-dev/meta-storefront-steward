import json

from steward.web.agentview import summarize, timeline


def test_cluster_summary_names_the_cross_app_issue():
    r = {"issues": [{"title": "Shared audio crash", "severity": 4, "apps": ["A", "B", "C"], "verified": True,
                     "since_last_pass": {"status": "new"}},
                    {"title": "Ads", "severity": 2, "apps": ["A"], "verified": True,
                     "since_last_pass": {"status": "ongoing"}}],
         "quiet_since_last_pass": ["Battery"], "context_tokens": 14179, "cached_tokens": 0}
    s = summarize("cluster_issues", json.dumps(r))
    assert "2 issues" in s and "1 new" in s and "1 ongoing" in s and "1 quiet" in s and "Shared audio crash" in s


def test_errors_and_garbage_are_shown_not_hidden():
    assert summarize("draft_ticket", json.dumps({"error": "unknown issue id K-x"})).startswith("error:")
    assert summarize("sync_store", "not json") == "not json"


def test_timeline_marks_done_only_with_a_report():
    rows = [{"tool": "plan", "result": "checking", "cost_usd": 0.002, "ts": "2026-10-29T02:00:00+00:00"},
            {"tool": "studio_overview", "args": "{}", "result": "{}", "cost_usd": 0.0, "ts": "2026-10-29T02:00:03+00:00"}]
    v = timeline(rows)
    assert not v["done"] and v["tools"] == 1 and v["seconds"] == 3
    v = timeline(rows + [{"tool": "report", "result": "all good", "cost_usd": 0.0, "ts": "2026-10-29T02:00:09+00:00"}])
    assert v["done"] and v["report"] == "all good"
