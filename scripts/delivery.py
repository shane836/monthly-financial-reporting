"""Input verification and exclusive delivery receipts; no mail is sent on import."""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def validate_period(period):
    if not isinstance(period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise ValueError("Reporting period must be YYYY-MM")
    date.fromisoformat(period + "-01")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def preflight(files, period, entity, roles):
    validate_period(period)
    if not entity or not roles or len(set(roles)) != len(roles):
        raise ValueError("An entity and unique required roles are required")
    errors, missing, verified = [], [], []
    for role in roles:
        matches = [entry for entry in files if entry.get("role") == role]
        if not matches:
            missing.append(role)
            continue
        if len(matches) != 1:
            errors.append(f"{role}: ambiguous input")
            continue
        entry = matches[0]
        path = Path(entry.get("path", ""))
        if entry.get("period") != period or entry.get("entity") != entity or entry.get("content_verified") is not True:
            errors.append(f"{role}: entity, period, or content verification mismatch")
        elif not path.is_file() or path.stat().st_size == 0:
            errors.append(f"{role}: missing or empty local file")
        else:
            verified.append({"role": role, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if any(entry.get("role") not in roles for entry in files):
        errors.append("Unknown input role")
    ready = not errors and not missing
    return dict(ready=ready, errors=errors, missing=missing, source_hashes=verified,
                fingerprint=fingerprint(dict(entity=entity, period=period, sources=verified)) if ready else None)


def read_receipt(path):
    try:
        value = json.loads(Path(path).read_text())
        validate_period(value["period"])
        if value["status"] not in ("pending", "sent") or not re.fullmatch(r"[a-f0-9]{64}", value["fingerprint"]):
            raise ValueError("Invalid receipt state")
        if value["status"] == "sent":
            if not value.get("message_id") or datetime.fromisoformat(value["verified_at"]).tzinfo is None:
                raise ValueError("Confirmed receipt lacks evidence")
        return value
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ValueError("Invalid delivery receipt; inspect it locally") from error


def deliver(directory, period, digest, send):
    """Reserve before sending; an uncertain attempt is held for manual reconciliation."""
    validate_period(period)
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("A SHA256 delivery fingerprint is required")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{period}-{digest}.json"
    if path.exists():
        receipt = read_receipt(path)
        if receipt["status"] == "sent":
            return receipt
        raise RuntimeError("Previous delivery is uncertain; reconcile Sent Items before retrying")
    receipt = dict(period=period, fingerprint=digest, status="pending", created_at=datetime.now(timezone.utc).isoformat())
    with path.open("x") as handle:
        json.dump(receipt, handle, indent=2)
    try:
        message_id = send(f"report-{digest}")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("Verified sent message ID required")
    except Exception as error:
        raise RuntimeError("Delivery outcome uncertain; receipt retained, no automatic resend") from error
    receipt.update(status="sent", message_id=message_id, verified_at=datetime.now(timezone.utc).isoformat())
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary.replace(path)
    return receipt
