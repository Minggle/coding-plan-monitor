"""JSON 配置读写。默认路径 %APPDATA%/coding-plan-monitor/config.json。"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, asdict

DEFAULT_POLL_INTERVAL_SEC = 300  # 5 分钟

PROVIDERS = ("kimi", "glm", "volcano", "custom")


def default_config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "coding-plan-monitor")


@dataclass
class CustomSpec:
    """自定义供应商的请求与字段映射。headers 中 {KEY} 会被替换为账号 key。

    paths 中每个窗口映射到响应 JSON 内的取值路径（点号分隔），
    值可以是数字、百分数或 {"percent": ..., "used": ..., "limit": ..., "reset": ...}。
    """

    url: str = ""
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    paths: dict[str, str] = field(default_factory=dict)  # {"5h": "...", "7d": "...", "monthly": "..."}


@dataclass
class Account:
    provider: str = "kimi"
    name: str = ""
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    # kimi / glm / custom
    key: str = ""
    # glm 站点：open.bigmodel.cn | api.z.ai
    site: str = "open.bigmodel.cn"
    # volcano 控制台凭证
    cookie: str = ""
    csrf_token: str = ""
    web_id: str = ""
    project_name: str = "default"
    # custom
    custom: CustomSpec = field(default_factory=CustomSpec)

    @property
    def display_name(self) -> str:
        return self.name or f"{self.provider}-{self.id}"


@dataclass
class Settings:
    poll_interval_sec: int = DEFAULT_POLL_INTERVAL_SEC
    display_mode: str = "tray"          # tray | strip
    tray_account_id: str = "auto"       # auto = 最接近限额的账号
    strip_x: int | None = None
    strip_y: int | None = None
    strip_locked: bool = False
    autostart: bool = False


@dataclass
class Config:
    accounts: list[Account] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    def enabled_accounts(self) -> list[Account]:
        return [a for a in self.accounts if a.enabled]

    def account_by_id(self, account_id: str) -> Account | None:
        for a in self.accounts:
            if a.id == account_id:
                return a
        return None


def _account_from_dict(d: dict) -> Account:
    d = dict(d)
    custom = d.pop("custom", None) or {}
    known = {f for f in Account.__dataclass_fields__} - {"custom"}
    acc = Account(**{k: v for k, v in d.items() if k in known})
    acc.custom = CustomSpec(**{k: v for k, v in custom.items() if k in CustomSpec.__dataclass_fields__})
    return acc


def load_config(config_dir: str | None = None) -> Config:
    path = os.path.join(config_dir or default_config_dir(), "config.json")
    if not os.path.exists(path):
        return Config()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cfg = Config()
    cfg.accounts = [_account_from_dict(a) for a in raw.get("accounts", [])]
    s = raw.get("settings", {})
    cfg.settings = Settings(**{k: v for k, v in s.items() if k in Settings.__dataclass_fields__})
    return cfg


def save_config(cfg: Config, config_dir: str | None = None) -> str:
    config_dir = config_dir or default_config_dir()
    os.makedirs(config_dir, exist_ok=True)
    path = os.path.join(config_dir, "config.json")
    raw = {
        "accounts": [asdict(a) for a in cfg.accounts],
        "settings": asdict(cfg.settings),
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path
