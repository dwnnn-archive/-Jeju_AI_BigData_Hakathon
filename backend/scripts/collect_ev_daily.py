"""제주데이터허브 전기자동차 충전 이력(일별)을 받아 날짜별 변동을 요약한다.

실행: python -m scripts.collect_ev_daily [YYYYMM ...] [--max-new-months N]
필요: backend/.env 의 JEJUHUB_PROJECT_KEY (일별 이력 데이터가 같은 프로젝트에 담겨 있어야 한다).
기본 달은 월별 이력과 같은 2021-04, 2022-04다. 한 달에 약 210~250회를 쓴다.

- 일별에는 충전 시작 시각·요일이 없어 시간대 점유율(ev_profile.json)은 바꾸지 않는다.
- 하는 일: 날짜별 총 충전량의 변동(혼잡한 날이 평균의 몇 배인가), 달력 요일별 평균,
  그리고 같은 달 월별 이력과 합계가 맞는지 확인한다.
- 받은 달은 runtime/ev_history_raw/ 에 저장해 다시 받지 않는다. 호출 내역은 runtime/hub_calls.log.
- 결과 요약: runtime/ev_daily_summary.json
"""

import json
import sys
from functools import partial

import httpx

from app.core.config import Settings
from app.providers.jejuhub_ev import QuotaExceeded, call_count, enable_call_log
from app.providers.jejuhub_ev_history import (
    DAILY_URL,
    cached_rows,
    daily_summary,
    fetch_rows,
    month_range,
)

DEFAULT_MONTHS = ["202104", "202204"]
MAX_NEW_MONTHS = 3  # 저장본이 있는 달은 호출이 없어 세지 않는다.


def main(argv: list[str]) -> int:
    limit = MAX_NEW_MONTHS
    if "--max-new-months" in argv:
        i = argv.index("--max-new-months")
        try:
            limit = int(argv[i + 1])
        except (IndexError, ValueError):
            print("--max-new-months 뒤에 숫자를 넣으세요.", file=sys.stderr)
            return 2
        argv = argv[:i] + argv[i + 2 :]
    months = argv or DEFAULT_MONTHS
    if not all(len(m) == 6 and m.isdigit() for m in months):
        print("달은 YYYYMM 형식으로 입력하세요.", file=sys.stderr)
        return 2
    settings = Settings()
    if settings.jejuhub_project_key is None:
        print("JEJUHUB_PROJECT_KEY가 설정되어 있지 않습니다(backend/.env).", file=sys.stderr)
        return 2
    key = settings.jejuhub_project_key.get_secret_value()
    cache = settings.ev_profile_path.parent / "ev_history_raw"
    new_months = [m for m in months if not (cache / f"daily-{m}.json").exists()]
    if len(new_months) > limit:
        print(
            f"새로 받을 달이 {len(new_months)}개입니다(한 달 약 210~250회). "
            f"한 번에 {limit}개까지만 받습니다. 줄이거나 --max-new-months 로 올리세요.",
            file=sys.stderr,
        )
        return 2
    enable_call_log(settings.ev_profile_path.parent / "hub_calls.log")
    summaries = {}
    with httpx.Client(timeout=settings.http_timeout) as client:
        for m in months:
            try:
                rows, new = cached_rows(
                    cache,
                    "daily",
                    m,
                    partial(fetch_rows, key, DAILY_URL, month_range(m), client=client),
                )
            except QuotaExceeded:
                print(f"{m}부터 하루 호출 한도로 멈췄습니다. 다시 실행하면 이어받습니다.")
                break
            except RuntimeError as exc:
                print(f"{m} 수집 실패: {exc}", file=sys.stderr)
                return 1
            try:
                monthly = json.loads((cache / f"monthly-{m}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                monthly = None
            s = summaries[m] = daily_summary(rows, monthly)
            origin = "새로 받음" if new else "저장본 사용"
            print(
                f"{m}: {len(rows):,}행 ({origin}) · {s['days']}일 · "
                f"하루 평균 {s['mean_kwh_per_day']:,.0f} kWh · "
                f"혼잡일(상위 5%) 평균의 {s['p95_ratio']:.2f}배, 최대 {s['max_ratio']:.2f}배 · "
                f"주말/평일 {s['weekend_over_weekday']:.2f}"
            )
            if "vs_monthly" in s:
                v = s["vs_monthly"]
                print(
                    f"    월별 합계와 비교: 충전량 {v['kwh_diff_pct']:+.2f}%, "
                    f"횟수 {v['count_diff_pct']:+.2f}%"
                )
    print(f"이번 실행 허브 호출 {call_count()}회 (내역: runtime/hub_calls.log)")
    if summaries:
        out = settings.ev_profile_path.parent / "ev_daily_summary.json"
        out.write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
