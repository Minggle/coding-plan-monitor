"""火山引擎 V4 签名（HMAC-SHA256，AWS SigV4 变体）。

四层派生密钥：kDate = HMAC(SK, date)，kRegion、kService、kSigning 依次派生。
canonical headers 顺序固定 host;x-date;x-content-sha256;content-type
（与线上服务兼容的实战格式，见 tests/test_volcano_sign.py 黄金向量）。
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote

CONTENT_TYPE = "application/json; charset=utf-8"
_SIGNED_HEADERS = "host;x-date;x-content-sha256;content-type"


def _uri_encode(s: str) -> str:
    return quote(s, safe="-_.~")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, data: str) -> bytes:
    return hmac.new(key, data.encode("utf-8"), hashlib.sha256).digest()


def build_canonical_query(action: str, region: str, version: str) -> str:
    """OpenAPI 公共参数按 key 字母序拼接。"""
    pairs = sorted([("Action", action), ("Region", region), ("Version", version)])
    return "&".join(f"{_uri_encode(k)}={_uri_encode(v)}" for k, v in pairs)


def signed_headers_v4(
    *,
    ak: str,
    sk: str,
    region: str,
    service: str,
    host: str,
    query: str,
    body: str,
    now: datetime,
) -> dict[str, str]:
    """返回一次 POST 所需的全部签名请求头。now 为 naive 时按 UTC 处理。"""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    x_date = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    body_hash = _sha256_hex(body.encode("utf-8"))

    canonical_headers = (
        f"host:{host}\n"
        f"x-date:{x_date}\n"
        f"x-content-sha256:{body_hash}\n"
        f"content-type:{CONTENT_TYPE}\n"
    )
    canonical_request = f"POST\n/\n{query}\n{canonical_headers}\n{_SIGNED_HEADERS}\n{body_hash}"

    scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = f"HMAC-SHA256\n{x_date}\n{scope}\n{_sha256_hex(canonical_request.encode('utf-8'))}"

    k_date = _hmac_sha256(sk.encode("utf-8"), short_date)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    return {
        "X-Date": x_date,
        "X-Content-Sha256": body_hash,
        "Content-Type": CONTENT_TYPE,
        "Authorization": (
            f"HMAC-SHA256 Credential={ak}/{scope}, "
            f"SignedHeaders={_SIGNED_HEADERS}, Signature={signature}"
        ),
    }
