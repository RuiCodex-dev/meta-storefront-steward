"""Pull every store source, pseudonymise and scrub, and write the clean database.

Raw responses are saved under data/raw (git-ignored, never sent anywhere). Each review gets an HMAC
pseudonym; the mapping back to the store review id goes only into the re-identification map, which is
read by exactly one function: the approved-reply writer.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
from pathlib import Path

import httpx

from .. import apps, config, db
from ..privacy import pseudo, reidmap
from ..privacy.scrub import scrub



def _play_bucket() -> str:
    """The developer account's review-export bucket, kept outside the repository."""
    return json.loads((config.KEYS_DIR / "storefront-steward" / "play.json").read_text(encoding="utf-8"))["review_bucket"]


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _save_raw(kind: str, name: str, payload) -> None:
    p = config.RAW / kind
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def _upsert_item(con, rec: dict) -> None:
    cols = ",".join(rec)
    ph = ",".join("?" * len(rec))
    con.execute(f"INSERT OR REPLACE INTO items({cols}) VALUES ({ph})", tuple(rec.values()))


# ---------------------------------------------------------------- Play monthly CSV (full history)
def _gcs_token() -> str:
    from google.oauth2 import service_account
    import google.auth.transport.requests as tr
    cr = service_account.Credentials.from_service_account_file(
        str(config.PLAY_SERVICE_ACCOUNT), scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
    cr.refresh(tr.Request())
    return cr.token


def download_play_csv() -> list[Path]:
    h = {"Authorization": "Bearer " + _gcs_token()}
    base = f"https://storage.googleapis.com/storage/v1/b/{_play_bucket()}/o"
    items = httpx.get(base, params={"prefix": "reviews/"}, headers=h, timeout=60).json().get("items", [])
    out = config.RAW / "play_csv"
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for it in items:
        name = it["name"].split("/")[-1]
        pkg = re.match(r"reviews_(.+)_\d{6}\.csv$", name)
        if not pkg or not apps.is_included(pkg.group(1)):
            continue                                   # excluded apps are never downloaded
        data = httpx.get(f"{base}/{it['name'].replace('/', '%2F')}", params={"alt": "media"}, headers=h,
                         timeout=60).content
        (out / name).write_bytes(data)
        paths.append(out / name)
    return paths


def _ms_to_iso(ms: str | None) -> str | None:
    if not ms:
        return None
    return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).isoformat(timespec="seconds")


def ingest_play_csv(con, paths: list[Path]) -> int:
    n = 0
    for p in paths:
        for row in csv.DictReader(io.StringIO(p.read_bytes().decode("utf-16"))):
            pkg = row["Package Name"]
            if not apps.is_included(pkg):
                continue
            text = (row.get("Review Text") or "").strip()
            if not text:
                continue                                # rating-only rows carry no feedback to triage
            link = row.get("Review Link") or ""
            m = re.search(r"reviewId=([^&]+)", link)
            store_id = m.group(1) if m else hashlib.sha256(
                f"{row['Review Submit Millis Since Epoch']}|{row.get('Device')}|{text}".encode()).hexdigest()
            pid = pseudo.review_id("play", pkg, store_id)
            reidmap.put(pid, "play", pkg, store_id)
            clean, hits = scrub(text)
            title, th = scrub(row.get("Review Title") or "")
            reply, _ = scrub(row.get("Developer Reply Text") or "")
            _upsert_item(con, dict(
                id=pid, store="play", package=pkg, kind="review",
                rating=int(row["Star Rating"]) if row.get("Star Rating") else None,
                lang=row.get("Reviewer Language") or None, title=title or None, text=clean, text_en=None,
                version_code=int(row["App Version Code"]) if (row.get("App Version Code") or "").isdigit() else None,
                version_name=row.get("App Version Name") or None, device=row.get("Device") or None,
                os_version=None, territory=None,
                created_at=_ms_to_iso(row.get("Review Submit Millis Since Epoch")),
                modified_at=_ms_to_iso(row.get("Review Last Update Millis Since Epoch")),
                dev_reply=reply or None, dev_reply_at=_ms_to_iso(row.get("Developer Reply Millis Since Epoch")),
                scrub_hits=json.dumps(hits + th), synthetic=0))
            n += 1
    con.commit()
    return n


# ---------------------------------------------------------------- Play API (last ~7 days, has translations)
def ingest_play_api(con) -> int:
    from . import play
    svc, n = play.publisher(), 0
    for app in apps.included():
        try:
            revs = play.list_reviews(app.package, svc)
        except play.NotAccessible:
            continue
        if revs:
            _save_raw("play_api", f"{app.package}-{dt.date.today()}.json", revs)
        for r in revs:
            uc = (r.get("comments") or [{}])[0].get("userComment") or {}
            dc = next((c.get("developerComment") for c in r.get("comments", []) if c.get("developerComment")), None)
            author = r.get("authorName")
            raw_text = (uc.get("originalText") or uc.get("text") or "").strip()
            if not raw_text:
                continue
            pid = pseudo.review_id("play", app.package, r["reviewId"])
            reidmap.put(pid, "play", app.package, r["reviewId"])
            clean, hits = scrub(raw_text, author)
            en, _ = scrub(uc.get("text") if uc.get("originalText") else None, author)
            reply, _ = scrub((dc or {}).get("text"), author)
            _upsert_item(con, dict(
                id=pid, store="play", package=app.package, kind="review", rating=uc.get("starRating"),
                lang=uc.get("reviewerLanguage"), title=None, text=clean, text_en=en or None,
                version_code=uc.get("appVersionCode"), version_name=uc.get("appVersionName"),
                device=(uc.get("deviceMetadata") or {}).get("productName") or uc.get("device"),
                os_version=str(uc.get("androidOsVersion") or "") or None, territory=None,
                created_at=None,
                modified_at=dt.datetime.fromtimestamp(int((uc.get("lastModified") or {}).get("seconds", 0)),
                                                      dt.timezone.utc).isoformat(timespec="seconds"),
                dev_reply=reply or None, dev_reply_at=None, scrub_hits=json.dumps(hits), synthetic=0))
            n += 1
    con.commit()
    return n


# ---------------------------------------------------------------- App Store Connect (full history)
def _asc_package(bundle: str) -> str | None:
    """ASC bundle ids differ in case/underscores from Play package names; map to our registry."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    for a in apps.APPS:
        if norm(a.package) == norm(bundle):
            return a.package
    return None


def ingest_asc(con) -> int:
    from . import asc
    n = 0
    for app in asc.apps():
        pkg = _asc_package(app["attributes"]["bundleId"])
        if not pkg or not apps.is_included(pkg):
            continue
        revs = asc.customer_reviews(app["id"])
        if revs:
            _save_raw("asc", f"{pkg}-{dt.date.today()}.json", revs)
        for r in revs:
            at = r["attributes"]
            pid = pseudo.review_id("appstore", pkg, r["id"])
            reidmap.put(pid, "appstore", pkg, r["id"])
            nick = at.get("reviewerNickname")
            clean, hits = scrub(at.get("body"), nick)
            title, th = scrub(at.get("title"), nick)
            resp = (r.get("_response") or {}).get("attributes") or {}
            reply, _ = scrub(resp.get("responseBody"), nick)
            _upsert_item(con, dict(
                id=pid, store="appstore", package=pkg, kind="review", rating=at.get("rating"), lang=None,
                title=title or None, text=clean, text_en=None, version_code=None, version_name=None, device=None,
                os_version=None, territory=at.get("territory"), created_at=at.get("createdDate"),
                modified_at=at.get("createdDate"), dev_reply=reply or None,
                dev_reply_at=resp.get("lastModifiedDate"), scrub_hits=json.dumps(hits + th), synthetic=0))
            n += 1
    con.commit()
    return n


# ---------------------------------------------------------------- crash / ANR issues and releases
def ingest_vitals(con, days: int = 90) -> int:
    from . import play
    svc, n = play.reporting(), 0
    for app in apps.included():
        try:
            issues = play.error_issues(app.package, days, svc)
        except Exception:      # an app without vitals data answers 403/404; that is not an error here
            continue
        for i in issues:
            iid = i.get("name", "").split("/")[-1]
            con.execute("INSERT OR REPLACE INTO crash_issues VALUES (?,?,?,?,?,?,?,?,?,?)", (
                app.package, iid, i.get("type"), i.get("cause"), i.get("location"),
                int(i["firstAppVersion"]["versionCode"]) if i.get("firstAppVersion") else None,
                int(i["lastAppVersion"]["versionCode"]) if i.get("lastAppVersion") else None,
                int(i.get("distinctUsers") or 0), int(i.get("errorReportCount") or 0), _now()))
            n += 1
    con.commit()
    return n


def ingest_releases(con) -> int:
    from . import play
    svc, n = play.publisher(), 0
    for app in apps.included():
        try:
            tracks = play.list_tracks(app.package, svc)
        except Exception:
            continue
        for t in tracks:
            for rel in t.get("releases", []):
                notes = {x.get("language"): x.get("text") for x in rel.get("releaseNotes", [])}
                con.execute("INSERT OR REPLACE INTO releases VALUES (?,?,?,?,?,?,?)", (
                    app.package, t.get("track"), rel.get("name") or "", rel.get("status"),
                    json.dumps(rel.get("versionCodes", [])), json.dumps(notes, ensure_ascii=False), _now()))
                n += 1
    con.commit()
    return n


def run_all() -> dict:
    config.ensure_dirs()
    con = db.connect()
    out = {}
    out["play_csv_files"] = len(paths := download_play_csv())
    out["play_csv_reviews"] = ingest_play_csv(con, paths)
    out["play_api_reviews"] = ingest_play_api(con)
    out["asc_reviews"] = ingest_asc(con)
    out["crash_issues"] = ingest_vitals(con)
    out["releases"] = ingest_releases(con)
    out["items_total"] = con.execute("SELECT COUNT(*) FROM items WHERE synthetic=0").fetchone()[0]
    return out
