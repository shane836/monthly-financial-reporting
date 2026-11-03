import json

import pytest

from scripts.delivery import deliver, fingerprint, preflight


def test_preflight_rejects_wrong_entity_and_unverified_content(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("fictional source")
    row = dict(role="statement", entity="Example Company", period="2030-01", path=str(source), content_verified=True)
    assert preflight([row], "2030-01", "Example Company", ["statement"])["ready"]
    assert not preflight([row], "2030-01", "Other Company", ["statement"])["ready"]
    row["content_verified"] = False
    assert not preflight([row], "2030-01", "Example Company", ["statement"])["ready"]


def test_preflight_rejects_conflicting_or_unknown_roles(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("fictional source")
    row = dict(role="statement", entity="Example", period="2030-01", path=str(source), content_verified=True)
    assert not preflight([row, row], "2030-01", "Example", ["statement"])["ready"]
    assert not preflight([dict(row, role="unexpected")], "2030-01", "Example", ["statement"])["ready"]


def test_delivered_package_is_not_sent_twice(tmp_path):
    attempts = []
    digest = fingerprint({"period": "2030-01", "package": "fictional"})
    def send(marker):
        attempts.append(marker)
        return "verified-message-id"
    first = deliver(tmp_path, "2030-01", digest, send)
    second = deliver(tmp_path, "2030-01", digest, send)
    assert first["status"] == second["status"] == "sent"
    assert len(attempts) == 1


def test_uncertain_submission_is_never_automatically_retried(tmp_path):
    attempts = []
    def timeout(marker):
        attempts.append(marker)
        raise TimeoutError("simulated")
    digest = "a" * 64
    with pytest.raises(RuntimeError, match="uncertain"):
        deliver(tmp_path, "2030-01", digest, timeout)
    with pytest.raises(RuntimeError, match="uncertain"):
        deliver(tmp_path, "2030-01", digest, timeout)
    assert len(attempts) == 1
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["status"] == "pending"


def test_recipient_scope_changes_fingerprint():
    assert fingerprint({"to": "a@example.invalid"}) != fingerprint({"to": "b@example.invalid"})
