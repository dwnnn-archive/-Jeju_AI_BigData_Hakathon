import type { AnalysisRun } from "./types";
import { modes, regions, scenarios } from "./AnalysisForm";

/** 분석 지역·시연 조건·분석 단계: 발전량 예측·자원 배분·검토 화면이 같은 표현을 쓴다. */
export function conditionFacts(run: AnalysisRun | null) {
  return [
    {
      label: "분석 지역",
      value: run ? regions[run.request.region] : "-",
    },
    {
      label: run?.request.mode === "live" ? "데이터 조건" : "시연 조건",
      value: !run
        ? "-"
        : run.request.mode === "demo"
          ? `${modes.demo} · ${scenarios[run.request.scenario]}`
          : modes.live,
    },
    {
      label: "분석 단계",
      value: !run
        ? "-"
        : run.request.phase === "intraday"
          ? "당일 점검"
          : "하루 전 계획",
    },
  ];
}

/** 발전량 예측·자원 배분 화면 상단의 분석 조건 카드 줄. */
export function RunConditions({ run }: { run: AnalysisRun }) {
  return (
    <dl className="run-conditions" aria-label="분석 조건">
      <div>
        <dt>대상일</dt>
        <dd>{run.request.date}</dd>
      </div>
      {conditionFacts(run).map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
