import type { AnalysisRun } from "../features/analysis/types";
import { labels, phaseLabel } from "../features/analysis/state";
import {
  FlowChart,
  RiskStrip,
  fmt,
  pad,
  surplusSpan,
} from "../features/analysis/FlowChart";

const riskLabel = { NORMAL: "정상 범위", CAUTION: "경계", CRITICAL: "위험" };

export function ForecastPage({
  run,
  onNext,
}: {
  run: AnalysisRun | null;
  onNext?: () => void;
}) {
  const result = run?.result;
  if (!result) {
    return (
      <section className="ed-empty" aria-live="polite">
        <h2>
          {run?.status === "failed"
            ? "분석이 완료되지 않았습니다."
            : run
              ? `${labels[run.status]}입니다.`
              : "아직 확인한 예측이 없습니다."}
        </h2>
        <p>
          {run?.status === "failed"
            ? "필수 데이터 또는 서버 설정을 확인하세요. 확인되지 않은 결과는 표시하지 않습니다."
            : "위 조건으로 분석을 요청하면 시간별 발전량과 수요가 이곳에 표시됩니다."}
        </p>
      </section>
    );
  }
  const span = surplusSpan(result.hourly);
  const peak = `${pad(result.peak_hour)}:00–${pad((result.peak_hour + 1) % 24)}:00`;
  return (
    <>
      <p className="dv-caption">
        {phaseLabel(run.phase ?? run.request.phase, run.check_no)}
        {result.from_hour != null ? ` · ${result.from_hour}시 이후 판정` : ""}
        {` · 발전량/수요 최대 비율 ${(result.peak_ratio * 100).toFixed(0)}% (경계 ${(result.thresholds.warning_ratio * 100).toFixed(0)}% · 위험 ${(result.thresholds.critical_ratio * 100).toFixed(0)}%)`}
        <br />
        잉여전력은 수요의 {(result.thresholds.warning_ratio * 100).toFixed(0)}
        %를 초과하는 발전량입니다.
      </p>
      <dl className="dv-kpis ed-kpis">
        <div>
          <dt>피크 잉여전력 · {riskLabel[result.risk]}</dt>
          <dd>
            {fmt(result.peak_surplus_mwh)}
            <small>MWh</small>
          </dd>
        </div>
        <div>
          <dt>피크 시간 · KST</dt>
          <dd className="ed-kpi-time">{peak}</dd>
        </div>
        <div>
          <dt>잉여 발생 구간</dt>
          <dd className="ed-kpi-time">
            {span ? `${span[0]}–${span[1]}시` : "없음"}
          </dd>
        </div>
        <div>
          <dt>경계값 재조회</dt>
          <dd>
            {run.refresh_count || 0}
            <small>회</small>
          </dd>
        </div>
      </dl>

      <section className="dv-band" aria-labelledby="ed-flow-title">
        <div className="dv-band-head">
          <h2 id="ed-flow-title">하루의 전력 흐름</h2>
          <div className="dv-legend" aria-hidden="true">
            <span className="dv-legend-gen">발전량</span>
            <span className="dv-legend-dem">수요 · 점선</span>
          </div>
        </div>
        <FlowChart
          hourly={result.hourly}
          warningRatio={result.thresholds.warning_ratio}
        />
        <h3 className="ed-subhead">24시간 위험 띠</h3>
        <RiskStrip hourly={result.hourly} />
        <p className="dv-caption">
          {run.simulation
            ? "시연 데이터 기준 · 실제 예측값이 아닙니다. 예측값은 현장 운영 검증과 실제 조치 승인을 대신하지 않습니다."
            : "외부 데이터 기준 · 운영 검증 전 값입니다."}
        </p>
      </section>

      <details className="dv-details">
        <summary>시간별 수치 보기</summary>
        <div className="table-scroll">
          <table className="ed-table">
            <thead>
              <tr>
                <th>시간</th>
                <th>발전량</th>
                <th>수요</th>
                <th>잉여</th>
                <th>위험도</th>
              </tr>
            </thead>
            <tbody>
              {[...result.hourly]
                .sort((a, b) => a.hour - b.hour)
                .map((r) => (
                  <tr key={r.hour}>
                    <td>{pad(r.hour)}:00</td>
                    <td>{fmt(r.generation_mwh)}</td>
                    <td>{fmt(r.demand_mwh)}</td>
                    <td>{fmt(r.surplus_mwh)}</td>
                    <td>{riskLabel[r.risk]}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>

      {onNext && run.allocation && (
        <nav className="ed-stepnav" aria-label="단계 이동">
          <button type="button" className="ed-stepnav-next" onClick={onNext}>
            다음 단계
            <strong>
              자원 배분 <span aria-hidden="true">›</span>
            </strong>
          </button>
        </nav>
      )}
    </>
  );
}
