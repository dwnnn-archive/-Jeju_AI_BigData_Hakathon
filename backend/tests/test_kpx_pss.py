import zipfile
from datetime import date

from scripts.kpx_pss import load_pss, parse_file

SHEET = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>
<row r="1"><c r="A1" t="s"><v>0</v></c></row>
<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>
<row r="3"><c r="A3" t="inlineStr"><is><t>20240101</t></is></c>{cells}</row>
<row r="4"><c r="A4"><v>20240102</v></c><c r="B4"><v>730</v></c><c r="Z4"><v>1</v></c></row>
</sheetData>
</worksheet>"""
SHARED = """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<si><t>일자별 발전계획용 수요예측 리스트(제주) (단위 : MW)</t></si>
<si><t>구분</t></si><si><t>1h</t></si>
</sst>"""


def _xlsx(path):
    # 1h=700, 2h=650, ... 24h까지 숫자 칸, 일부 칸은 비움
    cells = "".join(
        f'<c r="{chr(66 + i) if i < 25 else "A"}3"><v>{700 - 10 * i}</v></c>' for i in range(2)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", SHEET.format(cells=cells))
        z.writestr("xl/sharedStrings.xml", SHARED)


def test_reads_titles_inline_strings_numbers_and_converts_to_start_hour(tmp_path):
    f = tmp_path / "pssJeju_2024.xlsx"
    _xlsx(f)
    s = parse_file(f)
    assert s[(date(2024, 1, 1), 0)] == 700.0  # 1h → 0시
    assert s[(date(2024, 1, 1), 1)] == 690.0
    assert s[(date(2024, 1, 2), 0)] == 730.0  # 날짜가 숫자 칸이어도 읽음
    assert (date(2024, 1, 1), 5) not in s  # 빈 칸은 건너뜀
    assert all(k[0].year == 2024 for k in s)  # 제목·헤더 행은 무시


def test_load_pss_merges_year_files(tmp_path):
    _xlsx(tmp_path / "pssJeju_2024.xlsx")
    _xlsx(tmp_path / "pssJeju_2025.xlsx")  # 같은 날짜가 들어 있어도 병합 가능해야 한다
    assert len(load_pss(tmp_path)) == len(parse_file(tmp_path / "pssJeju_2024.xlsx"))
