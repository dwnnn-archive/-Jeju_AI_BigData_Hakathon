import csv
from datetime import date

from scripts.kpx_generation import WIND_USABLE_END, load_jeju, write_csv


def _w(path, header, rows):
    path.write_text(
        "\n".join([",".join(header)] + [",".join(map(str, r)) for r in rows]), encoding="cp949"
    )


def test_formats_hours_units_and_regions_are_normalized(tmp_path):
    # wide, 1~24시(종료 시각), 빈 값, 서울은 제외
    _w(
        tmp_path / "20230228.csv",
        ["거래일자", "거래시간", "지역", "태양광 발전량(MWh)", "풍력 발전량(MWh)"],
        [
            ("2023-01-01", 1, "제주도", "  ", 5.5),
            ("2023-01-01", 24, "제주도", 2, 7),
            ("2023-01-01", 1, "서울시", 9, 9),
        ],
    )
    # long, 지역명 '제주', 연료원 분리
    _w(
        tmp_path / "20241231.csv",
        ["거래일자", "거래시간", "지역", "연료원", "전력거래량(MWh)"],
        [("2024-01-01", 1, "제주", "풍력", 3), ("2024-01-01", 1, "제주도", "태양광", 4)],
    )
    # 태양광 전용 kWh, 1~24시
    _w(
        tmp_path / "20211231.csv",
        ["거래일자", "거래시간", "지역", "발전량"],
        [("2021-05-01", 13, "제주도", 85904.927)],
    )
    # 태양광 전용 0~23시(시작 시각), 단위 없는 열 이름은 MWh
    _w(
        tmp_path / "20201231.csv",
        ["연료원", "지역세부구분", "거래일", "시간", "전력거래량"],
        [("태양광", "제주도", "2019-05-01", "00", 1.5)],
    )
    s = load_jeju(tmp_path)
    assert s[(date(2023, 1, 1), 0)] == {"wind": 5.5}  # 1시 → 0시, 빈 태양광 값은 없는 값
    assert s[(date(2023, 1, 1), 23)] == {"solar": 2.0, "wind": 7.0}  # 24시 → 23시
    assert s[(date(2024, 1, 1), 0)] == {"wind": 3.0, "solar": 4.0}
    assert s[(date(2021, 5, 1), 12)]["solar"] == 85.904927  # kWh → MWh
    assert s[(date(2019, 5, 1), 0)]["solar"] == 1.5  # 0시 기준은 그대로
    assert all(k[0] != date(2023, 1, 2) for k in s)


def test_overlap_prefers_20230228_and_fills_missing_from_others(tmp_path):
    _w(
        tmp_path / "a20230228.csv",
        ["거래일자", "거래시간", "지역", "태양광 발전량(MWh)", "풍력 발전량(MWh)"],
        [("2022-01-01", 1, "제주도", 1, "")],
    )
    _w(
        tmp_path / "b.csv",
        ["거래일자", "거래시간", "지역", "연료원", "발전량(MWh)"],
        [("2022-01-01", 1, "제주도", "태양광", 99), ("2022-01-01", 1, "제주도", "풍력", 8)],
    )
    s = load_jeju(tmp_path)[(date(2022, 1, 1), 0)]
    assert s["solar"] == 1  # 우선 파일 값 유지
    assert s["wind"] == 8  # 빈 값은 다른 파일로 보완


def test_output_marks_wind_after_cutoff_as_unusable(tmp_path):
    series = {
        (WIND_USABLE_END, 5): {"wind": 10.0, "solar": 0.0},
        (date(2024, 6, 1), 5): {"wind": 0.5, "solar": 1.0},
        (date(2020, 1, 1), 5): {"wind": None, "solar": 1.0},
    }
    out = tmp_path / "o.csv"
    assert write_csv(series, out) == 3
    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    assert [r["wind_usable"] for r in rows] == ["0", "1", "0"]
    assert rows[1]["timestamp"] == "2024-05-31T05:00:00+09:00"
    assert rows[0]["wind_mwh"] == ""
