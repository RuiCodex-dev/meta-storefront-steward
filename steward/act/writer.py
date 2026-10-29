"""The only code that writes to a store, and the only reader of the re-identification map.

A reply is posted only when ALL of these hold:
  1. a human approved this exact draft in the queue (status 'approved'),
  2. the verifier found no problem with the final text,
  3. live mode is switched on for this process (STEWARD_LIVE=1); otherwise it is a logged dry run.
Every attempt, dry or live, is written to the audit table.
"""
from __future__ import annotations

import datetime as dt
import json
import os

from .. import db
from ..privacy import reidmap, scan


def _audit(con, actor: str, action: str, target: str, detail: dict) -> None:
    con.execute("INSERT INTO audit(ts,actor,action,target,detail) VALUES (?,?,?,?,?)",
                (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), actor, action, target,
                 json.dumps(detail, ensure_ascii=False)))
    con.commit()


def post(draft_id: int, actor: str, con=None) -> dict:
    con = con or db.connect()
    d = con.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if d is None or d["status"] != "approved":
        raise PermissionError("only an approved draft can be posted")
    text = d["edited_text"] or d["text"]
    if scan(text) or len(text) > 350:   # Play's limit; App Store posting is disabled below
        raise ValueError("final text failed the outbound check; not posted")
    live = os.environ.get("STEWARD_LIVE") == "1"
    target = reidmap.resolve(d["item_id"])
    if target is None and live:
        raise LookupError("no store review behind this pseudonym (synthetic item?)")
    if not live:
        if target is None:   # demo database / synthetic item: show what would happen, with nothing to send to
            pkg = con.execute("SELECT package FROM items WHERE id=?", (d["item_id"],)).fetchone()
            result = {"mode": "dry-run", "store": "none (synthetic review)", "package": pkg[0] if pkg else None,
                      "chars": len(text)}
        else:
            result = {"mode": "dry-run", "store": target[0], "package": target[1], "chars": len(text)}
        store = result["store"]
    elif (store := target[0]) == "play":
        package, review_id = target[1], target[2]
        from ..connectors import play
        r = play.publisher().reviews().reply(packageName=package, reviewId=review_id,
                                             body={"replyText": text}).execute()
        result = {"mode": "live", "store": store, "package": package, "result": r.get("result", {})}
    elif store == "appstore":
        # The studio's App Store Connect access is read-only while its iOS freeze lasts; no write path exists.
        raise PermissionError("App Store replies are disabled: App Store Connect is used read-only")
    else:
        raise ValueError(f"unknown store {store}")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    con.execute("UPDATE drafts SET posted_at=?, post_result=?, status=? WHERE id=?",
                (now, json.dumps(result), "posted" if live else "approved", draft_id))
    con.commit()
    _audit(con, actor, "post-live" if live else "post-dry-run", f"draft:{draft_id}", result)
    return result
