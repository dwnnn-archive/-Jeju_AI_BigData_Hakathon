import zipfile
from datetime import date

from scripts.kpx_curtailment import load_jeju_curtailment

HEADER = "일자,제어지역,누적 시행회차," + ",".join(f"{h}시" for h in range(1, 25))
WIND = (
    HEADER
    + "\n2021-01-13,제주,1,"
    + ",".join(
        ["0"] * 12 + ["12", "28", "25"] + ["0"] * 8 + [""]  # 마지막 칸 빈 값 = 0
    )
)
SOLAR = (
    HEADER + "\n2022-03-06,제주,1," + ",".join(["0"] * 13 + ["출력제어", "출력제어"] + ["0"] * 9)
)
LAND = HEADER + "\n2021-03-16,전남,1," + ",".join(["출력제어"] * 24)
SUMMARY = "일자,횟수\n2024-06-01,30\n2024-06-02,31\n"  # 이름에 태양광·풍력이 둘 다 있는 요약본


def _write(directory):
    (directory / "제주 풍력 출력제어횟수 및 제어량.csv").write_bytes(WIND.encode("cp949"))
    (directory / "제주 태양광 출력제어횟수.csv").write_bytes(SOLAR.encode("utf-8-sig"))
    (directory / "육지 풍력 출력제어횟수.csv").write_bytes(LAND.encode("cp949"))
    (directory / "한국전력거래소_시간별 제주 태양광 풍력 제어량 및 제어횟수.csv").write_bytes(
        SUMMARY.encode("cp949")
    )


def _check(wind, solar):
    # 13~15시(종료 시각) → 12~14시(시작 시각)
    assert wind == {
        (date(2021, 1, 13), 12): 12.0,
        (date(2021, 1, 13), 13): 28.0,
        (date(2021, 1, 13), 14): 25.0,
    }
    assert solar == {(date(2022, 3, 6), 13): 1.0, (date(2022, 3, 6), 14): 1.0}


def test_reads_folder_ignores_mainland_and_ambiguous_summary_file(tmp_path):
    _write(tmp_path)
    _check(*load_jeju_curtailment(tmp_path))


def test_reads_zip_with_korean_names(tmp_path):
    _write(tmp_path)
    archive = tmp_path / "curtail.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for p in tmp_path.glob("*.csv"):
            z.write(p, arcname=p.name)
    _check(*load_jeju_curtailment(archive))


def test_missing_files_return_empty(tmp_path):
    assert load_jeju_curtailment(tmp_path) == ({}, {})
