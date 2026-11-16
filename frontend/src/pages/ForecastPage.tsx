import { lazy, Suspense } from "react";
import { ArrowUpRight, Clock3, Info } from "lucide-react";
import type { AnalysisRun } from "../features/analysis/types";
import { EmptyState } from "../components/EmptyState";
import { AllocationPanel } from "../features/allocation/AllocationPanel";

const GenerationChart = lazy(() =>
  import("../features/analysis/GenerationChart").then((m) => ({
    default: m.GenerationChart,
  })),
);
export function ForecastPage({ run }: { run: AnalysisRun | null }) {
  const result = run?.result;
  return (
    <>
      <div className="forecast-grid">
        <section className="panel chart-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">DAY-AHEAD OUTLOOK</span>
              <h2>시간별 발전량과 수요</h2>
            </div>
            <span className="small-chip">KST · 24시간</span>
          </div>
          {result ? (
            <Suspense
              fallback={
                <div className="chart-loading" role="status">
                  차트 표시 준비 중
                </div>
              }
            >
              <GenerationChart result={result} />
            </Suspense>
          ) : (
            <EmptyState
              title={
                run?.status === "failed"
                  ? "분석이 완료되지 않았습니다"
                  : undefined
              }
              description={
                run?.status === "failed"
                  ? "필수 데이터 또는 서버 설정을 확인하세요. 확인되지 않은 결과는 표시하지 않습니다."
                  : undefined
              }
            />
          )}
        </section>
        <aside className="panel summary-panel">
          <div className="section-heading">
            <div>
              <span className="eyebrow">REVIEW BRIEF</span>
              <h2>검토 요약</h2>
            </div>
            <ArrowUpRight size={20} />
          </div>
          <p className="summary-label">피크 잉여전력 (수요의 40% 초과분)</p>
          <div className="big-number">
            {result ? result.peak_surplus_mwh.toFixed(1) : "—"}
            <span>MWh</span>
          </div>
          <span
            className={`risk-badge risk-badge--${result?.risk.toLowerCase() || "empty"}`}
          >
            {result
              ? { NORMAL: "정상 범위", CAUTION: "경계", CRITICAL: "위험" }[
                  result.risk
                ]
              : "분석 결과 없음"}
          </span>
          <dl className="summary-list">
            <div>
              <dt>발전량/수요 최대 비율</dt>
              <dd>
                {result
                  ? `${(result.peak_ratio * 100).toFixed(0)}% (경계 ${(result.thresholds.warning_ratio * 100).toFixed(0)}% · 위험 ${(result.thresholds.critical_ratio * 100).toFixed(0)}%)`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>
                <Clock3 size={15} />
                피크 시간
              </dt>
              <dd>
                {result
                  ? `${String(result.peak_hour).padStart(2, "0")}:00–${String(result.peak_hour + 1).padStart(2, "0")}:00`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>흡수 권고 비율</dt>
              <dd>
                {run?.allocation
                  ? run.allocation.absorption_pct.toFixed(1) + "%"
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>재조회 횟수</dt>
              <dd>{run?.result ? `${run.refresh_count || 0}회` : "—"}</dd>
            </div>
          </dl>
          <div className="summary-note">
            <Info size={17} />
            <p>
              예측값은 검토를 위한 참고 정보입니다. 현장 운영 검증과 실제 조치
              승인을 대신하지 않습니다.
            </p>
          </div>
        </aside>
      </div>
      <section className="panel">
        <div className="section-heading">
          <div>
            <span className="eyebrow">RESOURCE ALLOCATION</span>
            <h2>분산자원 배분 권고</h2>
          </div>
          <span className="small-chip">피크 1시간 기준</span>
        </div>
        <AllocationPanel run={run} />
      </section>
    </>
  );
}
