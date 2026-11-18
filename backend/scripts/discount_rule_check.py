"""정부 전기차 충전 할인 규칙(주말·공휴일 낮 11~14시)이 과거 출력제한일을 얼마나 덮는지 센다.

사용 (backend/ 에서, 먼저 scripts.evaluate_pipeline 으로 runtime/e2e/days.json 을 만들어 둔다):
    python -m scripts.discount_rule_check
    python -m scripts.discount_rule_check --days runtime/e2e/days.json

- 할인 기간은 2026년 시행 기간(봄 4/18~5/31, 가을 9/5~10/31)을 **같은 월일에 그대로** 과거 날짜에 대 본 것이다.
  2023~2024년에 실제로 할인이 있었던 것이 아니라 "같은 규칙이 있었다면"의 계산이다.
- 할인 적용일 = 할인 기간 안의 주말·공휴일, 할인 시간 = 11~14시(시작 시각 11, 12, 13).
- 규칙은 충전을 유도하는 정책이고 위험일을 예측하는 도구가 아니다. 이 계산은 "달력 기준이 실제
  출력제한일을 얼마나 덮는가"만 보여 준다.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from app.domain.kr_holidays import is_day_off

DISCOUNT_HOURS = frozenset({11, 12, 13})
RISK_FLAGS = ("CAUTION", "CRITICAL")


def in_window(d: date) -> bool:
    md = (d.month, d.day)
    return (4, 18) <= md <= (5, 31) or (9, 5) <= md <= (10, 31)


def is_discount_day(d: date) -> bool:
    return in_window(d) and is_day_off(d)


def summarize(days: list[dict]) -> dict:
    rows = [(date.fromisoformat(r["date"]), r) for r in days]
    curtailed = [(d, r) for d, r in rows if r["actual"]]
    on_discount = [(d, r) for d, r in curtailed if is_discount_day(d)]
    overlapping = [(d, r) for d, r in on_discount if DISCOUNT_HOURS & set(r["actual_hours"])]
    discount_days = [(d, r) for d, r in rows if is_discount_day(d)]
    hours_total = sum(len(r["actual_hours"]) for _, r in curtailed)
    hours_covered = sum(len(DISCOUNT_HOURS & set(r["actual_hours"])) for _, r in on_discount)
    return {
        "days": len(rows),
        "curtailed_days": len(curtailed),
        "curtailed_outside_window": sum(1 for d, _ in curtailed if not in_window(d)),
        "curtailed_weekdays": sum(1 for d, _ in curtailed if not is_day_off(d)),
        "discount_days": len(discount_days),
        "discount_days_with_curtailment": sum(1 for _, r in discount_days if r["actual"]),
        "curtailed_on_discount_days": len(on_discount),
        "curtailed_overlapping_discount_hours": len(overlapping),
        "curtailed_hours_total": hours_total,
        "curtailed_hours_covered": hours_covered,
        "agent_flagged_days": sum(1 for _, r in curtailed if r["risk"] in RISK_FLAGS),
    }


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--days", type=Path, default=Path("runtime/e2e/days.json"))
    a = p.parse_args()
    s = summarize(json.loads(a.days.read_text(encoding="utf-8")))
    n = s["curtailed_days"]
    print(f"점검 {s['days']}일 중 출력제한일 {n}일")
    print(
        f"- 할인 기간 밖 제한일 {s['curtailed_outside_window']}일, 평일 제한일 {s['curtailed_weekdays']}일"
        f" ({pct(s['curtailed_weekdays'], n)})"
    )
    print(
        f"- 할인 적용일(기간 안 주말·공휴일) {s['discount_days']}일 중 제한이 있던 날"
        f" {s['discount_days_with_curtailment']}일 ({pct(s['discount_days_with_curtailment'], s['discount_days'])})"
    )
    print(
        f"- 규칙이 닿는 제한일(할인 적용일) {s['curtailed_on_discount_days']}/{n} ({pct(s['curtailed_on_discount_days'], n)})"
    )
    print(
        f"- 그중 제한 시간이 11~14시와 겹친 제한일 {s['curtailed_overlapping_discount_hours']}/{n}"
        f" ({pct(s['curtailed_overlapping_discount_hours'], n)})"
    )
    print(
        f"- 제한 시간 {s['curtailed_hours_total']}시간 중 할인 시간에 든 시간 {s['curtailed_hours_covered']}"
        f" ({pct(s['curtailed_hours_covered'], s['curtailed_hours_total'])})"
    )
    print(
        f"- 에이전트(주의 이상) 포착 {s['agent_flagged_days']}/{n} ({pct(s['agent_flagged_days'], n)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
