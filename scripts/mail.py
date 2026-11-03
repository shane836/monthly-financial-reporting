"""Opt-in Apple Mail adapter. Account and recipients come from private configuration."""
import json
from pathlib import Path
import subprocess
import tempfile
import time


def bridge(request):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as handle:
        json.dump(request, handle)
        handle.flush()
        process = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", str(Path(__file__).with_name("mail.js")), handle.name], capture_output=True, text=True, timeout=180)
    if process.returncode:
        raise RuntimeError("Apple Mail operation failed; inspect local account access and permissions")
    return json.loads(process.stdout)


class MailClient:
    def __init__(self, mailbox, recipients, *, bridge=bridge):
        if not mailbox or not recipients:
            raise ValueError("Configure a mailbox and recipient allowlist")
        self.mailbox = mailbox.strip().lower()
        self.recipients = {address.strip().lower() for address in recipients if address.strip()}
        self.bridge = bridge

    def call(self, action, **kwargs):
        return self.bridge(dict(action=action, mailbox=self.mailbox, **kwargs))

    def search(self, query, **kwargs):
        if not query.strip():
            raise ValueError("Use a nonempty, scoped subject query")
        return self.call("search", query=query, **kwargs)

    def download(self, message_id, index, filename, destination):
        destination = Path(destination)
        if destination.exists():
            raise ValueError("Download destination already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        result = self.call("download", id=message_id, attachment_index=index, filename=filename, path=str(destination.resolve()))
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError("Attachment was not downloaded completely")
        return result

    def send(self, recipient, subject, body, attachments, marker, *, approved=False, attempts=6):
        if not approved or recipient.lower() not in self.recipients:
            raise ValueError("Explicit approval and an allowlisted recipient are required")
        if not marker or not subject or attempts < 1:
            raise ValueError("Subject, delivery marker, and verification attempts are required")
        paths = [Path(path).resolve() for path in attachments]
        if any(not path.is_file() for path in paths):
            raise ValueError("Attachment missing")
        submitted = self.call("send", to=recipient, allowed_recipients=sorted(self.recipients), subject=subject,
                              body=body + "\n\nDelivery marker: " + marker, attachments=[str(path) for path in paths], approved=True)
        if not submitted.get("submitted"):
            raise RuntimeError("Email outcome uncertain; no resend allowed")
        for attempt in range(attempts):
            rows = self.search(subject, sent_only=True, contains_body=marker)
            matches = [row for row in rows if row["subject"] == subject
                       and set(address.lower() for address in row.get("recipients", [])) == {recipient.lower()}
                       and sorted(a["name"] for a in row.get("attachments", [])) == sorted(path.name for path in paths)
                       and row.get("internet_message_id")]
            if len(matches) == 1:
                return matches[0]["internet_message_id"]
            if len(matches) > 1:
                raise RuntimeError("Email outcome uncertain: multiple sent matches")
            if attempt + 1 < attempts:
                time.sleep(5)
        raise RuntimeError("Email outcome uncertain; reconcile Sent Items, do not automatically resend")
