import type { AnalysisRun, Transport } from "./types";

export const labels: Record<AnalysisRun["status"], string> = {
  queued: "실행 대기 중",
  running: "분석 중",
  status_unknown: "상태 확인 불가",
  interrupted: "실행 중단 확인",
  awaiting_approval: "계산 완료 · 검토 필요",
  completed: "계산 완료",
  approved: "발송 확정됨",
  rejected: "발송 보류됨",
  failed: "분석 실패",
  decision_pending: "결정 처리 확인 필요",
};
export function phaseLabel(phase?: string, checkNo?: number) {
  return phase === "intraday"
    ? `당일 ${checkNo ? `${checkNo}차 ` : ""}점검`
    : "하루 전 계획";
}
export function statusLabel(transport: Transport, run: AnalysisRun | null) {
  if (transport === "sending") return "요청 전송 중";
  if (transport === "unknown") return "상태 확인 불가";
  if (transport === "checking") return "서버 상태 확인 중";
  return run ? labels[run.status] : "분석 요청 전";
}
export function acceptSnapshot(
  current: AnalysisRun | null,
  candidate: AnalysisRun,
  id: string,
) {
  if (candidate.id !== id) throw new Error("분석 ID가 일치하지 않습니다.");
  if (
    current?.id === id &&
    (current.version > candidate.version ||
      (current.version === candidate.version &&
        Date.parse(current.server_checked_at) >
          Date.parse(candidate.server_checked_at)))
  )
    return current;
  return candidate;
}
export function canReview(
  run: AnalysisRun | null,
  transport: Transport,
  matches: boolean,
) {
  return Boolean(
    run &&
    transport === "confirmed" &&
    matches &&
    run.can_decide &&
    run.status === "awaiting_approval" &&
    run.result_token &&
    run.expires_at &&
    Date.parse(run.expires_at) > Date.now(),
  );
}
export const blockLabels: Record<string, string> = {
  not_awaiting_approval: "현재 상태에서는 새 결정을 할 수 없습니다.",
  superseded: "같은 조건의 더 최근 분석이 있습니다.",
  result_expired: "검토 유효시간이 지났습니다.",
  operational_validation_missing:
    "모델·자원 가용량의 운영 검증이 완료되지 않았습니다.",
  boundary_unresolved: "재조회 후에도 경계값이 해소되지 않았습니다.",
  result_unavailable: "확인된 결과가 아직 없습니다.",
  legacy_result: "이전 버전 결과는 조회만 가능합니다.",
};

/** 한국 표준시 기준 오늘(YYYY-MM-DD). */
export type DateLimits = { min?: string; max?: string };
function addDaysIso(isoDate: string, days: number) {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}
/** 외부 데이터의 하루 전 분석은 내일~모레만. 시연 데이터는 제한이 없다. */
export function dateLimits(
  mode: "demo" | "live",
  now = Date.now(),
): DateLimits {
  if (mode !== "live") return {};
  const today = todayKst(now);
  return { min: addDaysIso(today, 1), max: addDaysIso(today, 2) };
}
export function clampDate(date: string, limits: DateLimits) {
  if (limits.min && date < limits.min) return limits.min;
  if (limits.max && date > limits.max) return limits.max;
  return date;
}

export function todayKst(now = Date.now()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/**
 * 당일 점검을 요청할 수 있는 화면 상태인가.
 * 서버 규칙(오늘 날짜, 직전 결과 정상, 횟수 제한)의 앞단 확인일 뿐이며 최종 판단은 서버가 한다.
 */
export function canIntradayCheck(
  run: AnalysisRun | null,
  transport: Transport,
  today = todayKst(),
) {
  return Boolean(
    run &&
    transport === "confirmed" &&
    run.status === "completed" &&
    run.result?.risk === "NORMAL" &&
    run.request.date === today,
  );
}

export type WorkdayStep = {
  key: string;
  time: string;
  title: string;
  detail: string;
  state: "done" | "current" | "todo";
};

/** 하루 업무 흐름. 현재 화면의 분석이 어느 단계인지만 표시한다(없는 일을 한 것으로 쓰지 않는다). */
export function workdaySteps(run: AnalysisRun | null): WorkdayStep[] {
  const phase = run?.phase ?? run?.request.phase;
  const check = run?.check_no ?? 0;
  const risky =
    run?.result?.risk === "CAUTION" || run?.result?.risk === "CRITICAL";
  const decided = run?.status === "approved" || run?.status === "rejected";
  const awaiting = run?.status === "awaiting_approval";
  const finished = Boolean(run && run.status !== "queued");
  const at = (n: number) => (phase === "intraday" ? check >= n : false);
  const dayAheadDone = finished && (phase !== "intraday" || check >= 1);
  const steps: Omit<WorkdayStep, "state">[] = [
    {
      key: "day_ahead",
      time: "전날 17:30",
      title: "하루 전 분석",
      detail: "내일 24시간 발전량·수요 예측, 위험 판정(자동 실행)",
    },
    {
      key: "check1",
      time: "당일 07:45",
      title: "당일 1차 점검",
      detail: "하루 전이 정상일 때만. 초단기예보로 다시 판정",
    },
    {
      key: "check2",
      time: "당일 10:45",
      title: "당일 2차 점검",
      detail: "여전히 정상이면 한 번 더. 하루 최대 2회",
    },
    {
      key: "review",
      time: "위험 판정 즉시",
      title: "담당자 통보문 확인",
      detail: "대응 후보 제안과 통보문 초안 확인 후 발송 확정 또는 보류",
    },
    {
      key: "notify",
      time: "승인 직후",
      title: "관계기관 통보",
      detail: "승인된 초안으로 통보(실제 발송은 운영 검증 후)",
    },
    {
      key: "peak",
      time: "09:00–15:00",
      title: "출력제한 피크 시간대",
      detail: "KPX가 출력제한 여부를 판단·지시(서비스 범위 밖)",
    },
  ];
  const done = [dayAheadDone, at(1), at(2), risky && decided, false, false];
  let current = -1;
  if (!run) current = 0;
  else if (risky && awaiting) current = 3;
  else if (risky && decided) current = 4;
  else if (phase === "intraday") current = check >= 2 ? 5 : check + 1;
  else current = 1;
  return steps.map((s, i) => ({
    ...s,
    state:
      done[i] && i !== current ? "done" : i === current ? "current" : "todo",
  }));
}
