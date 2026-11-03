import zipfile
from datetime import date

import openpyxl
import pytest

from scripts.workbook import merge_caches, patch_archive, previous_period, verify_archive, ytd_columns


def template(path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Summary"
    sheet.append(["Revenue", 0])
    sheet.append(["Expenses", 0])
    sheet.append(["Net", "=B1-B2"])
    book.create_sheet("History").sheet_state = "hidden"
    book.save(path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("customXml/example.xml", "<example>preserve me</example>")


def test_january_uses_previous_december():
    assert previous_period(date(2030, 1, 10)) == "2029-12"


def test_ytd_rejects_gap_duplicate_and_wrong_end():
    sheet = openpyxl.Workbook().active
    sheet.append(["Jan 2030", "Mar 2030"])
    with pytest.raises(ValueError):
        ytd_columns(sheet, "2030-03", row=1)
    sheet.cell(1, 2, "Jan 2030")
    with pytest.raises(ValueError):
        ytd_columns(sheet, "2030-01", row=1)
    sheet.cell(1, 2, "Feb 2030")
    assert ytd_columns(sheet, "2030-02", row=1) == [1, 2]


def test_patch_preserves_every_untouched_part_and_formula(tmp_path):
    original, output = tmp_path / "source.xlsx", tmp_path / "output.xlsx"
    template(original)
    updates = [{"sheet": "Summary", "cell": "B1", "value": 1250}]
    patch_archive(original, output, updates)
    sheet = openpyxl.load_workbook(output).get_sheet_by_name("Summary")
    assert sheet["B1"].value == 1250
    assert sheet["B3"].value == "=B1-B2"
    assert openpyxl.load_workbook(output)["History"].sheet_state == "hidden"
    with zipfile.ZipFile(original) as a, zipfile.ZipFile(output) as b:
        assert a.namelist() == b.namelist()
        for name in a.namelist():
            if name != "xl/worksheets/sheet1.xml":
                assert a.read(name) == b.read(name)
    assert verify_archive(original, output, updates)["input_cells"] == 1


@pytest.mark.parametrize("updates", [
    [{"sheet": "Summary", "cell": "B3", "value": 12}],
    [{"sheet": "Summary", "cell": "Z999", "value": 12}],
    [{"sheet": "Summary", "cell": "B1", "value": 12}] * 2,
    [{"sheet": "Summary", "cell": "B1", "value": float("nan")}],
])
def test_unsafe_updates_refused_without_output(tmp_path, updates):
    original, output = tmp_path / "source.xlsx", tmp_path / "output.xlsx"
    template(original)
    with pytest.raises(ValueError):
        patch_archive(original, output, updates)
    assert not output.exists()


def test_no_source_overwrite(tmp_path):
    path = tmp_path / "source.xlsx"
    template(path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        patch_archive(path, path, [])
    assert path.read_bytes() == before


def test_missing_numeric_formula_cache_is_rejected(tmp_path):
    original, calculated = tmp_path / "source.xlsx", tmp_path / "calculated.xlsx"
    template(original)
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(calculated, "w") as dest:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                content = content.replace(b"<f>B1-B2</f><v></v>", b"<f>B1-B2</f><v>100</v>")
            dest.writestr(info, content)
    with pytest.raises(ValueError):
        merge_caches(calculated, original, tmp_path / "final.xlsx")
