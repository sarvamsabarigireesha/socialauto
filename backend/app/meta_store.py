"""Persist Meta (Facebook/Instagram) app credentials on disk.

Env vars remain the production source of truth when set. The in-app wizard
writes DATA_DIR/meta_app.json so a self-hosted install can go live without
redeploying. Overlay values win when they are non-empty.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import DATA_DIR

META_FILE = Path(DATA_DIR) / "meta_app.json"

_DEFAULTS = {
    "app_id": "",
    "app_secret": "",
    "verify_token": "socialauto-verify-token",
    "graph_version": "v25.0",
    "mock_mode": None,          # None = follow MOCK_MODE env
    "app_public_url": "",
    "config_id": "",            # Facebook Login for Business configuration id (optional)
}

_cache: dict = {"t": 0.0, "data": None}


def _read_file() -> dict:
    if not META_FILE.exists():
        return {}
    try:
        data = json.loads(META_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_overlay(force: bool = False) -> dict:
    now = time.time()
    if not force and _cache["data"] is not None and (now - _cache["t"]) < 1.0:
        return _cache["data"]
    merged = dict(_DEFAULTS)
    merged.update({k: v for k, v in _read_file().items() if k in _DEFAULTS})
    _cache["t"] = now
    _cache["data"] = merged
    return merged


def save_overlay(**kwargs) -> dict:
    current = dict(_DEFAULTS)
    current.update(_read_file())
    for k, v in kwargs.items():
        if k not in _DEFAULTS:
            continue
        if k == "mock_mode":
            current[k] = None if v is None else bool(v)
        else:
            current[k] = ("" if v is None else str(v)).strip()
    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(json.dumps(current, indent=2), encoding="utf-8")
    _cache["t"] = 0.0
    _cache["data"] = None
    return load_overlay(force=True)


def _first(*vals) -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


def meta_app_id() -> str:
    ov = load_overlay()
    return _first(ov.get("app_id"), os.getenv("META_APP_ID", ""))


def meta_app_secret() -> str:
    ov = load_overlay()
    return _first(ov.get("app_secret"), os.getenv("META_APP_SECRET", ""))


def meta_verify_token() -> str:
    ov = load_overlay()
    return _first(ov.get("verify_token"), os.getenv("META_VERIFY_TOKEN", "socialauto-verify-token")) \
        or "socialauto-verify-token"


def meta_graph_version() -> str:
    ov = load_overlay()
    v = _first(ov.get("graph_version"), os.getenv("META_GRAPH_VERSION", "v25.0")) or "v25.0"
    return v if v.startswith("v") else f"v{v}"


def meta_config_id() -> str:
    ov = load_overlay()
    return _first(ov.get("config_id"), os.getenv("META_CONFIG_ID", ""))


def app_public_url() -> str:
    ov = load_overlay()
    return _first(ov.get("app_public_url"), os.getenv("APP_PUBLIC_URL", "")).rstrip("/")


def mock_mode() -> bool:
    ov = load_overlay()
    if ov.get("mock_mode") is not None:
        return bool(ov["mock_mode"])
    return os.getenv("MOCK_MODE", "true").lower() == "true"


def meta_configured() -> bool:
    return bool(meta_app_id() and meta_app_secret())


META_SCOPES = (
    "public_profile,"
    "pages_show_list,"
    "pages_read_engagement,"
    "pages_manage_posts,"
    "pages_manage_engagement,"
    "pages_manage_metadata,"
    "instagram_basic,"
    "instagram_content_publish,"
    "instagram_manage_comments,"
    "instagram_manage_insights,"
    "business_management"
)

THREADS_SCOPES = "threads_basic,threads_content_publish"
