import zipfile

import openpyxl
import pytest

from scripts.workbook import merge_caches


def test_cache_import_rejects_changed_input_values(tmp_path):
    source, calculated = tmp_path / "source.xlsx", tmp_path / "calculated.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet["A1"] = 10
    sheet["A2"] = "=A1*2"
    book.save(source)
    sheet["A1"] = 99
    book.save(calculated)
    with zipfile.ZipFile(calculated) as archive:
        parts = [(info, archive.read(info.filename)) for info in archive.infolist()]
    with zipfile.ZipFile(calculated, "w") as archive:
        for info, content in parts:
            if info.filename == "xl/worksheets/sheet1.xml":
                content = content.replace(b"<f>A1*2</f><v />", b"<f>A1*2</f><v>198</v>")
                content = content.replace(b"<f>A1*2</f><v></v>", b"<f>A1*2</f><v>198</v>")
            archive.writestr(info, content)
    with pytest.raises(ValueError, match="recalculated"):
        merge_caches(source, calculated, tmp_path / "final.xlsx")
