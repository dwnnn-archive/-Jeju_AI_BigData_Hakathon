"""충전기 점유율이 오늘 더 높아졌다면 EV 용량과 시연 위험일 결과가 어떻게 달라지는지 계산한다.

실행(backend/ 에서): python -m scripts.ev_usage_sensitivity
필요: runtime/ev_stations.json(충전소 목록), runtime/ev_profile.json(충전 이력 프로필).
충전 이력은 2021·2022년 자료라 오늘의 이용은 더 많을 수 있다. 일별 이력(collect_ev_daily)에서
하루 평균 충전량이 1년 만에 27% 늘었으므로, 프로필의 시간대별 점유율을 k배로 키워 본다(상한 100%).
"""

import copy
import json
from datetime import date

from app.core.config import Settings
from app.domain.rules import allocate
from app.domain.schemas import Capacities
from app.providers.jejuhub_ev import ev_capacity, load_snapshot
from app.providers.jejuhub_ev_history import load_profile

MULTIPLIERS = (1.0, 1.27, 2.0, 3.0, 4.0)
SURPLUS_MWH = 230  # 시연 위험일의 피크 잉여전력
HOUR = 12


def scaled(profile: dict, k: float) -> dict:
    out = copy.deepcopy(profile)
    for group in ("slow", "fast"):
        out[group]["occupancy"] = [min(1.0, o * k) for o in out[group]["occupancy"]]
    return out


def main() -> int:
    s = Settings()
    loaded = load_snapshot(s.ev_snapshot_path)
    profile = load_profile(s.ev_profile_path)
    if loaded is None or profile is None:
        print("충전소 파일과 충전 이력 프로필이 필요합니다(매뉴얼 4절).")
        return 1
    stations, _ = loaded
    summary_path = s.ev_profile_path.parent / "ev_daily_summary.json"
    if summary_path.exists():
        d = json.loads(summary_path.read_text(encoding="utf-8"))
        if {"202104", "202204"} <= d.keys():
            a, b = d["202104"]["mean_kwh_per_day"], d["202204"]["mean_kwh_per_day"]
            print(f"하루 평균 충전량 2021-04 {a:,.0f} -> 2022-04 {b:,.0f} kWh (x{b / a:.2f})")
    print(f"점유율 배수 k에 따른 {HOUR}시 EV 용량과 위험일(잉여 {SURPLUS_MWH} MWh) 결과")
    for k in MULTIPLIERS:
        p = scaled(profile, k)
        ev = ev_capacity(
            stations,
            HOUR,
            slow_kw=s.ev_slow_kw,
            fast_kw=s.ev_fast_kw,
            idle_ratio=s.ev_idle_ratio,
            profile=p,
            target_date=date(2026, 11, 18),
        )
        r = allocate(SURPLUS_MWH, Capacities(ev=ev["capacity_mwh"]))
        occ = f"{p['slow']['occupancy'][HOUR]:.0%}/{p['fast']['occupancy'][HOUR]:.0%}"
        print(
            f"k={k:<4}: 점유율(완속/급속) {occ} | EV {ev['capacity_mwh']:6.1f} MWh | "
            f"흡수 {r['absorbed_mwh']:.1f} ({r['absorption_pct']:.1f}%) 잔여 {r['residual_mwh']:.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
