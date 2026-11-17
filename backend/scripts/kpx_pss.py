"""KPX '제주 하루전 발전계획용 수요예측(PSS)' 연도별 엑셀을 읽는다 (표준 라이브러리만 사용).

파일 구조: 첫 행은 제목, 둘째 행은 헤더(`구분`, `1h`~`24h`), 이후 `YYYYMMDD` + 24개 값(MW).
엑셀(xlsx)은 XML을 담은 zip이라 openpyxl 없이 읽는다. 시간은 1h~24h(종료 시각)이라 1을 빼
0~23(시작 시각)으로 바꾼다. 실측 수요와 같은 표기임을 확인했다.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime
from pathlib import Path

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group()
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return [
        "".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t"))
        for si in root.findall("m:si", _NS)
    ]


def read_rows(path: Path) -> list[list[str | None]]:
    """첫 번째 시트의 모든 행을 문자열 리스트로 반환한다(빈 칸은 None)."""
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        sheet = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))[
            0
        ]
        root = ET.fromstring(z.read(sheet))
    rows: list[list[str | None]] = []
    for row in root.iter(f"{{{_NS['m']}}}row"):
        cells: dict[int, str | None] = {}
        for c in row.findall("m:c", _NS):
            kind, value = c.get("t"), c.find("m:v", _NS)
            if kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            elif value is None or value.text is None:
                text = None
            elif kind == "s":
                text = shared[int(value.text)]
            else:
                text = value.text
            cells[_col_index(c.get("r"))] = text
        rows.append([cells.get(i) for i in range(max(cells, default=-1) + 1)])
    return rows


def parse_file(path: Path) -> dict[tuple[date, int], float]:
    """(날짜, 0~23시 시작) → 예측 MW."""
    out: dict[tuple[date, int], float] = {}
    for row in read_rows(path):
        head = (row[0] or "").strip() if row else ""
        if not re.fullmatch(r"\d{8}(\.0)?", head):
            continue  # 제목·헤더 행 건너뜀
        d = datetime.strptime(head[:8], "%Y%m%d").date()
        for hour_ending in range(1, 25):
            raw = row[hour_ending] if hour_ending < len(row) else None
            if raw not in (None, ""):
                out[(d, hour_ending - 1)] = float(raw)
    return out


def load_pss(directory: Path) -> dict[tuple[date, int], float]:
    merged: dict[tuple[date, int], float] = {}
    for path in sorted(directory.glob("pssJeju_*.xlsx")):
        merged.update(parse_file(path))
    return merged
