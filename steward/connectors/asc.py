"""App Store Connect, read-only: customer reviews and versions. ES256 JWT built at call time."""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import jwt

API = "https://api.appstoreconnect.apple.com"


def _env(name: str) -> str:
    v = os.environ.get(name)
    if not v and os.name == "nt":
        import winreg  # user environment variables set after the shell started
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            v = winreg.QueryValueEx(k, name)[0]
    if not v:
        raise RuntimeError(f"{name} is not set")
    return v


def _token() -> str:
    key = Path(_env("APP_STORE_P8_PATH")).read_text(encoding="utf-8")
    now = int(time.time())
    return jwt.encode({"iss": _env("APP_STORE_ISSUER_ID"), "iat": now, "exp": now + 1100,
                       "aud": "appstoreconnect-v1"}, key, algorithm="ES256",
                      headers={"kid": _env("APP_STORE_KEY_ID"), "typ": "JWT"})


def _get(path: str, params: dict | None = None) -> dict:
    r = httpx.get(API + path if path.startswith("/") else path, params=params,
                  headers={"Authorization": f"Bearer {_token()}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def apps() -> list[dict]:
    out, url, params = [], "/v1/apps", {"limit": 200, "fields[apps]": "bundleId,name"}
    while url:
        d = _get(url, params)
        out += d.get("data", [])
        url, params = (d.get("links") or {}).get("next"), None
    return out


def customer_reviews(app_id: str, max_pages: int = 20) -> list[dict]:
    out, url = [], f"/v1/apps/{app_id}/customerReviews"
    params = {"limit": 200, "sort": "-createdDate", "include": "response"}
    included = {}
    for _ in range(max_pages):
        d = _get(url, params)
        for inc in d.get("included", []):
            included[inc["id"]] = inc
        for rev in d.get("data", []):
            rel = ((rev.get("relationships") or {}).get("response") or {}).get("data")
            rev["_response"] = included.get(rel["id"]) if rel else None
            out.append(rev)
        url, params = (d.get("links") or {}).get("next"), None
        if not url:
            break
    return out


def versions(app_id: str) -> list[dict]:
    d = _get(f"/v1/apps/{app_id}/appStoreVersions",
             {"limit": 50, "fields[appStoreVersions]": "versionString,appStoreState,createdDate,earliestReleaseDate"})
    return d.get("data", [])
