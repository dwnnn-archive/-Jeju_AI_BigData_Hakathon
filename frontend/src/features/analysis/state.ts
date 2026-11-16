import type { AnalysisRun, Transport } from "./types";

export const labels: Record<AnalysisRun["status"], string> = {
  queued: "실행 대기 중",
  running: "분석 중",
  status_unknown: "상태 확인 불가",
  interrupted: "실행 중단 확인",
  awaiting_approval: "계산 완료 · 검토 필요",
  completed: "계산 완료",
  approved: "검토 승인됨",
  rejected: "반려됨",
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
