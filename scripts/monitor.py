"""Receipt inspection and explicit HTTPS heartbeat signaling. No scheduler is installed."""
from datetime import datetime, timedelta
from pathlib import Path
import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from scripts.delivery import read_receipt, validate_period


def inspect(receipts, now, *, baseline, timezone="UTC", due_day=20, due_hour=9, grace_hours=0):
    validate_period(baseline)
    if now.tzinfo is None or not 1 <= due_day <= 28 or not 0 <= due_hour <= 23 or grace_hours < 0:
        raise ValueError("Use an aware timestamp, due day 1..28, hour 0..23, and nonnegative grace")
    zone = ZoneInfo(timezone)
    now = now.astimezone(zone)
    confirmed, pending = set(), set()
    for path in sorted(Path(receipts).glob("*.json")):
        receipt = read_receipt(path)
        (confirmed if receipt["status"] == "sent" else pending).add(receipt["period"])
    year, month = map(int, baseline.split("-"))
    due = []
    while True:
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        deadline = datetime(next_year, next_month, due_day, due_hour, tzinfo=zone) + timedelta(hours=grace_hours)
        if deadline > now:
            break
        due.append(f"{year:04}-{month:02}")
        year, month = next_year, next_month
    overdue = sorted(set(due) - confirmed)
    current = (now.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    uncertain = sorted(period for period in pending if period <= current)
    # A late ping for an earlier report must not clear the next reporting deadline.
    return dict(due=due, overdue=overdue, uncertain=uncertain,
                healthy=bool(due) and due[-1] == current and not overdue and not uncertain)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_ping(url, body):
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with build_opener(NoRedirect).open(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError("Monitor rejected completion signal")


def signal(url, result, *, post=post_ping):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("An HTTPS heartbeat URL without userinfo or fragment is required")
    # Send healthy completion only. Missing signals must be detected independently.
    if not result.get("healthy"):
        return {"status": "blocked"}
    try:
        post(url, {"status": "healthy"})
    except Exception:
        # Network exceptions can contain a credential-bearing endpoint.
        raise RuntimeError("Heartbeat failed; delivery receipts remain authoritative") from None
    return {"status": "acknowledged"}
