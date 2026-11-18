import { useEffect, useState } from "react";
import type { AnalysisRun, Transport } from "../features/analysis/types";
import { labels, phaseLabel } from "../features/analysis/state";
import { DateField } from "../components/DateField";
import {
  FlowChart,
  fmt,
  longDate,
  pad,
  resourceNames,
  sourceNames,
  surplusSpan,
} from "../features/analysis/FlowChart";

type Tab = "before" | "after";

function BeforeView({
  date,
  onDateChange,
  onSubmit,
  disabled,
  error,
  onPreview,
}: {
  date: string;
  onDateChange: (date: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  error: string;
  onPreview: () => void;
}) {
  return (
    <section className="dv-section" aria-labelledby="dv-before-title">
      <p className="dv-eyebrow">출력제한 대응 분석</p>
      <h1 id="dv-before-title" className="dv-hero">
        내일의 전력.
        <br />
        오늘의 준비.
      </h1>
      <p className="dv-lead">
        제주의 발전량과 수요를 살펴보고,
        <br />
        남는 전력의 활용 방안을 확인하세요.
      </p>
      <form
        className="dv-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <div className="dv-fields">
          <div className="dv-field">
            <label htmlFor="dv-date">분석 대상일</label>
            <DateField
              id="dv-date"
              value={date}
              onChange={onDateChange}
              disabled={disabled}
            />
          </div>
          <div className="dv-field">
            <span className="dv-label">분석 지역</span>
            <strong className="dv-static">제주 전역</strong>
          </div>
        </div>
        {error && (
          <p role="alert" className="field-error">
            {error}
          </p>
        )}
        <div className="dv-actions">
          <button type="submit" className="dv-pill" disabled={disabled}>
            {disabled ? "분석 진행 중" : "분석 시작"}
          </button>
          <button type="button" className="dv-link" onClick={onPreview}>
            예시 결과 살펴보기 ›
          </button>
        </div>
      </form>
      <ol className="dv-steps">
        {[
          ["발전량과 수요", "시간대별 전력 흐름을 예측합니다."],
          ["자원 배분", "잉여전력의 활용 방안을 제안합니다."],
          [
            "통보문 확인",
            "AI가 만든 통보문을 담당자가 확인하고 발송을 정합니다.",
          ],
        ].map(([title, desc], i) => (
          <li key={title}>
            <span className="dv-step-num">{pad(i + 1)}</span>
            <strong>{title}</strong>
            <p>{desc}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function AfterView({
  run,
  transport,
  onStart,
  onReview,
  onForecast,
}: {
  run: AnalysisRun | null;
  transport: Transport;
  onStart: () => void;
  onReview: () => void;
  onForecast: () => void;
}) {
  const result = run?.result ?? null;
  if (!run || !result) {
    return (
      <section className="dv-section dv-empty" aria-live="polite">
        <p className="dv-eyebrow">
          {run ? labels[run.status] : "분석 결과 없음"}
        </p>
        <h1 className="dv-hero dv-hero--sm">
          {run && !["failed", "interrupted"].includes(run.status)
            ? "결과를 계산하고 있습니다."
            : "아직 확인한 분석이 없습니다."}
        </h1>
        <p className="dv-lead">
          {run
            ? "서버에서 계산이 끝나면 이 화면에 결과가 표시됩니다."
            : "분석 전 탭에서 대상일을 고르고 분석을 시작하세요."}
        </p>
        {(!run || ["failed", "interrupted"].includes(run.status)) && (
          <div className="dv-actions">
            <button type="button" className="dv-pill" onClick={onStart}>
              분석하러 가기
            </button>
          </div>
        )}
      </section>
    );
  }

  const allocation = run.allocation;
  const span = surplusSpan(result.hourly);
  const peak = `${pad(result.peak_hour)}:00–${pad((result.peak_hour + 1) % 24)}:00`;
  const rows = allocation
    ? (Object.keys(resourceNames) as (keyof typeof resourceNames)[]).filter(
        (key) => allocation.allocated_mwh[key] > 0,
      )
    : [];
  const stale = transport !== "confirmed";

  return (
    <>
      <section className="dv-section" aria-labelledby="dv-after-title">
        <p className="dv-meta">
          <span>{longDate(run.request.date)} · 제주 전역</span>
          <span>{run.simulation ? "시연 분석" : "외부 데이터 · 검증 전"}</span>
          <span>{labels[run.status]}</span>
          <span>
            {phaseLabel(run.phase ?? run.request.phase, run.check_no)}
          </span>
        </p>
        <h1 id="dv-after-title" className="dv-hero">
          {span ? "예측된 잉여전력." : "예측된 전력 흐름."}
          <br />
          {span ? "대응은 오늘." : "여유는 충분합니다."}
        </h1>
        <p className="dv-lead">
          {span
            ? `${span[0]}시부터 ${span[1]}시까지 잉여전력이 예상됩니다.`
            : "발전량이 대응 기준을 넘는 시간이 예상되지 않습니다."}
          <br />
          {allocation
            ? `자원 배분으로 피크 1시간 잉여량의 ${fmt(allocation.absorption_pct)}%를 흡수할 수 있습니다.`
            : "위험 기준 미만이라 자원 배분이 필요하지 않습니다."}
        </p>
        <p className="dv-caption">
          잉여전력은 수요의 {(result.thresholds.warning_ratio * 100).toFixed(0)}
          %를 초과하는 발전량입니다.
          {result.from_hour != null
            ? ` ${result.from_hour}시 이후 구간을 판정했습니다.`
            : ""}
        </p>
        {stale && (
          <p className="notice notice--warning">
            최신 서버 상태를 다시 확인하는 중입니다. 표시된 값은 마지막으로
            확인한 결과입니다.
          </p>
        )}
        <div className="dv-actions">
          {allocation && (
            <button type="button" className="dv-pill" onClick={onReview}>
              배분안 검토
            </button>
          )}
          <button type="button" className="dv-link" onClick={onForecast}>
            시간별 예측 보기 ›
          </button>
        </div>
        <dl className="dv-kpis">
          <div>
            <dt>피크 시간 잉여전력 · {peak}</dt>
            <dd>
              {fmt(result.peak_surplus_mwh)}
              <small>MWh</small>
            </dd>
          </div>
          <div>
            <dt>흡수 가능 비율</dt>
            <dd>
              {allocation ? fmt(allocation.absorption_pct) : "—"}
              <small>%</small>
            </dd>
          </div>
          <div>
            <dt>배분 후 잔여량</dt>
            <dd>
              {allocation ? fmt(allocation.residual_mwh) : "—"}
              <small>MWh</small>
            </dd>
          </div>
        </dl>
      </section>

      <section className="dv-band" aria-labelledby="dv-flow-title">
        <div className="dv-band-head">
          <h2 id="dv-flow-title">하루의 전력 흐름</h2>
          <div className="dv-legend" aria-hidden="true">
            <span className="dv-legend-gen">발전량</span>
            <span className="dv-legend-dem">수요 · 점선</span>
          </div>
        </div>
        <FlowChart
          hourly={result.hourly}
          warningRatio={result.thresholds.warning_ratio}
        />
        <p className="dv-caption">
          {run.simulation
            ? "시연 데이터 기준 · 실제 예측값이 아닙니다."
            : "외부 데이터 기준 · 운영 검증 전 값입니다."}
        </p>
      </section>

      {allocation && (
        <section
          className="dv-section dv-alloc"
          aria-labelledby="dv-alloc-title"
        >
          <div>
            <h2 id="dv-alloc-title">
              {fmt(allocation.absorbed_mwh)} MWh를
              <br />
              어디에 배분할까요.
            </h2>
            <p>
              피크 1시간 기준 대응 후보 제안입니다.
              <br />
              적용 전 운영 조건을 확인하세요.
            </p>
          </div>
          <ul>
            {rows.map((key) => (
              <li key={key}>
                <div>
                  <strong>{resourceNames[key]}</strong>
                  <span>{peak}</span>
                </div>
                <p>
                  {fmt(allocation.allocated_mwh[key])}
                  <small>MWh</small>
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      <details className="dv-details">
        <summary>배분 조건과 데이터 출처 확인</summary>
        <p>
          {allocation
            ? `가용량을 ESS ${fmt(allocation.capacities_mwh.bess)}, VPP ${fmt(allocation.capacities_mwh.vpp)}, 수전해 ${fmt(allocation.capacities_mwh.p2x)}, 전기차 ${fmt(allocation.capacities_mwh.ev)} MWh로 가정했습니다(${allocation.availability_verified ? "현장 확인됨" : "시연 추정치"}). 수소 환산 ${fmt(allocation.hydrogen_kg)} kg. `
            : ""}
          데이터 출처:{" "}
          {Object.entries(run.sources)
            .map(
              ([key, value]) =>
                `${sourceNames[key] || key} ${String(value.source || "미확인")}`,
            )
            .join(", ") || "확인 전"}
          . 설비 제어는 연결되어 있지 않습니다.
        </p>
      </details>
    </>
  );
}

export function DashboardPage({
  run,
  transport,
  date,
  onDateChange,
  onSubmit,
  submitDisabled,
  formError,
  onGoReview,
  onOpenForecast,
}: {
  run: AnalysisRun | null;
  transport: Transport;
  date: string;
  onDateChange: (date: string) => void;
  onSubmit: () => void;
  submitDisabled: boolean;
  formError: string;
  onGoReview: () => void;
  onOpenForecast: () => void;
}) {
  const [tab, setTab] = useState<Tab>(run?.result ? "after" : "before");
  const runId = run?.id;
  // A newly submitted or selected analysis moves the view to its result.
  useEffect(() => {
    if (runId) setTab("after");
  }, [runId]);

  return (
    <div className="dv">
      <div className="dv-tabs" role="tablist" aria-label="대시보드 보기">
        {(
          [
            ["before", "분석 전"],
            ["after", "분석 후"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            id={`dv-tab-${id}`}
            aria-selected={tab === id}
            aria-controls={`dv-panel-${id}`}
            className="dv-tab"
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`dv-panel-${tab}`}
        aria-labelledby={`dv-tab-${tab}`}
      >
        {tab === "before" ? (
          <BeforeView
            date={date}
            onDateChange={onDateChange}
            onSubmit={onSubmit}
            disabled={submitDisabled}
            error={formError}
            onPreview={() => setTab("after")}
          />
        ) : (
          <AfterView
            run={run}
            transport={transport}
            onStart={() => setTab("before")}
            onReview={onGoReview}
            onForecast={onOpenForecast}
          />
        )}
      </div>
    </div>
  );
}
