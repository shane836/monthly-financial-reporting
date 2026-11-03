from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.delivery import deliver
from scripts.monitor import inspect, signal


def test_due_date_uses_configured_timezone_and_grace(tmp_path):
    now = datetime(2030, 2, 10, 11, tzinfo=ZoneInfo("UTC"))
    result = inspect(tmp_path, now, baseline="2030-01", timezone="UTC", due_day=10, due_hour=9, grace_hours=3)
    assert result["overdue"] == []
    result = inspect(tmp_path, now.replace(hour=12), baseline="2030-01", timezone="UTC", due_day=10, due_hour=9, grace_hours=3)
    assert result["overdue"] == ["2030-01"]


def test_pending_revision_blocks_healthy_status(tmp_path):
    deliver(tmp_path, "2030-01", "a" * 64, lambda _: "verified-id")
    with pytest.raises(RuntimeError):
        deliver(tmp_path, "2030-01", "b" * 64, lambda _: None)
    result = inspect(tmp_path, datetime(2030, 2, 20, tzinfo=ZoneInfo("UTC")), baseline="2030-01", timezone="UTC")
    assert result["uncertain"] == ["2030-01"]
    assert result["healthy"] is False


def test_corrupt_receipts_surface(tmp_path):
    (tmp_path / "broken.json").write_text("not json")
    with pytest.raises(ValueError):
        inspect(tmp_path, datetime.now(ZoneInfo("UTC")), baseline="2030-01")


def test_heartbeat_rejects_non_https_and_does_not_leak_url():
    with pytest.raises(ValueError):
        signal("http://example.invalid/private", {"healthy": True})
    def fails(*_):
        raise RuntimeError("https://example.invalid/secret-value")
    with pytest.raises(RuntimeError) as error:
        signal("https://example.invalid/private", {"healthy": True}, post=fails)
    assert "secret-value" not in str(error.value)


def test_heartbeat_payload_excludes_local_financial_data():
    calls = []
    signal("https://example.invalid/private", {"healthy": True, "overdue": [], "uncertain": [], "private_path": "/private/source", "balance": 42}, post=lambda url, body: calls.append(body))
    assert calls == [{"status": "healthy"}]
