import { lazy, Suspense } from "react";
import {
  CircleCheck,
  Clock3,
  CloudSun,
  Info,
  Plug,
  ShieldCheck,
  TriangleAlert,
  Zap,
} from "lucide-react";
import type {
  AnalysisRun,
  AnalysisSummary,
  Transport,
} from "../features/analysis/types";
import { labels } from "../features/analysis/state";
import { regions } from "../features/analysis/AnalysisForm";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";

const GenerationChart = lazy(() =>
  import("../features/analysis/GenerationChart").then((m) => ({
    default: m.GenerationChart,
  })),
);

const riskLabel = { NORMAL: "정상 범위", CAUTION: "경계", CRITICAL: "위험" };
const sourceNames: Record<string, string> = {
  weather: "기상",
  generation: "발전량",
  demand: "수요",
};
const sourceIcons: Record<string, typeof Zap> = {
  weather: CloudSun,
  generation: Zap,
  demand: Plug,
};
const pad = (h: number) => String(h).padStart(2, "0");

type StepState = "done" | "waiting" | "idle";
function steps(run: AnalysisRun | null): {
  title: string;
  desc: string;
  state: StepState;
}[] {
  const status = run?.status;
  const review: [string, StepState] =
    status === "awaiting_approval"
      ? ["담당자 결정 대기", "waiting"]
      : status === "approved"
        ? ["시연 승인 기록됨", "done"]
        : status === "rejected"
          ? ["반려 기록됨", "done"]
          : status === "decision_pending"
            ? ["결정 처리 확인 필요", "waiting"]
            : ["이전 단계 완료 후 진행", "idle"];
  return [
    {
      title: "① 발전량 예측",
      desc: run?.result ? "완료" : run ? labels[run.status] : "분석 요청 전",
      state: run?.result ? "done" : "idle",
    },
    {
      title: "② 자원 배분 권고",
      desc: run?.allocation
        ? `완료 · 흡수 ${run.allocation.absorption_pct.toFixed(1)}%`
        : "예측 완료 후 계산",
      state: run?.allocation ? "done" : "idle",
    },
    { title: "③ 검토·승인", desc: review[0], state: review[1] },
  ];
}

export function DashboardPage({
  run,
  transport,
  items,
  historyLoading,
  historyError,
  onNewAnalysis,
  onOpenHistory,
  onGoReview,
  onSelect,
}: {
  run: AnalysisRun | null;
  transport: Transport;
  items: AnalysisSummary[];
  historyLoading: boolean;
  historyError: string;
  onNewAnalysis: () => void;
  onOpenHistory: () => void;
  onGoReview: () => void;
  onSelect: (item: AnalysisSummary) => void;
}) {
  const result = run?.result ?? null;
  const allocation = run?.allocation ?? null;
  const confirmed = transport === "confirmed";
  const pendingCount = items.filter(
    (item) => item.status === "awaiting_approval",
  ).length;
  const peak = result
    ? `${pad(result.peak_hour)}:00–${pad((result.peak_hour + 1) % 24)}:00`
    : null;
  const flow = steps(run);

  return (
    <div className="dashboard">
      <header className="dash-header">
        <div>
          <h1>출력제한 대응 현황</h1>
          <p>
            {run
              ? `${run.request.date} · ${regions[run.request.region]} · ${run.simulation ? "시연 데이터" : "외부 데이터 · 운영 검증 전"} · 최근 확인한 분석 기준`
              : "아직 확인한 분석이 없습니다. 분석을 요청하면 이곳에 요약됩니다."}
          </p>
        </div>
        <div className="dash-actions">
          <Button variant="secondary" onClick={onOpenHistory}>
            분석 이력 보기
          </Button>
          <Button onClick={onNewAnalysis}>새 분석 요청</Button>
        </div>
      </header>

      {result && confirmed && result.risk !== "NORMAL" && (
        <section
          className={`dash-alert dash-alert--${result.risk.toLowerCase()}`}
          aria-label="검토 알림"
        >
          <TriangleAlert size={24} aria-hidden="true" />
          <div>
            <strong>
              {result.date} {peak} 잉여전력 {result.peak_surplus_mwh.toFixed(1)}{" "}
              MWh 예상 · {riskLabel[result.risk]}
            </strong>
            <p>
              {run?.status === "awaiting_approval"
                ? "배분 권고안이 준비되었습니다. 담당자 검토와 시연 승인이 필요합니다."
                : run
                  ? `현재 상태: ${labels[run.status]}`
                  : ""}
            </p>
          </div>
          {run?.status === "awaiting_approval" && (
            <Button className="button--dark" onClick={onGoReview}>
              검토하러 가기
            </Button>
          )}
        </section>
      )}

      <section className="dash-kpis" aria-label="핵심 지표">
        <article className="dash-card dash-kpi">
          <span className="dash-kpi-label">
            <Zap size={18} aria-hidden="true" />
            피크 잉여전력
          </span>
          <p className="dash-kpi-value">
            {result ? result.peak_surplus_mwh.toFixed(1) : "—"}
            <small>MWh</small>
          </p>
          <span
            className={`risk-badge risk-badge--${result?.risk.toLowerCase() || "empty"}`}
          >
            {result ? riskLabel[result.risk] : "분석 결과 없음"}
          </span>
        </article>
        <article className="dash-card dash-kpi">
          <span className="dash-kpi-label">
            <Clock3 size={18} aria-hidden="true" />
            피크 시간
          </span>
          <p className="dash-kpi-value">{peak ?? "—"}</p>
          <span className="risk-badge">1시간 구간 · KST</span>
        </article>
        <article className="dash-card dash-kpi">
          <span className="dash-kpi-label">
            <Plug size={18} aria-hidden="true" />
            흡수 권고 비율
          </span>
          <p className="dash-kpi-value">
            {allocation ? allocation.absorption_pct.toFixed(1) : "—"}
            <small>%</small>
          </p>
          <span className="risk-badge">
            {allocation
              ? `잔여 ${allocation.residual_mwh.toFixed(1)} MWh`
              : "배분 결과 없음"}
          </span>
        </article>
        <article className="dash-card dash-kpi">
          <span className="dash-kpi-label">
            <ShieldCheck size={18} aria-hidden="true" />
            결정 대기
          </span>
          <p className="dash-kpi-value">
            {historyLoading && !items.length ? "—" : pendingCount}
            <small>건</small>
          </p>
          <span className="risk-badge risk-badge--info">
            최근 30건 이력 기준
          </span>
        </article>
      </section>

      <div className="dash-row">
        <section className="dash-card dash-chart" aria-labelledby="dash-chart">
          <h2 id="dash-chart">시간별 발전량과 수요</h2>
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
              title="표시할 예측이 없습니다"
              description="분석을 요청하면 다음날 시간별 발전량과 수요를 비교해 보여줍니다."
            />
          )}
        </section>

        <aside className="dash-card dash-side" aria-labelledby="dash-steps">
          <div className="dash-card-head">
            <h2 id="dash-steps">진행 단계</h2>
            {run && (
              <span className="small-chip mono">ID {run.id.slice(0, 8)}</span>
            )}
          </div>
          <ol className="dash-steps">
            {flow.map((step) => (
              <li
                key={step.title}
                className={`dash-step dash-step--${step.state}`}
              >
                {step.state === "done" ? (
                  <CircleCheck size={22} aria-hidden="true" />
                ) : (
                  <Clock3 size={22} aria-hidden="true" />
                )}
                <div>
                  <strong>{step.title}</strong>
                  <span>{step.desc}</span>
                </div>
                {step.state === "waiting" && (
                  <span className="risk-badge risk-badge--caution">대기</span>
                )}
              </li>
            ))}
          </ol>
          <Button
            className="dash-wide"
            onClick={run ? onGoReview : onNewAnalysis}
          >
            {run ? "검토·승인으로 이동" : "새 분석 요청"}
          </Button>
          <p className="dash-note">
            <Info size={16} aria-hidden="true" />
            승인해도 실제 설비에는 명령을 보내지 않습니다(시연).
          </p>
        </aside>
      </div>

      <div className="dash-row">
        <section className="dash-card" aria-labelledby="dash-history">
          <div className="dash-card-head">
            <h2 id="dash-history">최근 분석 이력</h2>
            <Button
              variant="secondary"
              className="button--sm"
              onClick={onOpenHistory}
            >
              전체 보기
            </Button>
          </div>
          {historyError && (
            <p className="notice notice--warning" role="alert">
              {historyError}
            </p>
          )}
          {historyLoading && !items.length ? (
            <p role="status" className="muted">
              이력을 확인하고 있습니다.
            </p>
          ) : items.length ? (
            <div className="table-scroll">
              <table className="dash-table">
                <thead>
                  <tr>
                    <th>대상일</th>
                    <th>지역</th>
                    <th>데이터</th>
                    <th>상태</th>
                    <th>ID</th>
                    <th>
                      <span className="sr-only">결과</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.slice(0, 5).map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.request.date}</strong>
                      </td>
                      <td>{regions[item.request.region]}</td>
                      <td>{item.simulation ? "시연" : "외부 · 검증 전"}</td>
                      <td
                        className={
                          item.status === "awaiting_approval"
                            ? "dash-status--pending"
                            : undefined
                        }
                      >
                        {labels[item.status]}
                      </td>
                      <td className="mono">{item.id.slice(0, 8)}</td>
                      <td>
                        <Button
                          variant="ghost"
                          className="button--sm"
                          onClick={() => onSelect(item)}
                          aria-label={`${item.request.date} ${item.id.slice(0, 8)} 결과 열기`}
                        >
                          열기
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            !historyError && (
              <EmptyState
                title="저장된 분석이 없습니다"
                description="분석을 요청하면 최근 기록이 이곳에 표시됩니다."
              />
            )
          )}
        </section>

        <aside className="dash-card dash-side" aria-labelledby="dash-sources">
          <div className="dash-card-head">
            <h2 id="dash-sources">데이터 출처</h2>
            {run && (
              <span className="small-chip">
                {run.simulation ? "시연 데이터" : "외부 · 검증 전"}
              </span>
            )}
          </div>
          {run?.sources && Object.keys(run.sources).length ? (
            <ul className="dash-sources">
              {Object.entries(run.sources).map(([key, value]) => {
                const Icon = sourceIcons[key] || Info;
                return (
                  <li key={key}>
                    <Icon size={20} aria-hidden="true" />
                    <div>
                      <strong>{sourceNames[key] || key}</strong>
                      <span>
                        {String(value.source || "미확인")} ·{" "}
                        {value.simulated
                          ? "시연/대체 데이터"
                          : "외부 조회 또는 추정"}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="muted dash-empty-text">
              분석 결과가 확인되면 사용한 기상·발전량·수요 데이터 출처를
              표시합니다.
            </p>
          )}
          {run?.trace?.length ? (
            <p className="caption">실행 기록: {run.trace.join(" → ")}</p>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
