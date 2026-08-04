from app.core.cache import load_snapshots, save_snapshots
from app.core.models import UsageSnapshot, UsageWindow, WindowType


def test_cache_roundtrip(tmp_path):
    snaps = {
        "acc1": UsageSnapshot(
            provider="kimi",
            account_name="主力",
            windows=[
                UsageWindow(window_type=WindowType.FIVE_HOUR, percent=25.0, used=50000, limit=200000, reset_at=1753800000.0),
                UsageWindow(window_type=WindowType.SEVEN_DAY, percent=12.0),
            ],
            fetched_at=1753700000.0,
        )
    }
    save_snapshots(snaps, str(tmp_path))
    loaded = load_snapshots(str(tmp_path))
    assert "acc1" in loaded
    s = loaded["acc1"]
    assert s.provider == "kimi"
    assert s.fetched_at == 1753700000.0
    assert s.window(WindowType.FIVE_HOUR).percent == 25.0
    assert s.window(WindowType.SEVEN_DAY).used is None


def test_cache_missing(tmp_path):
    assert load_snapshots(str(tmp_path)) == {}


def test_cache_corrupt(tmp_path):
    (tmp_path / "cache.json").write_text("not json{", encoding="utf-8")
    assert load_snapshots(str(tmp_path)) == {}
