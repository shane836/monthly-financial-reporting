"""CLI for explicit reporting operations. Defaults never send email or signal a monitor."""
import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path

from scripts.delivery import deliver, fingerprint, preflight
from scripts.financials import prepare
from scripts.mail import MailClient
from scripts.monitor import inspect, signal
from scripts.workbook import patch_archive, previous_period, recalculate, verify_archive


def load(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def client():
    return MailClient(os.environ.get("REPORT_MAILBOX", ""), os.environ.get("REPORT_ALLOWED_RECIPIENTS", "").split(","))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    period = sub.add_parser("period")
    period.add_argument("--as-of", default=date.today().isoformat())
    check = sub.add_parser("preflight")
    check.add_argument("--manifest", required=True)
    check.add_argument("--config", required=True)
    check.add_argument("--period", required=True)
    build = sub.add_parser("build")
    build.add_argument("--data", required=True)
    build.add_argument("--config", required=True)
    build.add_argument("--template", required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--evidence", required=True)
    calc = sub.add_parser("recalculate")
    calc.add_argument("--source", required=True)
    calc.add_argument("--output", required=True)
    calc.add_argument("--working-copy", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--template", required=True)
    verify.add_argument("--output", required=True)
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--require-calculated", action="store_true")
    search = sub.add_parser("mail-search")
    search.add_argument("--query", required=True)
    search.add_argument("--since", required=True)
    download = sub.add_parser("mail-download")
    download.add_argument("--message-id", type=int, required=True)
    download.add_argument("--attachment-index", type=int, required=True)
    download.add_argument("--filename", required=True)
    download.add_argument("--output", required=True)
    send = sub.add_parser("send")
    send.add_argument("--period", required=True)
    send.add_argument("--to", required=True)
    send.add_argument("--subject", required=True)
    send.add_argument("--body-file", required=True)
    send.add_argument("--attachment", action="append", required=True)
    send.add_argument("--receipts", required=True)
    send.add_argument("--approve-send", action="store_true")
    monitor = sub.add_parser("inspect")
    monitor.add_argument("--receipts", required=True)
    monitor.add_argument("--config", required=True)
    monitor.add_argument("--signal", action="store_true")
    demo = sub.add_parser("demo")
    demo.add_argument("--output-dir", default="runs/demo")
    args = parser.parse_args()
    if args.command == "period":
        result = previous_period(date.fromisoformat(args.as_of))
    elif args.command == "preflight":
        config = load(args.config)
        result = preflight(load(args.manifest), args.period, config["entity"], config["required_roles"])
    elif args.command == "build":
        data = load(args.data)
        updates, checks = prepare(data, load(args.config))
        patch_archive(args.template, args.output, updates)
        result = verify_archive(args.template, args.output, updates)
        result.update(period=data["period"], entity=data["entity"], updates=updates, checks=checks,
                      template_sha256=hashlib.sha256(Path(args.template).read_bytes()).hexdigest(),
                      output_sha256=hashlib.sha256(Path(args.output).read_bytes()).hexdigest(),
                      data_fingerprint=fingerprint(data), review_status="recalculation_and_review_required")
        save(args.evidence, result)
    elif args.command == "recalculate":
        recalculate(args.source, args.output, args.working_copy)
        result = {"status": "recalculated", "next": "Verify the final file against its template and evidence"}
    elif args.command == "verify":
        evidence = load(args.evidence)
        if hashlib.sha256(Path(args.template).read_bytes()).hexdigest() != evidence["template_sha256"]:
            raise ValueError("Template differs from build evidence")
        result = verify_archive(args.template, args.output, evidence["updates"], require_calculated=args.require_calculated)
        result["output_sha256"] = hashlib.sha256(Path(args.output).read_bytes()).hexdigest()
    elif args.command == "mail-search":
        result = client().search(args.query, since=args.since, exclude_sent=True)
    elif args.command == "mail-download":
        result = client().download(args.message_id, args.attachment_index, args.filename, args.output)
    elif args.command == "send":
        if not args.approve_send:
            raise ValueError("Review exact recipients, content, and attachments before using --approve-send")
        mail = client()
        body = Path(args.body_file).read_text()
        attachments = [Path(path).resolve() for path in args.attachment]
        digest = fingerprint(dict(mailbox=mail.mailbox, recipient=args.to.lower(), subject=args.subject, body=body,
                                  period=args.period, attachments=[dict(name=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in attachments]))
        result = deliver(args.receipts, args.period, digest,
                         lambda marker: mail.send(args.to, args.subject, body, attachments, marker, approved=True))
    elif args.command == "inspect":
        result = inspect(args.receipts, datetime.now().astimezone(), **load(args.config)["monitor"])
        if args.signal:
            result["heartbeat"] = signal(os.environ.get("REPORT_HEARTBEAT_URL", ""), result)
    else:
        import openpyxl
        root = Path(args.output_dir)
        root.mkdir(parents=True, exist_ok=False)
        template = root / "template.xlsx"
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "Summary"
        for row in [["Revenue", 0], ["Expenses", 0], ["Net income", "=B1-B2"]]:
            sheet.append(row)
        book.save(template)  # Only this newly generated fictional workbook is saved with openpyxl.
        examples = Path(__file__).resolve().parents[1] / "examples"
        updates, checks = prepare(load(examples / "data.example.json"), load(examples / "config.example.json"))
        output = root / "populated.xlsx"
        patch_archive(template, output, updates)
        result = verify_archive(template, output, updates)
        result.update(checks=checks, review_status="recalculation_and_review_required")
        save(root / "validation.json", result)
    print(json.dumps(result, indent=2))
    if isinstance(result, dict) and (result.get("ready") is False or result.get("healthy") is False):
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Do not print credentials, raw email, financial content, or credential-bearing URLs.
        import logging
        import sys
        private = Path("private")
        private.mkdir(exist_ok=True)
        logging.basicConfig(filename=private / "error.log", level=logging.ERROR)
        logging.exception("Reporting operation failed")
        print(f"Reporting operation failed ({type(error).__name__}); see private/error.log. No automatic resend.", file=sys.stderr)
        raise SystemExit(1)
