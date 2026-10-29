"""Run-to-run memory and the engineering-ticket verifier, offline."""
import json
import types

from fastapi.testclient import TestClient

from steward import db, llm, memory, ticket
from steward.reason import _crash_key


def _cluster(con, cid, run, t, items, crashes, title="x"):
    con.execute("INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, "com.ruicodex.a", run, title, "s", 4, json.dumps(items), "[]", json.dumps(crashes), "unknown",
                 json.dumps({"evidence": [], "links": [], "problems": [], "action": "fix it"}), "verified", None, t))


def test_new_ongoing_and_quiet_are_matched_by_evidence_not_titles(tmp_path):
    con = db.connect(tmp_path / "m.db")
    _cluster(con, "K-old1", "r1", "2026-10-27T08:00:00", ["R-1", "R-2"], ["C-a"], "Audio crash")
    _cluster(con, "K-old2", "r1", "2026-10-27T08:00:00", ["R-9"], [], "Battery")
    _cluster(con, "K-new1", "r2", "2026-10-28T08:00:00", ["R-1", "R-2", "R-3"], ["C-a"], "Shared SoLoud crash")
    _cluster(con, "K-new2", "r2", "2026-10-28T08:00:00", ["R-7"], [], "Battery")      # same title, other evidence
    m = memory.compare(con)
    assert m["run"] == "r2" and m["previous"] == "r1"
    assert m["issues"]["K-new1"]["status"] == "ongoing" and m["issues"]["K-new1"]["new_signals"] == 1
    assert m["issues"]["K-new2"]["status"] == "new"
    assert [q["issue_id"] for q in m["quiet"]] == ["K-old2"]
    assert set(memory.same_issue_ids(con, "K-new1")) == {"K-new1", "K-old1"}


def test_first_pass_has_no_comparison(tmp_path):
    con = db.connect(tmp_path / "f.db")
    _cluster(con, "K-1", "r1", "2026-10-27T08:00:00", ["R-1"], [])
    assert memory.compare(con)["issues"]["K-1"]["status"] == "first pass"


def _ticket(**kw):
    t = {"title": "Native audio crash", "apps": ["com.ruicodex.a"], "affected_versions": ["versionCode 41"],
         "symptoms": "s", "user_impact": "u", "suspected_component": "SoLoud", "first_step": "f",
         "evidence_ids": ["R-1"]}
    t.update(kw)
    return t


def test_ticket_verifier_rules():
    ok = dict(ids={"R-1", "C-a"}, packages={"com.ruicodex.a"}, versions={"41", "1.4.2"})
    assert ticket.verify(_ticket(), **ok) == []
    assert ticket.verify(_ticket(affected_versions=["1.4.2"]), **ok) == []
    assert any("versions not in the evidence" in p for p in ticket.verify(_ticket(affected_versions=["57"]), **ok))
    assert any("outside this issue" in p for p in ticket.verify(_ticket(apps=["com.other"]), **ok))
    assert any("not evidence" in p for p in ticket.verify(_ticket(evidence_ids=["R-404"]), **ok))
    assert any("no evidence" in p for p in ticket.verify(_ticket(evidence_ids=[]), **ok))
    assert any("personal data" in p for p in ticket.verify(_ticket(symptoms="mail dev@example.com"), **ok))


def test_ticket_draft_is_revised_then_queued_and_exported(tmp_path, monkeypatch):
    con = db.connect(tmp_path / "t.db")
    con.execute("INSERT INTO items(id,store,package,rating,lang,text,version_name,version_code,synthetic) VALUES "
                "('R-1','play','com.ruicodex.a',1,'en','crashes on start','1.4.2',41,0)")
    con.execute("INSERT INTO crash_issues VALUES ('com.ruicodex.a','iss1','CRASH','SIGSEGV','libsoloud.so',40,41,9,"
                "30,'2026-10-27')")
    _cluster(con, "K-1", "r1", "2026-10-27T08:00:00", ["R-1"], [_crash_key("com.ruicodex.a", "iss1")])
    con.commit()
    replies = [_ticket(affected_versions=["99"]), _ticket()]
    calls = []

    def chat(provider, model, messages, **kw):
        calls.append(messages)
        return types.SimpleNamespace(data=replies[len(calls) - 1], text="{}", cost_usd=0.002)
    monkeypatch.setattr(llm, "chat", chat)
    out = ticket.draft_ticket("K-1", con=con)
    assert out["problems"] == [] and out["attempts"] == 2 and "versions not in the evidence" in calls[1][-1]["content"]
    con.execute("UPDATE drafts SET status='approved' WHERE id=?", (out["draft_id"],))
    con.commit()
    path = ticket.export(out["draft_id"], con=con)
    text = open(path, encoding="utf-8").read()
    assert text.startswith("# Native audio crash") and "K-1" in text


def test_queue_page_shows_tickets_and_replies(tmp_path, monkeypatch):
    from steward.web import app as webapp
    con = db.connect(tmp_path / "w.db")
    _cluster(con, "K-1", "r1", "2026-10-27T08:00:00", ["R-1"], [], "Shared audio crash")
    con.execute("INSERT INTO drafts(item_id,cluster_id,kind,lang,text,cites,verifier,status,attempts) VALUES "
                "('K-1','K-1','ticket','en','# Shared audio crash','[]','[]','pending',?)",
                (json.dumps([{"text": "a", "problems": ["versions not in the evidence: ['99']"]},
                             {"text": "b", "problems": []}]),))
    con.commit()
    con.close()
    monkeypatch.setattr(webapp, "_con", lambda: db.connect(tmp_path / "w.db"))
    r = TestClient(webapp.app).get("/queue")
    assert r.status_code == 200 and "engineering ticket" in r.text and "revised 1× after the verifier" in r.text
