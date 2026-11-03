"""Generalized workbook helpers extracted from a private reporting runner.
Patch worksheet XML while preserving unrelated ZIP members. openpyxl reads only.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import calendar
import html
import math
import os
import posixpath
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
import openpyxl
M = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CELL = re.compile(r'<c\b[^>]*\br="([^"]+)"[^>]*?(?:/>|>.*?</c>)', re.S)
FORMULA = re.compile(r'<f\b[^>]*?(?:/>|>.*?</f>)', re.S)

def norm(value):
    return " ".join(str(value or "").split())


def dec(value):
    if value in (None, ""):
        return Decimal(0)
    if not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"Expected numeric source, found {value!r}")
    return Decimal(str(value))


def cents(value):
    return dec(value).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)


def previous_period(today: date):
    return (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def month_end(period):
    d = date.fromisoformat(period + "-01")
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def book(path, cached=False):
    return openpyxl.load_workbook(path, data_only=cached)


def ytd_columns(sheet, period, row=5):
    end = month_end(period)
    dates = []
    for c in range(1, sheet.max_column + 1):
        value = sheet.cell(row, c).value
        if isinstance(value, str) and re.fullmatch(r"[A-Z][a-z]{2} \d{4}", value):
            dates.append((datetime.strptime(value, "%b %Y"), c))
    selected = [(d, c) for d, c in dates if d.year == end.year and d.month <= end.month]
    if [d.month for d, _ in selected] != list(range(1, end.month + 1)):
        raise ValueError("Missing, duplicate or unordered YTD months")
    if not dates or max(d for d, _ in dates).strftime("%Y-%m") != period:
        raise ValueError("T12 end month does not match reporting period")
    return [c for _, c in selected]


def account_rows(sheet, start=7):
    result = {}
    section = ""
    for row in sheet.iter_rows(min_row=start):
        raw = row[0].value
        label = norm(raw)
        if not label:
            continue
        if label.isupper() and not str(raw).startswith(" "):
            section = label
        if str(raw).startswith(" ") and not label.isupper():
            label = section + " :: " + label
        if label in result:
            raise ValueError(f"Duplicate account: {label}")
        result[label] = row[0].row
    return result


def check_account_set(amounts, known):
    unknown = {label: value for label, value in amounts.items() if label not in known and value != 0}
    if unknown:
        raise ValueError(f"Unknown nonzero source accounts: {unknown}")


def is_input_placeholder(formula, coordinate, unlocked):
    match = re.fullmatch(r'=IF\(ISBLANK\(([A-Z]+)(\d+)\),"",\1\2\)', str(formula))
    return bool(unlocked and match and match.group(2) == re.search(r'\d+$',coordinate).group(0))


def sheet_members(archive):
    root = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
    result = {}
    for s in root.findall("m:sheets/m:sheet", M):
        rid = s.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = targets[rid]
        result[s.attrib["name"]] = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
    return result


def xml_values(archive, member):
    strings = []
    if "xl/sharedStrings.xml" in archive.namelist():
        strings = ["".join(n.itertext()) for n in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
    result = {}
    for c in ET.fromstring(archive.read(member)).findall(".//m:sheetData/m:row/m:c", M):
        typ = c.get("t", "n")
        v = c.find("m:v", M)
        value = None if v is None else v.text
        if typ == "s" and value is not None:
            typ, value = "str", strings[int(value)]
        elif typ == "inlineStr":
            typ, value = "str", "".join(c.find("m:is", M).itertext())
        result[c.get("r")] = (typ, value)
    return result


def replace_value(original, typ, value, keep_formula):
    opening = re.match(r"<c\b[^>]*>", original).group(0).replace("/>", ">")
    opening = re.sub(r'\s+t="[^"]*"', "", opening)
    if value is not None and typ not in ("n", ""):
        opening = opening[:-1] + f' t="{typ}">'
    f = FORMULA.search(original)
    body = f.group(0) if keep_formula and f else ""
    if value is not None:
        body += "<v>" + html.escape(str(value)) + "</v>"
    return opening + body + "</c>"


def _patch_archive(source, output, updates, authored=None):
    if len({(u["sheet"], u["cell"]) for u in updates}) != len(updates):
        raise ValueError("Duplicate input address")
    expanded = None
    with zipfile.ZipFile(source) as z:
        members = sheet_members(z)
        wanted = defaultdict(dict)
        for u in updates:
            wanted[members[u["sheet"]]][u["cell"]] = u
        staged = {}
        authored_values = {}
        if authored:
            with zipfile.ZipFile(authored) as a:
                am = sheet_members(a)
                for sheet in {u["sheet"] for u in updates}:
                    authored_values[members[sheet]] = xml_values(a, am[sheet])
        for member, changes in wanted.items():
            seen = set()
            xml = z.read(member).decode()
            if 't="shared"' in xml:
                expanded = expanded or book(source)
            sheet = next(s for s, m in members.items() if m == member)

            def change(m):
                ref, original = m.group(1), m.group(0)
                if ref not in changes:
                    if 't="shared"' in original:
                        formula = expanded[sheet][ref].value
                        if not isinstance(formula, str) or not formula.startswith("="):
                            raise ValueError(f"Cannot expand shared formula {sheet}!{ref}")
                        return FORMULA.sub(lambda _: "<f>" + html.escape(formula[1:]) + "</f>", original)
                    return original
                if FORMULA.search(original):
                    if not changes[ref].get("input_placeholder_formula"):
                        raise ValueError(f"Input would overwrite formula: {sheet}!{ref}")
                    expanded_book = expanded or book(source)
                    original_cell = expanded_book[sheet][ref]
                    if changes[ref].get("input_placeholder_formula") != original_cell.value or not is_input_placeholder(original_cell.value,ref,not original_cell.protection.locked):
                        raise ValueError(f"Input would overwrite formula: {sheet}!{ref}")
                seen.add(ref)
                value = changes[ref]["value"]
                typ, encoded = ("n", None) if value is None else (("str", value) if isinstance(value, str) else ("n", value))
                if authored:
                    at, av = authored_values[member].get(ref, ("n", None))
                    same = (av in (None, "") and value is None) or (av == value if isinstance(value, str) else av is not None and cents(float(av)) == cents(value))
                    if not same:
                        raise ValueError(f"Authoring mismatch: {sheet}!{ref}: {av!r} != {value!r}")
                    typ, encoded = at, av
                return replace_value(original, typ, encoded, False)

            staged[member] = CELL.sub(change, xml).encode()
            if seen != set(changes):
                raise ValueError(f"Missing input cells in template: {set(changes) - seen}")
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist():
                out.writestr(info, staged.get(info.filename, z.read(info.filename)))


def _merge_caches(source, calculated, output):
    count = 0
    with zipfile.ZipFile(source) as z, zipfile.ZipFile(calculated) as calc:
        members, cm = sheet_members(z), sheet_members(calc)
        staged = {}
        for sheet, member in members.items():
            values = xml_values(calc, cm[sheet])
            previous=xml_values(z,member)

            def change(m):
                nonlocal count
                if not FORMULA.search(m.group(0)):
                    return m.group(0)
                if m.group(1) not in values:
                    raise ValueError(f"Missing recalculated formula: {sheet}!{m.group(1)}")
                typ, value = values[m.group(1)]
                if typ == "e":
                    raise ValueError(f"Excel error: {sheet}!{m.group(1)} {value}")
                if typ in ("n", "") and value in (None, ""):
                    raise ValueError(f"Missing numeric formula cache: {sheet}!{m.group(1)}")
                old_typ,old_value=previous[m.group(1)]
                if old_typ=='n' and old_value not in (None,'') and typ=='n' and value in (None,''):
                    raise ValueError(f'Missing expected numeric formula cache: {sheet}!{m.group(1)}')
                count += 1
                return replace_value(m.group(0), typ, value, True)

            staged[member] = CELL.sub(change, z.read(member).decode()).encode()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as out:
            for info in z.infolist():
                out.writestr(info, staged.get(info.filename, z.read(info.filename)))
    return count


def _output_paths(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output.exists():
        raise ValueError("Write to a new output path; source and existing outputs are immutable")
    output.parent.mkdir(parents=True, exist_ok=True)
    return source, output


def _atomic_output(output, writer):
    fd, name = tempfile.mkstemp(suffix=".xlsx", dir=output.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        writer(temporary)
        # Exclusive linking avoids overwriting an output created by a concurrent run.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def patch_archive(source, output, updates):
    source, output = _output_paths(source, output)
    for update in updates:
        value = update["value"]
        if isinstance(value, bool) or not (value is None or isinstance(value, (str, int, float, Decimal))):
            raise ValueError("Inputs must be scalar text, finite numbers, or null")
        if isinstance(value, (float, Decimal)) and not math.isfinite(value):
            raise ValueError("Nonfinite numeric input")
    _atomic_output(output, lambda temporary: _patch_archive(source, temporary, updates))


def merge_caches(source, calculated, output):
    source, output = _output_paths(source, output)
    if Path(calculated).resolve() == output:
        raise ValueError("Calculated input cannot also be the output")
    original, refreshed = book(source), book(calculated)
    if original.sheetnames != refreshed.sheetnames:
        raise ValueError("The recalculated workbook has different worksheets")
    for sheet in original:
        for row in sheet:
            for cell in row:
                if cell.value != refreshed[sheet.title][cell.coordinate].value:
                    raise ValueError("The recalculated workbook has different inputs or formulas")
        for row in refreshed[sheet.title]:
            for cell in row:
                if cell.value != sheet[cell.coordinate].value:
                    raise ValueError("The recalculated workbook has unexpected new content")
    _atomic_output(output, lambda temporary: _merge_caches(source, calculated, temporary))


def verify_archive(source, output, updates, *, require_calculated=False):
    allowed = {(u["sheet"], u["cell"]): u["value"] for u in updates}
    if len(allowed) != len(updates):
        raise ValueError("Duplicate input address")
    before, after = book(source), book(output)
    cached = book(output, cached=True)
    if before.sheetnames != after.sheetnames:
        raise ValueError("Worksheet names changed")
    seen, formulas = set(), 0
    for sheet in before:
        final = after[sheet.title]
        for row in sheet:
            for cell in row:
                key = (sheet.title, cell.coordinate)
                current = final[cell.coordinate]
                if cell._style != current._style:
                    raise ValueError("Cell style changed")
                if key in allowed:
                    if current.value != allowed[key]:
                        raise ValueError("Authored input mismatch")
                    seen.add(key)
                elif cell.value != current.value:
                    raise ValueError("Unexpected value or formula change")
                value = cached[sheet.title][cell.coordinate]
                if value.data_type == "e":
                    raise ValueError("Formula error in final workbook")
                if current.data_type == "f":
                    formulas += 1
                    if require_calculated and value.value is None:
                        raise ValueError("Missing formula cache; recalculate and verify")
        for row in final:
            for cell in row:
                if cell.value is not None and sheet[cell.coordinate].value is None and (sheet.title, cell.coordinate) not in allowed:
                    raise ValueError("Unexpected new cell content")
    if seen != set(allowed):
        raise ValueError("Input destination missing")
    with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
        if a.namelist() != b.namelist():
            raise ValueError("Workbook archive members changed")
        worksheets = set(sheet_members(a).values())
        for name in a.namelist():
            if name not in worksheets and a.read(name) != b.read(name):
                raise ValueError("Nonworksheet package part changed")
    return dict(status="passed", input_cells=len(allowed), preserved_formulas=formulas,
                recalculation_checked=require_calculated)


def recalculate(source, output, working_copy):
    """Recalculate a serialized disposable Excel copy, then merge only formula caches."""
    import fcntl
    import shutil
    import subprocess

    source, output = _output_paths(source, output)
    working = Path(working_copy).resolve()
    if working in (source, output) or working.suffix.lower() != ".xlsx":
        raise ValueError("Choose a separate generated .xlsx working copy")
    working.parent.mkdir(parents=True, exist_ok=True)
    with working.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Keep the generated working file's inode so Excel can retain narrow file access.
        shutil.copyfile(source, working)
        result = subprocess.run(["/usr/bin/osascript", str(Path(__file__).with_name("excel.applescript")),
                                 str(working), working.name, "recalculate"], capture_output=True, text=True, timeout=150)
        if result.returncode:
            raise RuntimeError("Excel recalculation failed; inspect local Excel access and workbook state")
        merge_caches(source, working, output)
