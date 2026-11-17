"""제주데이터허브 전기자동차 충전 이력(월별·요일별)으로 EV 이용 패턴을 만든다.

실행: python -m scripts.collect_ev_history [YYYYMM ...] [--max-new-months N]
필요: backend/.env 의 JEJUHUB_PROJECT_KEY (월별·요일별 충전 이력 데이터가 같은 프로젝트에 담겨 있어야 한다).
기본 달은 출력제한이 몰리는 봄 2개(2021-04, 2022-04)다. 새로 받는 달은 기본 3개까지만 허용한다.
호출 내역은 runtime/hub_calls.log 에 남고, 끝날 때 이번 실행의 호출 횟수를 출력한다. 이력은 2021-01 ~ 2022-06 구간만 있다.

- 허브 API는 **하루 호출 한도**가 있다. 월 하나를 받는 데 월별 약 170회·요일별 약 85회를 쓰며,
  실제로 6개월을 받자 월별 한도가 찼다. 그래서 받은 달은 runtime/ev_history_raw/ 에 저장하고,
  다시 실행하면 저장된 달은 건너뛰고 이어받는다. 한도가 차면 거기서 멈추고 **받은 달만으로** 패턴을 만든다.
- 저장: EV_PROFILE_PATH(기본 runtime/ev_profile.json). runtime/ 아래라 Git에 올라가지 않는다.
"""

import sys
import time
from functools import partial

import httpx

from app.core.config import Settings
from app.providers.jejuhub_ev import QuotaExceeded, call_count, enable_call_log
from app.providers.jejuhub_ev_history import (
    MONTHLY_URL,
    WEEKDAY_URL,
    build_profile,
    cached_rows,
    fetch_rows,
    save_profile,
)

DEFAULT_MONTHS = ["202104", "202204"]  # 봄 두 해. 한 달에 약 255회를 쓴다.
MAX_NEW_MONTHS = 3  # 한 번에 새로 받을 수 있는 달 수. 저장본이 있는 달은 호출이 없어 세지 않는다.


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
    new_months = [
        m
        for m in months
        if not ((cache / f"monthly-{m}.json").exists() and (cache / f"weekday-{m}.json").exists())
    ]
    if len(new_months) > limit:
        print(
            f"새로 받을 달이 {len(new_months)}개입니다(한 달 약 255회). 한 번에 {limit}개까지만 받습니다. "
            f"줄이거나 --max-new-months 로 올리세요.",
            file=sys.stderr,
        )
        return 2
    enable_call_log(settings.ev_profile_path.parent / "hub_calls.log")
    monthly: list[dict] = []
    weekday: list[dict] = []
    stopped = None
    started = time.time()
    with httpx.Client(timeout=settings.http_timeout) as client:
        for m in months:
            params = {"startDate": m, "endDate": m}
            try:
                got, new1 = cached_rows(
                    cache,
                    "monthly",
                    m,
                    partial(fetch_rows, key, MONTHLY_URL, params, client=client),
                )
                monthly += got
                wk, new2 = cached_rows(
                    cache,
                    "weekday",
                    m,
                    partial(fetch_rows, key, WEEKDAY_URL, params, client=client),
                )
                weekday += wk
            except QuotaExceeded:
                stopped = m
                break
            except RuntimeError as exc:
                print(f"{m} 수집 실패: {exc}", file=sys.stderr)
                return 1
            origin = "새로 받음" if (new1 or new2) else "저장본 사용"
            print(
                f"{m}: 월별 {len(got):,}건, 요일별 {len(wk):,}건 ({origin}, {time.time() - started:.0f}초)",
                flush=True,
            )
    print(f"이번 실행 허브 호출 {call_count()}회 (내역: runtime/hub_calls.log)")
    if stopped:
        print(
            f"{stopped}부터 하루 호출 한도로 멈췄습니다. 한도가 풀린 뒤 다시 실행하면 이어받습니다."
        )
    try:
        profile = build_profile(monthly, weekday)
    except ValueError:
        print("받은 월별 자료가 없어 이용 패턴을 만들 수 없습니다.", file=sys.stderr)
        return 1
    save_profile(profile, settings.ev_profile_path)
    print(f"저장 → {settings.ev_profile_path} (사용한 달: {', '.join(profile['months'])})")
    print(f"사용 {profile['rows_used']:,}건, 제외 {profile['rows_skipped']:,}건")
    for name in ("slow", "fast"):
        g = profile[name]
        if g is None:
            print(f"{name}: 자료 없음")
            continue
        occ = g["occupancy"]
        print(
            f"{name}: 평균 전력 {g['avg_kw']:.1f} kW, 점유율 12시 {occ[12]:.1%} / 최대 {max(occ):.1%}"
            f"(월평균 충전기 {g['chargers_per_month_avg']:.0f}기)"
        )
    print("요일 보정:", {w: round(v, 2) for w, v in profile["weekday_factor"].items()})
    return 1 if stopped and not profile["months"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
