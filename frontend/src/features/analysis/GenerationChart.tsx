import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Area,
} from "recharts";
import type { AnalysisRun } from "./types";

export function GenerationChart({
  result,
}: {
  result: NonNullable<AnalysisRun["result"]>;
}) {
  return (
    <>
      <div className="chart-legend">
        <span>
          <i className="legend-generation" />
          예상 발전량
        </span>
        <span>
          <i className="legend-demand" />
          예상 수요
        </span>
        <span>
          <i className="legend-surplus" />
          잉여전력
        </span>
        <small>1시간 구간 · MWh</small>
      </div>
      <div
        className="chart"
        role="img"
        aria-label={`${result.date} 시간별 예상 발전량과 수요. 하단 표로도 확인할 수 있습니다.`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={result.hourly}
            margin={{ top: 15, right: 18, bottom: 0, left: 0 }}
          >
            <CartesianGrid stroke="#f1f1f5" vertical={false} />
            <XAxis
              dataKey="hour"
              tickFormatter={(h) => `${String(h).padStart(2, "0")}시`}
              interval={3}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#767676", fontSize: 12 }}
              dy={8}
            />
            <YAxis
              width={44}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "#767676", fontSize: 12 }}
            />
            <Tooltip
              labelFormatter={(h) => `${h}:00–${Number(h) + 1}:00 KST`}
              contentStyle={{
                borderRadius: 10,
                border: "1px solid #e5e5ec",
                fontSize: 13,
              }}
            />
            <Area
              type="linear"
              dataKey="surplus_mwh"
              name="잉여전력 (MWh)"
              fill="#ffe08a"
              stroke="none"
              isAnimationActive={false}
            />
            <Line
              type="linear"
              dataKey="generation_mwh"
              name="예상 발전량 (MWh)"
              stroke="#009e42"
              strokeWidth={2.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="linear"
              dataKey="demand_mwh"
              name="예상 수요 (MWh)"
              stroke="#505050"
              strokeWidth={2}
              strokeDasharray="5 5"
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="risk-strip" aria-label="24시간 위험도">
        {result.hourly.map((row) => (
          <span
            key={row.hour}
            className={`risk-cell risk-cell--${row.risk.toLowerCase()}`}
            title={`${row.hour}시 ${row.risk} · 잉여 ${row.surplus_mwh} MWh`}
          />
        ))}
      </div>
      <div className="risk-caption">
        <span>00시</span>
        <span>시간대별 위험도 · 상세 수치는 아래 표에서 확인</span>
        <span>23시</span>
      </div>
      <details className="data-details">
        <summary>시간별 수치 표 보기</summary>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">시간별 예측 수치</caption>
            <thead>
              <tr>
                <th>시간</th>
                <th>발전량</th>
                <th>수요</th>
                <th>잉여전력</th>
                <th>위험도</th>
              </tr>
            </thead>
            <tbody>
              {result.hourly.map((row) => (
                <tr key={row.hour}>
                  <td>{row.hour}:00</td>
                  <td>{row.generation_mwh.toFixed(1)}</td>
                  <td>{row.demand_mwh.toFixed(1)}</td>
                  <td>{row.surplus_mwh.toFixed(1)}</td>
                  <td>{row.risk}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}
