"""예보 저장 장치: 받은 예보 원본과 판정 기록을 SQLite에 쌓는다.

왜 필요한가
- 기상청은 최근 3일 치 발표분만 다시 준다. 저장하지 않으면 "예보가 실제로 얼마나 틀렸는지"를
  평가하거나 예보 기준으로 임계값을 다시 맞추거나 ML 모델을 개선할 수 없다.
- 실제 서비스가 호출한 예보를 그대로 쌓으므로 학습·평가에 쓰는 입력과 서비스 입력이 같다.

저장 내용
- forecast_issues / forecast_values: 발표(source, 격자, 발표 일시)마다 받은 **모든 항목**의 원본 값.
  source 는 short(단기예보), ultra_fcst(초단기예보), ultra_ncst(초단기실황).
- evaluations: 분석 실행마다 판정 결과, 시간별 발전량·수요 예측, 사용한 입력(당일 점검은 이어 붙인
  날씨와 시간별 출처), 사용한 모델 정보.

저장은 절대로 분석을 막지 않는다. 호출하는 쪽은 safe_* 메서드를 쓴다(실패하면 경고만 남긴다).
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

SOURCES = ("short", "ultra_fcst", "ultra_ncst")


def _float(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None  # 강수량 "강수없음" 같은 범주 문자열은 raw 로만 남긴다


def _valid_rows(source: str, items: list[dict]):
    """(유효일자 YYYY-MM-DD, 시, 항목, 숫자값, 원문)."""
    for item in items:
        if source == "ultra_ncst":
            day, time, raw = item["baseDate"], str(item["baseTime"]), item["obsrValue"]
        else:
            day, time, raw = item["fcstDate"], str(item["fcstTime"]), item["fcstValue"]
        iso = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
        yield iso, int(time[:2]), item["category"], _float(raw), str(raw)


class ForecastArchive:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._ready = False

    @contextmanager
    def _connect(self):
        if not self._ready:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._ready = True
            with self._open() as conn:
                conn.executescript(_SCHEMA)
        with self._open() as conn:
            yield conn

    @contextmanager
    def _open(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # ---- 쓰기 ----

    def record_issue(
        self, source: str, nx: int, ny: int, base_date: str, base_time: str, items: list[dict]
    ) -> int:
        """한 번의 발표(source, 격자, 발표 일시)를 저장한다. 이미 있으면 다시 쓰지 않는다."""
        if source not in SOURCES:
            raise ValueError(f"Unknown forecast source: {source}")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO forecast_issues(source,nx,ny,base_date,base_time,fetched_at)"
                " VALUES(?,?,?,?,?,?)",
                (source, nx, ny, base_date, str(base_time), datetime.now(UTC).isoformat()),
            )
            issue_id = conn.execute(
                "SELECT id FROM forecast_issues WHERE source=? AND nx=? AND ny=? AND base_date=?"
                " AND base_time=?",
                (source, nx, ny, base_date, str(base_time)),
            ).fetchone()[0]
            if cursor.rowcount:  # 새 발표일 때만 값을 쓴다
                conn.executemany(
                    "INSERT OR IGNORE INTO forecast_values"
                    "(issue_id,valid_date,valid_hour,category,value,raw) VALUES(?,?,?,?,?,?)",
                    [(issue_id, *row) for row in _valid_rows(source, items)],
                )
            return issue_id

    def record_evaluation(
        self,
        run_id: str,
        phase: str,
        check_no: int,
        result: dict,
        inputs: dict | None = None,
        models: dict | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evaluations(run_id,phase,check_no,target_date,evaluated_at,from_hour,"
                "risk,peak_ratio,peak_surplus_mwh,peak_hour,result_json,inputs_json,models_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    phase,
                    check_no,
                    result["date"],
                    datetime.now(UTC).isoformat(),
                    result.get("from_hour", 0),
                    result["risk"],
                    result["peak_ratio"],
                    result["peak_surplus_mwh"],
                    result["peak_hour"],
                    json.dumps(result, ensure_ascii=False),
                    json.dumps(inputs, ensure_ascii=False) if inputs is not None else None,
                    json.dumps(models, ensure_ascii=False) if models is not None else None,
                ),
            )

    # 호출하는 쪽은 아래를 쓴다: 저장 실패가 분석을 막지 않는다.
    def safe_record_issue(self, *args, **kwargs) -> None:
        try:
            self.record_issue(*args, **kwargs)
        except Exception:  # noqa: BLE001 - 저장은 부가 기능이라 어떤 오류도 전파하지 않는다
            log.warning("forecast archive: failed to record issue", exc_info=True)

    def safe_record_evaluation(self, *args, **kwargs) -> None:
        try:
            self.record_evaluation(*args, **kwargs)
        except Exception:  # noqa: BLE001
            log.warning("forecast archive: failed to record evaluation", exc_info=True)

    # ---- 읽기 (내보내기·평가용) ----

    def issue_keys(self, source: str) -> set[tuple[int, int, str, str]]:
        """이미 저장한 발표의 (nx, ny, 발표 일자, 발표 시각) 집합."""
        with self._connect() as conn:
            return {
                (r["nx"], r["ny"], r["base_date"], r["base_time"])
                for r in conn.execute(
                    "SELECT nx,ny,base_date,base_time FROM forecast_issues WHERE source=?",
                    (source,),
                )
            }

    def issues(self, source: str | None = None) -> list[dict]:
        query, args = "SELECT * FROM forecast_issues", ()
        if source:
            query, args = query + " WHERE source=?", (source,)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query + " ORDER BY id", args)]

    def values(self, issue_id: int) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT valid_date,valid_hour,category,value,raw FROM forecast_values"
                    " WHERE issue_id=? ORDER BY valid_date,valid_hour,category",
                    (issue_id,),
                )
            ]

    def evaluations(self, run_id: str | None = None) -> list[dict]:
        query, args = "SELECT * FROM evaluations", ()
        if run_id:
            query, args = query + " WHERE run_id=?", (run_id,)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query + " ORDER BY id", args)]

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "issues": conn.execute("SELECT COUNT(*) FROM forecast_issues").fetchone()[0],
                "values": conn.execute("SELECT COUNT(*) FROM forecast_values").fetchone()[0],
                "evaluations": conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0],
            }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS forecast_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL, nx INTEGER NOT NULL, ny INTEGER NOT NULL,
    base_date TEXT NOT NULL, base_time TEXT NOT NULL, fetched_at TEXT NOT NULL,
    UNIQUE(source, nx, ny, base_date, base_time)
);
CREATE TABLE IF NOT EXISTS forecast_values (
    issue_id INTEGER NOT NULL REFERENCES forecast_issues(id),
    valid_date TEXT NOT NULL, valid_hour INTEGER NOT NULL, category TEXT NOT NULL,
    value REAL, raw TEXT NOT NULL,
    PRIMARY KEY (issue_id, valid_date, valid_hour, category)
);
CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL, phase TEXT NOT NULL, check_no INTEGER NOT NULL,
    target_date TEXT NOT NULL, evaluated_at TEXT NOT NULL, from_hour INTEGER NOT NULL,
    risk TEXT NOT NULL, peak_ratio REAL NOT NULL, peak_surplus_mwh REAL NOT NULL,
    peak_hour INTEGER NOT NULL, result_json TEXT NOT NULL, inputs_json TEXT, models_json TEXT
);
CREATE INDEX IF NOT EXISTS evaluations_target ON evaluations(target_date, evaluated_at);
CREATE INDEX IF NOT EXISTS forecast_values_valid ON forecast_values(valid_date, valid_hour);
"""
