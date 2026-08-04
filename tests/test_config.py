import json
import os

from app.core.config import Account, Config, CustomSpec, Settings, load_config, save_config


def test_roundtrip(tmp_path):
    cfg = Config(
        accounts=[
            Account(provider="kimi", name="主力", key="sk-kimi-1"),
            Account(provider="glm", name="GLM-Pro", key="glm-key", site="api.z.ai", enabled=False),
            Account(
                provider="volcano",
                name="火山",
                cookie="sessionid=abc; csrfToken=tok123",
                csrf_token="tok123",
                web_id="wid",
            ),
            Account(
                provider="custom",
                name="自定义",
                key="ck",
                custom=CustomSpec(
                    url="https://example.com/usage",
                    headers={"Authorization": "Bearer {KEY}"},
                    paths={"5h": "data.five_hour", "7d": "data.week", "monthly": "data.month"},
                ),
            ),
        ],
        settings=Settings(poll_interval_sec=120, display_mode="strip"),
    )
    path = save_config(cfg, str(tmp_path))
    assert os.path.exists(path)

    loaded = load_config(str(tmp_path))
    assert len(loaded.accounts) == 4
    assert loaded.accounts[0].provider == "kimi"
    assert loaded.accounts[1].site == "api.z.ai"
    assert loaded.accounts[2].csrf_token == "tok123"
    assert loaded.accounts[3].custom.paths["monthly"] == "data.month"
    assert loaded.settings.poll_interval_sec == 120
    assert loaded.settings.display_mode == "strip"
    # id 保留
    assert loaded.accounts[0].id == cfg.accounts[0].id


def test_load_missing_returns_default(tmp_path):
    cfg = load_config(str(tmp_path))
    assert cfg.accounts == []
    assert cfg.settings.poll_interval_sec == 300


def test_load_ignores_unknown_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "accounts": [{"provider": "kimi", "key": "k", "unknown_field": 1}],
                "settings": {"poll_interval_sec": 60, "future_option": True},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(str(tmp_path))
    assert cfg.accounts[0].key == "k"
    assert cfg.settings.poll_interval_sec == 60


def test_enabled_accounts(tmp_path):
    cfg = Config(accounts=[Account(enabled=True), Account(enabled=False)])
    assert len(cfg.enabled_accounts()) == 1
