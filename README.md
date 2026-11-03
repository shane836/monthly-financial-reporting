---
type: reference
title: Monthly Financial Reporting
description: A generalized agent skill with reusable financial-reporting code and fictional examples.
workstream: programming
hub: "[[Programming_Automation]]"
status: draft
---

# Monthly Financial Reporting

A customizable agent skill with Python helpers for source checks, reconciliation,
Excel template updates, email review delivery, and missed-completion monitoring.

This is a sanitized version of a working monthly financial-reporting application.
The original application has been used with live Mail and Excel integrations.
For this sanitized version, live Mail/Excel behavior and business-specific
parsing and mappings still need to be confirmed before operational use.

All bundled financial data is fictional. Private identities, account mappings,
paths, templates, recipients, operating schedules, exceptions, credentials,
and runtime records are excluded.

**Requires adaptation:** supply your report parsers, approved mappings, template,
accounts, and monitoring configuration. This repository does not submit reports
to investor portals or configure a monthly automation automatically.

## Included

| Component | Capability |
|---|---|
| `SKILL.md` | Agent workflow, evidence standards, review boundaries |
| `scripts/workbook.py` | ZIP-preserving inputs, shared-formula expansion, cache transfer, preservation checks, macOS Excel recalculation |
| `scripts/financials.py` | Provenance, finite values, configurable equations, unmapped-metric checks |
| `scripts/delivery.py` | Preflight, content fingerprints, exclusive reservations, confirmed receipts |
| `scripts/mail.py`, `mail.js` | Apple Mail search, attachment retrieval, allowlisted sending, Sent Items verification |
| `scripts/monitor.py` | Deadlines, overdue/uncertain inspection, explicit HTTPS completion signaling |
| `scripts/report.py` | CLI and fictional demo |

Python helpers require Python 3.12+. Native Mail/Excel operations require macOS,
a logged-in session, installed applications, and narrowly granted permissions.
No proprietary agent runtime is required.

## Try it

Run from the repo root using [uv](https://docs.astral.sh/uv/):

```sh
uv sync --frozen --group dev
uv run --frozen pytest -q
uv run --frozen python -m scripts.report demo --output-dir runs/demo
```

The demo generates a fictional template, populates inputs, and checks source
reconciliation and preservation. It does not open Mail/Excel, send email, access
accounts, contact monitoring, or install schedules. Output is marked as requiring
recalculation and review. Choose a new output directory for another run.

## Adapt with your agent

Point your agent at `SKILL.md`, or copy this repo into a skill directory supported
by your host. This does not configure accounts or approve external actions.

Use `examples/config.example.json` and `examples/data.example.json` as schema
examples. Put real configuration and source data under gitignored `private/`;
keep generated workbooks and receipts under `runs/`. Adapt extraction, entity,
input roles, current-period cells, reconciliation equations, timezone, recipients,
and approvals. Do not reuse prior-month cells without inspecting the template.

Equations check normalized metrics. They do not prove extraction completeness or
verify every workbook subtotal; add your source and final-output checks.

## Workbook commands

```sh
uv run --frozen python -m scripts.report period --as-of 2030-02-20
uv run --frozen python -m scripts.report build \
  --data examples/data.example.json --config examples/config.example.json \
  --template runs/demo/template.xlsx --output runs/populated.xlsx \
  --evidence runs/build-evidence.json
uv run --frozen python -m scripts.report recalculate \
  --source runs/populated.xlsx --output runs/final.xlsx \
  --working-copy private/excel-working.xlsx
uv run --frozen python -m scripts.report verify \
  --template runs/demo/template.xlsx --output runs/final.xlsx \
  --evidence runs/build-evidence.json --require-calculated
```

Before a real build, prepare a private manifest: an array of objects containing
`role`, `entity`, `period`, `path`, and `content_verified`. Set the verification
flag only after source inspection. Paths resolve from the working directory.
Run `preflight` with `--manifest`, `--config`, and `--period` before building.

The Excel working copy is generated and disposable; never use a user workbook
for that path. A lock serializes operations. A stable file lets Excel retain
narrow file access. The script refuses an already-open target and closes only
its target workbook. Formula caches are transferred to the preserved archive.
Missing numeric caches or formula errors stop verification. Inspect the final
file in Excel before relying on it.

## Email

Copy `.env.example` to `.env` and populate it locally. Never put secret values
in chat or command arguments. `REPORT_MAILBOX` selects an existing authenticated
Apple Mail account. `REPORT_ALLOWED_RECIPIENTS` is a comma-separated allowlist.
No tokens or passwords are extracted. Empty configuration cannot send.

Use `uv run --frozen --env-file .env python -m scripts.report --help` for commands.
`mail-search` requires a scoped subject query and starting timestamp.
`mail-download` requires a verified message ID, index, filename, and new destination.
Verify sender, entity, period, attachment identity, and downloaded contents.
The bridge recognizes common English mailbox names; adapt identification for
other localizations or account layouts.

`send` requires `--approve-send`, an allowlisted `--to`, `--subject`, `--body-file`,
one or more `--attachment` values, `--period`, and `--receipts`. Use the approval
flag only after the package and destination are authorized. The helper does not
establish financial review on its own. Scope receipt folders to one entity and
reporting workflow.

Reservations precede submission. Confirmed identical deliveries are not resent.
Pending receipts block retries. Reconcile them with Sent Items; never delete
pending evidence merely to force another send.

## Monitoring

Privately configure the first reporting month, IANA timezone, deadline day
(1–28), hour, and grace period. `inspect --receipts runs/receipts --config
private/config.json` reads receipts without opening Mail or Excel. It exits
nonzero when reporting is overdue or uncertain.

An optional `--signal` posts only `{"status":"healthy"}` to
`REPORT_HEARTBEAT_URL`. No financial data, paths, documents, or email contents
are sent. Redirects are refused. Use a compatible HTTPS endpoint accepting a
JSON POST with a 2xx response, and independently configure missing-signal alerts.
This repo installs neither alert channels nor schedules. Test a controlled
missed signal and recovery before relying on monitoring. Monitor failure must
not cause another report email.

## Validation and limits

Tests of this sanitized version use generated workbooks, fictional records,
and fake transports. The original application's working status does not establish
end-to-end validation of this version. Confirm live Mail/Excel permissions and
behavior, source parsing, and business-specific mappings in the target environment.
Signed, encrypted, or unusual workbooks need separate compatibility review;
editing a digitally signed package can invalidate its signature.

Failures exit nonzero and write detailed local tracebacks to `private/error.log`.
Keep that file private. Before publishing an adaptation, inspect an explicit
release file list; exclude actual workbooks, PDFs, emails, logs, receipts,
private configuration, and `.env` files.

## How this was built

Adapted with OpenAI Codex assistance from an existing private workflow.
Operational data and environment configuration are not distributed. Review
and validate the code for your own reporting requirements.

No license has been selected for this repository.
