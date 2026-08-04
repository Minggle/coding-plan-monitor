"""从粘贴的 curl 命令中提取火山控制台所需凭证：Cookie、x-csrf-token、x-web-id。

支持 Windows（curl "url" -H "..."）与 bash（curl 'url' -H '...'）两种引号风格，
以及 ^ 续行（cmd）和 \\ 续行（bash）。若 Cookie 中含 csrfToken=xxx 且头部未给
x-csrf-token，则自动从 Cookie 提取。
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field


@dataclass
class CurlCredentials:
    cookie: str = ""
    csrf_token: str = ""
    web_id: str = ""
    url: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)


def _normalize(text: str) -> str:
    # cmd 续行 ^\n、bash 续行 \\\n
    text = re.sub(r"\^\r?\n", " ", text)
    text = re.sub(r"\\\r?\n", " ", text)
    return text.strip()


def _split_tokens(text: str) -> list[str]:
    # 先把双引号内内容原样保留（shlex posix 会处理引号）
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


def parse_curl(text: str) -> CurlCredentials:
    text = _normalize(text)
    tokens = _split_tokens(text)
    cred = CurlCredentials()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("http"):
            cred.url = tok
        elif tok in ("-H", "--header") and i + 1 < len(tokens):
            header = tokens[i + 1]
            i += 1
            if ":" in header:
                k, v = header.split(":", 1)
                k, v = k.strip().lower(), v.strip()
                if k == "cookie":
                    cred.cookie = v
                elif k == "x-csrf-token":
                    cred.csrf_token = v
                elif k == "x-web-id":
                    cred.web_id = v
                else:
                    cred.extra_headers[k] = v
        elif tok in ("-b", "--cookie") and i + 1 < len(tokens):
            cred.cookie = tokens[i + 1].strip()
            i += 1
        i += 1

    if not cred.csrf_token and cred.cookie:
        m = re.search(r"(?:^|;\s*)csrfToken=([^;]+)", cred.cookie)
        if m:
            cred.csrf_token = m.group(1).strip()

    return cred
