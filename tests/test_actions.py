"""The draft revise loop and the store writer's hard limits, with the model and the stores stubbed out."""
import json
import types

import pytest

from steward import db, draft, llm
from steward.act import writer


def _con(tmp_path):
    con = db.connect(tmp_path / "t.db")
    con.execute("INSERT INTO items(id,store,package,rating,lang,text,synthetic) VALUES "
                "('R-test000001','play','com.ruicodex.koidrift',2,'en','Too many ads after every level',0)")
    con.commit()
    return con


def _fake_chat(replies):
    calls = []

    def chat(provider, model, messages, **kw):
        calls.append(messages)
        data = replies[len(calls) - 1]
        return types.SimpleNamespace(data=data, text=json.dumps(data), cost_usd=0.001)
    return chat, calls


def test_verifier_findings_drive_one_revision(tmp_path, monkeypatch):
    con = _con(tmp_path)
    bad = {"reply_text": "Sorry! We will refund you tomorrow.", "language": "en", "cites": [], "promises": []}
    good = {"reply_text": "Thanks for telling us; we are looking at how often ads appear between levels.",
            "language": "en", "cites": ["R-test000001"], "promises": []}
    chat, calls = _fake_chat([bad, good])
    monkeypatch.setattr(llm, "chat", chat)
    out = draft.draft_reply("R-test000001", con=con)
    assert out["problems"] == [] and out["attempts"] == 2
    # the second request carries the verifier's findings back to the model
    assert "verifier rejected" in calls[1][-1]["content"] and "promises" in calls[1][-1]["content"]
    row = con.execute("SELECT status, attempts FROM drafts WHERE id=?", (out["draft_id"],)).fetchone()
    att = json.loads(row["attempts"])
    assert row["status"] == "pending" and len(att) == 2 and att[0]["problems"] and not att[1]["problems"]


def test_draft_still_blocked_after_the_revision_budget(tmp_path, monkeypatch):
    con = _con(tmp_path)
    bad = {"reply_text": "Refund coming tomorrow!", "language": "en", "cites": [], "promises": ["refund"]}
    chat, calls = _fake_chat([bad] * draft.MAX_ATTEMPTS)
    monkeypatch.setattr(llm, "chat", chat)
    out = draft.draft_reply("R-test000001", con=con)
    assert out["problems"] and len(calls) == draft.MAX_ATTEMPTS
    assert con.execute("SELECT status FROM drafts").fetchone()[0] == "rejected_by_verifier"


def _approved(con, store):
    con.execute("UPDATE items SET store=? WHERE id='R-test000001'", (store,))
    con.execute("INSERT INTO drafts(item_id,kind,lang,text,cites,verifier,status) VALUES "
                "('R-test000001','reply','en','Thanks, we are looking into it.','[]','[]','approved')")
    con.commit()
    return con.execute("SELECT MAX(id) FROM drafts").fetchone()[0]


def test_only_approved_drafts_can_be_posted(tmp_path):
    con = _con(tmp_path)
    con.execute("INSERT INTO drafts(item_id,kind,lang,text,status) VALUES ('R-test000001','reply','en','x','pending')")
    con.commit()
    with pytest.raises(PermissionError):
        writer.post(1, actor="test", con=con)


def test_app_store_posting_is_disabled_even_in_live_mode(tmp_path, monkeypatch):
    con = _con(tmp_path)
    did = _approved(con, "appstore")
    monkeypatch.setattr(writer.reidmap, "resolve", lambda pid: ("appstore", "com.ruicodex.koidrift", "123"))
    monkeypatch.setenv("STEWARD_LIVE", "1")
    with pytest.raises(PermissionError, match="read-only"):
        writer.post(did, actor="test", con=con)


def test_dry_run_is_the_default(tmp_path, monkeypatch):
    con = _con(tmp_path)
    did = _approved(con, "play")
    monkeypatch.setattr(writer.reidmap, "resolve", lambda pid: ("play", "com.ruicodex.koidrift", "gp:abc"))
    monkeypatch.delenv("STEWARD_LIVE", raising=False)
    assert writer.post(did, actor="test", con=con)["mode"] == "dry-run"
    assert con.execute("SELECT action FROM audit").fetchone()[0] == "post-dry-run"
