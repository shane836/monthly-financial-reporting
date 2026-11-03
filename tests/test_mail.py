import pytest

from scripts.mail import MailClient


def test_non_allowlisted_recipient_is_blocked_before_transport():
    calls = []
    client = MailClient("sender@example.invalid", ["reviewer@example.invalid"], bridge=lambda data: calls.append(data))
    with pytest.raises(ValueError):
        client.send("other@example.invalid", "Review", "Body", [], "marker", approved=True)
    assert calls == []


def test_send_requires_approval_before_transport():
    client = MailClient("sender@example.invalid", ["reviewer@example.invalid"], bridge=lambda _: pytest.fail("unexpected Mail access"))
    with pytest.raises(ValueError):
        client.send("reviewer@example.invalid", "Review", "Body", [], "marker", approved=False)


def test_send_verifies_exact_subject_marker_and_recipient():
    calls = []
    def bridge(request):
        calls.append(request)
        if request["action"] == "send":
            return {"submitted": True}
        return [{"subject": "Review", "internet_message_id": "id-1", "recipients": ["wrong@example.invalid"], "attachments": []}]
    client = MailClient("sender@example.invalid", ["reviewer@example.invalid"], bridge=bridge)
    with pytest.raises(RuntimeError, match="uncertain"):
        client.send("reviewer@example.invalid", "Review", "Body", [], "marker", approved=True, attempts=1)
    assert [request["action"] for request in calls] == ["send", "search"]
