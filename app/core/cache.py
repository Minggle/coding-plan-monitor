"""最近一次成功快照的持久化缓存。失败时展示旧数据 + 时间戳。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

from app.core.config import default_config_dir
from app.core.models import UsageSnapshot, UsageWindow, WindowType


def _cache_path(config_dir: str | None) -> str:
    return os.path.join(config_dir or default_config_dir(), "cache.json")


def save_snapshots(snapshots: dict[str, UsageSnapshot], config_dir: str | None = None) -> None:
    """key = account_id。"""
    path = _cache_path(config_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = {}
    for account_id, snap in snapshots.items():
        raw[account_id] = {
            "provider": snap.provider,
            "account_name": snap.account_name,
            "fetched_at": snap.fetched_at,
            "windows": [
                {
                    "window_type": w.window_type.value,
                    "percent": w.percent,
                    "used": w.used,
                    "limit": w.limit,
                    "reset_at": w.reset_at,
                }
                for w in snap.windows
            ],
        }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_snapshots(config_dir: str | None = None) -> dict[str, UsageSnapshot]:
    path = _cache_path(config_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    result = {}
    for account_id, d in raw.items():
        try:
            windows = [
                UsageWindow(
                    window_type=WindowType(w["window_type"]),
                    percent=w.get("percent"),
                    used=w.get("used"),
                    limit=w.get("limit"),
                    reset_at=w.get("reset_at"),
                )
                for w in d.get("windows", [])
            ]
            result[account_id] = UsageSnapshot(
                provider=d.get("provider", ""),
                account_name=d.get("account_name", ""),
                windows=windows,
                fetched_at=d.get("fetched_at", 0),
            )
        except (KeyError, ValueError):
            continue
    return result
