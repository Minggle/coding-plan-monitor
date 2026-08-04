"""Provider 注册表与统一查询入口。"""

from __future__ import annotations

import json
import os
import time

import httpx

from app.core.config import Account, default_config_dir
from app.core.models import AccountResult, ErrorKind
from app.providers.base import Provider, ProviderError, default_client
from app.providers.custom import CustomProvider
from app.providers.glm import GlmProvider
from app.providers.kimi import KimiProvider
from app.providers.volcano import VolcanoProvider

PROVIDER_CLASSES: dict[str, type[Provider]] = {
    "kimi": KimiProvider,
    "glm": GlmProvider,
    "volcano": VolcanoProvider,
    "custom": CustomProvider,
}

PROVIDER_LABELS = {
    "kimi": "Kimi",
    "glm": "GLM（智谱）",
    "volcano": "火山引擎",
    "custom": "自定义",
}


def get_provider(name: str) -> Provider:
    cls = PROVIDER_CLASSES.get(name)
    if cls is None:
        raise ValueError(f"未知供应商：{name}")
    return cls()


def _dump_raw(provider: Provider, account: Account, config_dir: str | None) -> None:
    """把最近一次原始响应写入 logs/ 供诊断（不含凭证）。"""
    raw = getattr(provider, "last_raw", None)
    if not raw:
        return
    try:
        logs = os.path.join(config_dir or default_config_dir(), "logs")
        os.makedirs(logs, exist_ok=True)
        path = os.path.join(logs, f"{account.provider}-{account.id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"account": account.display_name, "at": time.time(), "raw": raw},
                      f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def fetch_account(account: Account, client: httpx.Client | None = None,
                  config_dir: str | None = None) -> AccountResult:
    """查询单个账号，永不抛异常，结果封装为 AccountResult。"""
    result = AccountResult(account_id=account.id, provider=account.provider, account_name=account.display_name)
    try:
        provider = get_provider(account.provider)
    except ValueError as e:
        result.error_kind = ErrorKind.PARSE
        result.error_msg = str(e)
        return result

    own_client = client is None
    client = client or default_client()
    try:
        result.snapshot = provider.fetch(account, client)
    except ProviderError as e:
        result.error_kind = e.kind
        result.error_msg = e.msg
    except Exception as e:  # 兜底，避免单账号异常拖垮轮询
        result.error_kind = ErrorKind.PARSE
        result.error_msg = f"未预期错误：{e}"
    finally:
        _dump_raw(provider, account, config_dir)
        if own_client:
            client.close()
    return result
