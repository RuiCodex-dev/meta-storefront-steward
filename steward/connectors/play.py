"""Google Play, read-only: reviews, release tracks, crash/ANR issues and vitals.

* reviews.list returns written reviews created or edited in roughly the last week.
* Release tracks are read through a temporary edit that is always DELETED, never committed, under the
  shared lock convention used by the studio's other Play agents (store-refresh README).
* Vitals come from the Play Developer Reporting API.

Nothing here writes to the store. Replies are posted only by steward/act/writer.py after a human approves.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import time
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .. import config

SCOPES = ["https://www.googleapis.com/auth/androidpublisher",
          "https://www.googleapis.com/auth/playdeveloperreporting"]
LOCKS = Path(os.environ.get(
    "STEWARD_PLAY_LOCKS",
    r"C:\Users\Admin\Desktop\Software\0RuiCodex Games & Apps\_store_refresh_2026-10\locks"))
AGENT = "rc35-storefront-steward"

_creds = None


def _credentials():
    global _creds
    if _creds is None:
        _creds = service_account.Credentials.from_service_account_file(str(config.PLAY_SERVICE_ACCOUNT), scopes=SCOPES)
    return _creds


def publisher():
    return build("androidpublisher", "v3", credentials=_credentials(), cache_discovery=False)


def reporting():
    return build("playdeveloperreporting", "v1beta1", credentials=_credentials(), cache_discovery=False)


class NotAccessible(Exception):
    """The service account cannot read this package (not ours, unpublished, or no permission)."""


def list_reviews(pkg: str, svc=None, max_pages: int = 50) -> list[dict]:
    svc = svc or publisher()
    out, token = [], None
    for _ in range(max_pages):
        kw = dict(packageName=pkg, maxResults=100, translationLanguage="en")
        if token:
            kw["token"] = token
        try:
            resp = svc.reviews().list(**kw).execute()
        except HttpError as e:
            if e.resp.status in (403, 404):
                raise NotAccessible(f"{pkg}: HTTP {e.resp.status}") from e
            raise
        out += resp.get("reviews", [])
        token = (resp.get("tokenPagination") or {}).get("nextPageToken")
        if not token:
            break
        time.sleep(1.0)
    return out


class _Lock:
    def __init__(self, pkg: str, wait_s: int = 300):
        self.path = LOCKS / f"play-{pkg}.lock"
        self.wait_s = wait_s

    def __enter__(self):
        deadline = time.time() + self.wait_s
        while True:
            try:
                self.path.mkdir(parents=True, exist_ok=False)
                (self.path / "owner").write_text(f"{AGENT} {dt.datetime.utcnow().isoformat()}Z read-only tracks\n")
                return self
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if age > 20 * 60:                 # stale per the shared convention
                    shutil.rmtree(self.path, ignore_errors=True)
                    continue
                if time.time() > deadline:
                    raise TimeoutError(f"lock {self.path.name} held by another agent")
                time.sleep(10)

    def __exit__(self, *exc):
        shutil.rmtree(self.path, ignore_errors=True)


def list_tracks(pkg: str, svc=None) -> list[dict]:
    """Read every track's releases through a throw-away edit that is deleted in a finally block."""
    svc = svc or publisher()
    with _Lock(pkg):
        edit = svc.edits().insert(packageName=pkg, body={}).execute()
        try:
            return svc.edits().tracks().list(packageName=pkg, editId=edit["id"]).execute().get("tracks", [])
        finally:
            try:
                svc.edits().delete(packageName=pkg, editId=edit["id"]).execute()
            except HttpError:
                pass


def error_issues(pkg: str, days: int = 90, svc=None) -> list[dict]:
    svc = svc or reporting()
    end = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - dt.timedelta(days=days)
    out, token = [], None
    while True:
        kw = dict(parent=f"apps/{pkg}", pageSize=50,
                  interval_startTime_year=start.year, interval_startTime_month=start.month,
                  interval_startTime_day=start.day, interval_endTime_year=end.year,
                  interval_endTime_month=end.month, interval_endTime_day=end.day)
        if token:
            kw["pageToken"] = token
        try:
            resp = svc.vitals().errors().issues().search(**kw).execute()
        except TypeError:
            # older discovery docs name the interval fields differently; fall back to no interval
            kw = dict(parent=f"apps/{pkg}", pageSize=50, **({"pageToken": token} if token else {}))
            resp = svc.vitals().errors().issues().search(**kw).execute()
        out += resp.get("errorIssues", [])
        token = resp.get("nextPageToken")
        if not token:
            return out


def rate_metric(pkg: str, metric: str, days: int = 60, svc=None) -> list[dict]:
    """metric: 'crashRate' or 'anrRate'. Daily rate per versionCode."""
    svc = svc or reporting()
    resource = {"crashRate": "crashRateMetricSet", "anrRate": "anrRateMetricSet"}[metric]
    end = dt.date.today() - dt.timedelta(days=2)
    start = end - dt.timedelta(days=days)
    body = {
        "timelineSpec": {"aggregationPeriod": "DAILY",
                         "startTime": {"year": start.year, "month": start.month, "day": start.day,
                                       "timeZone": {"id": "America/Los_Angeles"}},
                         "endTime": {"year": end.year, "month": end.month, "day": end.day,
                                     "timeZone": {"id": "America/Los_Angeles"}}},
        "dimensions": ["versionCode"],
        "metrics": [metric, "distinctUsers"],
        "pageSize": 1000,
    }
    getter = getattr(svc.vitals(), "crashrate" if metric == "crashRate" else "anrrate")()
    resp = getter.query(name=f"apps/{pkg}/{resource}", body=body).execute()
    return resp.get("rows", [])
