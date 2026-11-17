import { useId } from "react";
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

export function FlowChart({ hourly }: { hourly: Hourly }) {
  const clipId = useId().replace(/:/g, "");
  const W = 1000;
  const H = 300;
  const top = 40;
  const bottom = 270;
  const rows = [...hourly].sort((a, b) => a.hour - b.hour);
  const values = rows.flatMap((r) => [r.generation_mwh, r.demand_mwh]);
  const lo = Math.min(...values) * 0.85;
  const hi = Math.max(...values) * 1.05 || 1;
  const x = (h: number) => (h / 23) * W;
  const y = (v: number) => bottom - ((v - lo) / (hi - lo)) * (bottom - top);
  const gen = smoothPath(rows.map((r) => [x(r.hour), y(r.generation_mwh)]));
  const dem = smoothPath(rows.map((r) => [x(r.hour), y(r.demand_mwh)]));
  const span = surplusSpan(rows);
  return (
    <figure className="flow-chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={
          span
            ? `시간별 발전량과 수요. ${span[0]}시부터 ${span[1]}시까지 발전량이 수요보다 많습니다.`
            : "시간별 발전량과 수요. 발전량이 수요를 넘는 시간이 없습니다."
        }
      >
        <defs>
          <clipPath id={clipId}>
            <path d={`${dem} L${W},0 L0,0 Z`} />
          </clipPath>
        </defs>
        {[top, (top + bottom) / 2, bottom].map((gy) => (
          <line key={gy} x1="0" x2={W} y1={gy} y2={gy} className="flow-grid" />
        ))}
        <path
          d={`${gen} L${W},${H} L0,${H} Z`}
          className="flow-surplus"
          clipPath={`url(#${clipId})`}
        />
        <path d={dem} className="flow-demand" />
        <path d={gen} className="flow-generation" />
      </svg>
      {span && (
        <span
          className="flow-callout"
          style={{ left: `${((span[0] + span[1] - 1) / 2 / 23) * 100}%` }}
        >
          {span[0]}–{span[1]}시 · 잉여 발생
        </span>
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
