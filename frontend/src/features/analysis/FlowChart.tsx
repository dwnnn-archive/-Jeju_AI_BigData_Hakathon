import { useId, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { AnalysisRun } from "./types";

export type Hourly = NonNullable<AnalysisRun["result"]>["hourly"];

export const pad = (h: number) => String(h).padStart(2, "0");
export const fmt = (value: number) =>
  value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });

export const resourceNames = {
  bess: "ESS 충전",
  vpp: "VPP 유연성 자원",
  p2x: "수전해 수소 생산",
  ev: "전기차 충전 전환",
} as const;
export const sourceNames: Record<string, string> = {
  weather: "기상",
  generation: "발전량",
  demand: "수요",
};

export function longDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
    weekday: "long",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** First to last hour with surplus, as [start, endExclusive]. */
export function surplusSpan(hourly: Hourly): [number, number] | null {
  const hours = hourly.filter((r) => r.surplus_mwh > 0).map((r) => r.hour);
  return hours.length ? [Math.min(...hours), Math.max(...hours) + 1] : null;
}

/** Monotone cubic path: smooth without overshooting the real values. */
function smoothPath(points: [number, number][]) {
  const n = points.length;
  if (n < 2) return "";
  const dx = points.slice(1).map((p, i) => p[0] - points[i][0]);
  const slope = points.slice(1).map((p, i) => (p[1] - points[i][1]) / dx[i]);
  const tangent = points.map((_, i) => {
    if (i === 0) return slope[0];
    if (i === n - 1) return slope[n - 2];
    return slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2;
  });
  for (let i = 0; i < n - 1; i++) {
    if (slope[i] === 0) {
      tangent[i] = tangent[i + 1] = 0;
      continue;
    }
    const a = tangent[i] / slope[i];
    const b = tangent[i + 1] / slope[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      tangent[i] = t * a * slope[i];
      tangent[i + 1] = t * b * slope[i];
    }
  }
  let d = `M${points[0][0]},${points[0][1]}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const h = dx[i] / 3;
    d += ` C${x0 + h},${y0 + tangent[i] * h} ${x1 - h},${y1 - tangent[i + 1] * h} ${x1},${y1}`;
  }
  return d;
}

export function FlowChart({
  hourly,
  warningRatio,
}: {
  hourly: Hourly;
  warningRatio?: number;
}) {
  const clipId = useId().replace(/:/g, "");
  const W = 1000;
  const H = 300;
  const top = 40;
  const bottom = 270;
  const rows = [...hourly].sort((a, b) => a.hour - b.hour);
  const values = rows.flatMap((r) => [
    r.generation_mwh,
    r.demand_mwh,
    r.demand_mwh * (warningRatio ?? 1),
  ]);
  const lo = Math.min(...values) * 0.85;
  const hi = Math.max(...values) * 1.05 || 1;
  const x = (h: number) => (h / 23) * W;
  const y = (v: number) => bottom - ((v - lo) / (hi - lo)) * (bottom - top);
  const gen = smoothPath(rows.map((r) => [x(r.hour), y(r.generation_mwh)]));
  const dem = smoothPath(rows.map((r) => [x(r.hour), y(r.demand_mwh)]));
  const boundary = smoothPath(
    rows.map((r) => [x(r.hour), y(r.demand_mwh * (warningRatio ?? 1))]),
  );
  const basis =
    warningRatio == null
      ? "수요"
      : `수요의 ${Math.round(warningRatio * 100)}% 대응 기준`;
  const span = surplusSpan(rows);
  const [active, setActive] = useState<number | null>(null);
  const activeRow = active == null ? undefined : rows[active];
  const hourAt = (event: PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(
      Math.max((event.clientX - box.left) / box.width, 0),
      1,
    );
    return Math.round(ratio * (rows.length - 1));
  };
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (!step) return;
    event.preventDefault();
    setActive((current) =>
      Math.min(Math.max((current ?? -step) + step, 0), rows.length - 1),
    );
  };
  // 위치는 SVG 좌표(0..W, 0..H)를 백분율로 바꿔 HTML 위에 겹친다(원이 찌그러지지 않게).
  const pctX = (h: number) => `${(x(h) / W) * 100}%`;
  const pctY = (v: number) => `${(y(v) / H) * 100}%`;
  // 눈금: 세 줄의 가로선이 몇 MWh인지 왼쪽에 적는다.
  const ticks = [top, (top + bottom) / 2, bottom].map((gy) => ({
    gy,
    value: lo + ((bottom - gy) / (bottom - top)) * (hi - lo),
  }));
  return (
    <figure className="flow-chart">
      <ul className="flow-legend" aria-label="그래프 범례">
        <li>
          <span className="flow-key flow-key--generation" aria-hidden="true" />
          발전량 (예측)
        </li>
        <li>
          <span className="flow-key flow-key--demand" aria-hidden="true" />
          수요 (예측)
        </li>
        {warningRatio != null && (
          <li>
            <span className="flow-key flow-key--boundary" aria-hidden="true" />
            대응 기준 · 수요의 {Math.round(warningRatio * 100)}%
          </li>
        )}
        {warningRatio != null && (
          <li>
            <span className="flow-key flow-key--surplus" aria-hidden="true" />
            기준 초과분 (잉여)
          </li>
        )}
      </ul>
      <div
        className="flow-plot"
        tabIndex={0}
        role="group"
        aria-label="시간대별 수치 보기: 마우스를 올리거나 좌우 화살표 키로 시간을 옮깁니다."
        onPointerMove={(e) => setActive(hourAt(e))}
        onPointerDown={(e) => setActive(hourAt(e))}
        onPointerLeave={() => setActive(null)}
        onFocus={() => setActive((current) => current ?? 0)}
        onBlur={() => setActive(null)}
        onKeyDown={onKey}
      >
        {span && (
          <span
            className="flow-callout"
            style={{ left: `${((span[0] + span[1] - 1) / 2 / 23) * 100}%` }}
          >
            {span[0]}–{span[1]}시 · 잉여 발생
          </span>
        )}
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          role="img"
          aria-label={
            span
              ? `시간별 발전량과 수요. ${span[0]}시부터 ${span[1]}시까지 발전량이 ${basis}보다 많습니다.`
              : `시간별 발전량과 수요. 발전량이 ${basis}를 넘는 시간이 없습니다.`
          }
        >
          <defs>
            <clipPath id={clipId}>
              <path d={`${boundary} L${W},0 L0,0 Z`} />
            </clipPath>
          </defs>
          {[top, (top + bottom) / 2, bottom].map((gy) => (
            <line
              key={gy}
              x1="0"
              x2={W}
              y1={gy}
              y2={gy}
              className="flow-grid"
            />
          ))}
          <path
            d={`${gen} L${W},${H} L0,${H} Z`}
            className="flow-surplus"
            clipPath={`url(#${clipId})`}
          />
          <path d={dem} className="flow-demand" />
          {warningRatio != null && (
            <path
              d={boundary}
              fill="none"
              stroke="#956100"
              strokeWidth="2"
              strokeDasharray="3 5"
            />
          )}
          <path d={gen} className="flow-generation" />
        </svg>
        {ticks.map(({ gy, value }) => (
          <span
            key={gy}
            className="flow-ytick"
            style={{ top: `${(gy / H) * 100}%` }}
            aria-hidden="true"
          >
            {Math.round(value).toLocaleString()} MWh
          </span>
        ))}
        {activeRow && (
          <div className="flow-hover" aria-live="polite">
            <span
              className="flow-hover-line"
              style={{ left: pctX(activeRow.hour) }}
            />
            <span
              className="flow-hover-dot flow-hover-dot--demand"
              style={{
                left: pctX(activeRow.hour),
                top: pctY(activeRow.demand_mwh),
              }}
            />
            {warningRatio != null && (
              <span
                className="flow-hover-dot flow-hover-dot--boundary"
                style={{
                  left: pctX(activeRow.hour),
                  top: pctY(activeRow.demand_mwh * warningRatio),
                }}
              />
            )}
            <span
              className="flow-hover-dot flow-hover-dot--generation"
              style={{
                left: pctX(activeRow.hour),
                top: pctY(activeRow.generation_mwh),
              }}
            />
            <div
              className={
                "flow-tooltip" +
                (activeRow.hour > rows.length / 2 ? " flow-tooltip--left" : "")
              }
              style={{ left: pctX(activeRow.hour) }}
            >
              <strong>
                {pad(activeRow.hour)}:00–{pad((activeRow.hour + 1) % 24)}:00
              </strong>
              <dl>
                <dt className="is-generation">발전량</dt>
                <dd>{fmt(activeRow.generation_mwh)} MWh</dd>
                <dt className="is-demand">수요</dt>
                <dd>{fmt(activeRow.demand_mwh)} MWh</dd>
                {warningRatio != null && (
                  <>
                    <dt className="is-boundary">
                      기준({Math.round(warningRatio * 100)}%)
                    </dt>
                    <dd>{fmt(activeRow.demand_mwh * warningRatio)} MWh</dd>
                  </>
                )}
                <dt>잉여</dt>
                <dd>{fmt(activeRow.surplus_mwh)} MWh</dd>
                <dt>발전/수요</dt>
                <dd>
                  {Math.round(activeRow.ratio * 100)}% ·{" "}
                  {riskNames[activeRow.risk]}
                </dd>
              </dl>
            </div>
          </div>
        )}
      </div>
      {warningRatio != null && (
        <figcaption className="dv-caption">
          발전량(초록 선)이 대응 기준(갈색 점선: 수요의{" "}
          {Math.round(warningRatio * 100)}%)을 넘는 구간이 초록 음영으로
          표시됩니다. 그래프에 마우스를 올리면 시간대별 수치가 보입니다.
        </figcaption>
      )}
      <div className="flow-axis" aria-hidden="true">
        {["00시", "06시", "12시", "18시", "23시"].map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
    </figure>
  );
}

const riskNames = { NORMAL: "정상", CAUTION: "경계", CRITICAL: "위험" };

/** 24-cell strip: one cell per KST hour, colored by the server's risk level. */
export function RiskStrip({ hourly }: { hourly: Hourly }) {
  const rows = [...hourly].sort((a, b) => a.hour - b.hour);
  const count = (risk: keyof typeof riskNames) =>
    rows.filter((r) => r.risk === risk).length;
  return (
    <div className="ed-risk-strip">
      <div className="ed-risk-strip-cells">
        {rows.map((r) => (
          <span
            key={r.hour}
            className={`ed-risk-cell ed-risk-cell--${r.risk.toLowerCase()}`}
            title={`${pad(r.hour)}시 · ${riskNames[r.risk]} · 잉여 ${fmt(r.surplus_mwh)} MWh`}
          />
        ))}
      </div>
      <p className="ed-risk-strip-legend">
        정상 {count("NORMAL")}시간 · 경계 {count("CAUTION")}시간 · 위험{" "}
        {count("CRITICAL")}시간
      </p>
    </div>
  );
}
