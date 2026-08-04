from app.providers.curl_parse import parse_curl


def test_parse_bash_style():
    text = (
        "curl 'https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/GetCodingPlanUsage' \\\n"
        "  -H 'content-type: application/json' \\\n"
        "  -H 'cookie: sessionid=abc123; csrfToken=tok-xyz; other=1' \\\n"
        "  -H 'x-web-id: 738000111222' \\\n"
        "  --data-raw '{\"ProjectName\":\"default\"}'"
    )
    cred = parse_curl(text)
    assert "sessionid=abc123" in cred.cookie
    assert cred.csrf_token == "tok-xyz"  # 从 Cookie 自动提取
    assert cred.web_id == "738000111222"
    assert cred.url.startswith("https://console.volcengine.com")


def test_parse_cmd_style_with_caret():
    text = (
        'curl "https://console.volcengine.com/api/x" ^\n'
        '  -H "cookie: a=1; csrfToken=t2" ^\n'
        '  -H "x-csrf-token: explicit-tok" ^\n'
        '  -H "x-web-id: wid9"'
    )
    cred = parse_curl(text)
    assert cred.cookie == "a=1; csrfToken=t2"
    # 显式 header 优先于 Cookie 提取
    assert cred.csrf_token == "explicit-tok"
    assert cred.web_id == "wid9"


def test_parse_cookie_b_flag():
    text = "curl https://example.com -b 'k=v; csrfToken=zz'"
    cred = parse_curl(text)
    assert cred.cookie == "k=v; csrfToken=zz"
    assert cred.csrf_token == "zz"


def test_parse_empty():
    cred = parse_curl("")
    assert cred.cookie == ""
    assert cred.csrf_token == ""
