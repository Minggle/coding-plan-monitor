"""火山引擎 V4 签名（HMAC-SHA256，AWS SigV4 变体）。

黄金向量由社区参考实现（minimote/coding-plan-usage-query，Node.js）生成，
两个独立项目（另见 kenanlabs/quota-dashboard）线上验证可用。
"""

from datetime import datetime, timezone

from app.providers.volcano_sign import build_canonical_query, signed_headers_v4

FIXED_NOW = datetime(2026, 7, 25, 7, 2, 3, 123000, tzinfo=timezone.utc)
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _sign(action: str) -> dict[str, str]:
    return signed_headers_v4(
        ak="AKTESTEXAMPLE",
        sk="SKTESTEXAMPLE",
        region="cn-beijing",
        service="ark",
        host="open.volcengineapi.com",
        query=build_canonical_query(action, "cn-beijing", "2024-01-01"),
        body="",
        now=FIXED_NOW,
    )


def test_canonical_query_sorted():
    assert (
        build_canonical_query("GetAFPUsage", "cn-beijing", "2024-01-01")
        == "Action=GetAFPUsage&Region=cn-beijing&Version=2024-01-01"
    )
    assert (
        build_canonical_query("GetCodingPlanUsage", "cn-beijing", "2024-01-01")
        == "Action=GetCodingPlanUsage&Region=cn-beijing&Version=2024-01-01"
    )


def test_xdate_and_body_hash():
    h = _sign("GetAFPUsage")
    assert h["X-Date"] == "20260725T070203Z"
    assert h["X-Content-Sha256"] == EMPTY_SHA256
    assert h["Content-Type"] == "application/json; charset=utf-8"


def test_authorization_golden_vector_afp():
    assert _sign("GetAFPUsage")["Authorization"] == (
        "HMAC-SHA256 Credential=AKTESTEXAMPLE/20260725/cn-beijing/ark/request, "
        "SignedHeaders=host;x-date;x-content-sha256;content-type, "
        "Signature=053ffb9a3470c9a89a7b2657d8eb933474847a8116db93570b24ead9c46a5bf4"
    )


def test_authorization_golden_vector_coding():
    assert _sign("GetCodingPlanUsage")["Authorization"] == (
        "HMAC-SHA256 Credential=AKTESTEXAMPLE/20260725/cn-beijing/ark/request, "
        "SignedHeaders=host;x-date;x-content-sha256;content-type, "
        "Signature=6c628672198550266968df07c2eafaf106c04e2f2f0aa03430558fbe9614cdac"
    )


def test_body_affects_hash_and_signature():
    h = signed_headers_v4(
        ak="AKTESTEXAMPLE", sk="SKTESTEXAMPLE", region="cn-beijing", service="ark",
        host="open.volcengineapi.com", query="Action=X&Region=cn-beijing&Version=2024-01-01",
        body="{}", now=FIXED_NOW,
    )
    assert h["X-Content-Sha256"] != EMPTY_SHA256
    assert h["Authorization"] != _sign("GetAFPUsage")["Authorization"]
