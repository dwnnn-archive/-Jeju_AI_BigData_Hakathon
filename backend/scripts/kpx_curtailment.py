"""KPX '제주 태양광·풍력 출력제어' 이력을 시간 단위로 읽는다.

입력: data.go.kr '한국전력거래소_전국 태양광 풍력 제어횟수 및 제주 풍력 제어량' 압축 파일(zip)
또는 그 압축을 푼 폴더. 파일 이름에 '제주'와 '풍력'/'태양광'이 들어간 CSV를 사용한다.

- 풍력: 일자별 행에 1시~24시 **제어량(MWh)** 이 들어 있다. 제어가 없던 날짜는 행 자체가 없다.
  제어량은 "차단 시점 발전량을 차단 시간으로 환산한 참고값"이라 정확한 억제량이 아니다.
- 태양광: 시간 칸이 '출력제어' 또는 0이다(제어량 없음).
- 시간은 1~24(종료 시각)이므로 1을 빼 0~23(시작 시각)으로 바꾼다. 빈 칸은 0으로 본다.
- 풍력 이력은 2024-05-30, 태양광 이력은 2024-06-03에서 끝난다(이후 제주는 시장 기반 제어).
"""

import csv
import zipfile
from datetime import date
from pathlib import Path

CONTROL_FLAG = "출력제어"


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode curtailment CSV")


def _zip_name(info: zipfile.ZipInfo) -> str:
    try:  # 한글 이름이 cp437로 저장된 압축 파일 대응
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _members(source: Path) -> dict[str, bytes]:
    if source.is_dir():
        return {p.name: p.read_bytes() for p in source.glob("*.csv")}
    with zipfile.ZipFile(source) as z:
        return {
            _zip_name(i): z.read(i) for i in z.infolist() if i.filename.lower().endswith(".csv")
        }


def _parse(text: str, cell) -> dict[tuple[date, int], float]:
    out: dict[tuple[date, int], float] = {}
    rows = list(csv.reader(text.splitlines()))
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        d = date.fromisoformat(r[0].strip())
        for i, c in enumerate(r[3:27]):
            value = cell(c.strip())
            if value:
                out[(d, i)] = value
    return out


def _wind_cell(c: str) -> float:
    return float(c) if c else 0.0


def _solar_cell(c: str) -> float:
    return 1.0 if c == CONTROL_FLAG else 0.0


def load_jeju_curtailment(source: Path):
    """(풍력 제어량 MWh, 태양광 제어 여부)를 {(날짜, 0~23시): 값} 으로 반환한다. 없으면 빈 dict."""
    wind: dict[tuple[date, int], float] = {}
    solar: dict[tuple[date, int], float] = {}
    for name, raw in _members(source).items():
        has_wind, has_solar = "풍력" in name, "태양광" in name
        # 이름에 둘 다 있는 파일(예: '제주 태양광 풍력 제어량 및 제어횟수' 요약본)은
        # 시간별 표가 아니라서 풍력/태양광 어느 쪽으로도 읽지 않는다.
        if "제주" not in name or has_wind == has_solar:
            continue
        if has_wind:
            wind = _parse(_decode(raw), _wind_cell)
        else:
            solar = _parse(_decode(raw), _solar_cell)
    return wind, solar
