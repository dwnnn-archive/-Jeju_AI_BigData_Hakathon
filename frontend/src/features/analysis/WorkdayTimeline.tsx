import type { AnalysisRun } from "./types";
import { workdaySteps } from "./state";

const stateLabel = {
  done: "완료",
  current: "지금 여기",
  todo: "예정",
} as const;

/** 담당자의 하루 업무 흐름. 현재 화면의 분석이 어느 단계인지 표시한다. */
export function WorkdayTimeline({ run }: { run: AnalysisRun | null }) {
  const steps = workdaySteps(run);
  return (
    <ol className="workday" aria-label="담당자 하루 업무 흐름">
      {steps.map((step, index) => (
        <li
          key={step.key}
          className={`workday-step workday-step--${step.state}`}
        >
          <span className="workday-time">{step.time}</span>
          <strong>
            {index + 1}. {step.title}
          </strong>
          <small>{step.detail}</small>
          <span className="workday-state">{stateLabel[step.state]}</span>
        </li>
      ))}
    </ol>
  );
}
