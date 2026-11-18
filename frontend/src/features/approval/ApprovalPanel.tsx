import { useState } from "react";
import { ShieldCheck, Send } from "lucide-react";
import { DraftView } from "./DraftView";
import { Button } from "../../components/Button";
import { Modal } from "../../components/Modal";
import { blockLabels, canReview } from "../analysis/state";
import { conditionFacts } from "../analysis/RunConditions";
import type { AnalysisRun, Transport } from "../analysis/types";

type Props = {
  run: AnalysisRun | null;
  transport: Transport;
  matches: boolean;
  busy: boolean;
  reviewExpired?: boolean;
  onDecide: (
    action: "approve" | "reject",
    reason: string,
    token: string,
    approver: string,
  ) => Promise<void>;
  /** Logged-in officer; when present the modal reuses its token. */
  session?: { approverId: string; token: string } | null;
  onLogin?: () => void;
};
export function ApprovalPanel({
  run,
  transport,
  matches,
  busy,
  reviewExpired = false,
  onDecide,
  session = null,
  onLogin,
}: Props) {
  const [action, setAction] = useState<"approve" | "reject" | null>(null);
  const [reason, setReason] = useState("");
  const [typedApprover, setApprover] = useState("");
  const approver = session?.token ?? typedApprover;
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState("");
  const [reviewed, setReviewed] = useState<AnalysisRun | null>(null);
  const sameResult = Boolean(
    reviewed &&
    run &&
    reviewed.id === run.id &&
    reviewed.result_token === run.result_token,
  );
  const eligible = !reviewExpired && canReview(run, transport, matches);
  const retry =
    run?.status === "decision_pending" &&
    Boolean(run.decision_intent) &&
    transport === "confirmed" &&
    matches;
  const notificationLabels: Record<string, string> = {
    mock_sent: "시연 발송 처리 완료",
    pending: "발송 대기",
    sending: "발송 응답 확인 중",
    sent: "알림 수신처 응답 확인",
    blocked: "실제 발송 차단",
    delivery_unknown: "발송 결과 확인 불가",
  };
  async function confirm() {
    if (
      !reviewed?.result_token ||
      !sameResult ||
      !action ||
      (!eligible && !retry)
    )
      return;
    if (!reason.trim() || !approver.trim() || !checked) {
      setError("사유, 담당자 인증, 확인 항목을 모두 입력하세요.");
      return;
    }
    try {
      await onDecide(action, reason.trim(), reviewed.result_token, approver);
      setAction(null);
      setApprover("");
      setReason("");
      setChecked(false);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "결정 상태를 다시 확인하세요.",
      );
    }
  }
  function open(value: "approve" | "reject") {
    setReviewed(run);
    setAction(value);
    setError("");
    setChecked(false);
    setApprover("");
    setReason(retry ? run?.decision_intent?.reason || "" : "");
  }
  return (
    <div className="approval-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">HUMAN REVIEW</span>
          <h2>담당자 검토</h2>
        </div>
        <ShieldCheck size={22} />
      </div>
      <p className="section-description">
        계산 결과를 검토하고, 확인한 결과에 대해 결정을 남깁니다.
      </p>
      <div className="review-facts">
        <div>
          <span>검토 대상</span>
          <strong>
            {run
              ? `${run.request.date} · ${run.id.slice(0, 8)}`
              : "선택된 분석 없음"}
          </strong>
        </div>
        {conditionFacts(run).map(({ label, value }) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
        <div>
          <span>운영 검증</span>
          <strong>미완료 · 실제 조치 불가</strong>
        </div>
        <div>
          <span>전송 방식</span>
          <strong>시연 검토만 가능</strong>
        </div>
      </div>
      {run?.draft ? (
        <DraftView run={run} />
      ) : (
        <div className="draft-empty">검토할 초안이 아직 없습니다.</div>
      )}
      {transport !== "confirmed" && run && (
        <p className="notice notice--warning">
          최신 서버 상태를 확인하기 전에는 결정할 수 없습니다.
        </p>
      )}
      {!matches && run && (
        <p className="notice notice--warning">
          선택한 조건과 표시된 결과의 조건이 다릅니다.
        </p>
      )}
      {run?.decision_blocks
        .filter((code) => code !== "not_awaiting_approval" || !run.decision)
        .map((code) => (
          <p className="block-reason" key={code}>
            {blockLabels[code] || "서버에서 결정을 제한했습니다."}
          </p>
        ))}
      {run?.decision && (
        <div className="decision-record">
          <ShieldCheck size={18} />
          <div>
            <strong>
              {run.decision.action === "approve"
                ? "검토 승인 기록"
                : "반려 기록"}
            </strong>
            <p>
              {run.decision.reason} · {run.decision.actor}
            </p>
          </div>
        </div>
      )}
      {run?.notification && (
        <div className="decision-record">
          <Send size={18} />
          <div>
            <strong>{notificationLabels[run.notification.status]}</strong>
            <p>
              알림 상태이며, 저장·출력제한 등 설비 동작의 완료를 뜻하지
              않습니다.
            </p>
          </div>
        </div>
      )}
      <div className="review-actions">
        {retry ? (
          <Button onClick={() => open(run!.decision_intent!.action)}>
            기록된 결정 재시도
          </Button>
        ) : (
          <>
            <Button
              variant="secondary"
              disabled={!eligible}
              onClick={() => open("reject")}
            >
              반려 검토
            </Button>
            <Button disabled={!eligible} onClick={() => open("approve")}>
              시연 승인 검토
            </Button>
          </>
        )}
      </div>
      <p className="caption">
        승인과 반려는 되돌릴 수 없습니다. 실제 전력 설비에는 명령을 보내지
        않습니다.
      </p>
      {action && (
        <Modal
          title={
            action === "approve"
              ? "이 결과를 시연 승인할까요?"
              : "이 결과를 반려할까요?"
          }
          locked={busy}
          onClose={() => setAction(null)}
        >
          <p className="notice">
            {reviewed?.request.date} · 분석 {reviewed?.id.slice(0, 8)}
            <br />
            발전량/수요 최대{" "}
            {((reviewed?.result?.peak_ratio ?? 0) * 100).toFixed(0)}%
            <br />
            피크 잉여전력 {reviewed?.result?.peak_surplus_mwh.toFixed(1)} MWh
          </p>
          {!sameResult && (
            <p role="alert" className="notice notice--warning">
              검토 대상이 변경되었습니다. 이 창을 닫고 새 결과를 다시
              검토하세요.
            </p>
          )}
          <form
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void confirm();
            }}
          >
            <div className="field">
              <label htmlFor="reason">검토 사유</label>
              <textarea
                id="reason"
                rows={3}
                maxLength={1000}
                value={reason}
                readOnly={retry}
                onChange={(event) => setReason(event.target.value)}
                aria-describedby="review-help"
              />
            </div>
            {session ? (
              <p className="notice">
                <strong>{session.approverId}</strong> 담당자로 로그인되어 있어
                로그인한 인증 토큰으로 결정을 기록합니다.
              </p>
            ) : (
              <div className="field">
                <label htmlFor="approver">담당자 인증 토큰</label>
                <input
                  id="approver"
                  type="password"
                  value={approver}
                  autoComplete="off"
                  onChange={(event) => setApprover(event.target.value)}
                />
                {onLogin && (
                  <button
                    type="button"
                    className="login-link"
                    onClick={() => {
                      setAction(null);
                      onLogin();
                    }}
                  >
                    로그인하면 토큰을 매번 입력하지 않아도 됩니다
                  </button>
                )}
              </div>
            )}
            <label className="checkbox">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => setChecked(e.target.checked)}
              />
              시연 결과임을 확인했고, 이 결과에 대한 결정을 기록합니다.
            </label>
            <p id="review-help" className="caption">
              인증 토큰은 이번 창에서만 사용하며 저장하지 않습니다.
            </p>
            {error && (
              <p role="alert" className="notice notice--warning">
                {error}
              </p>
            )}
            <div className="modal-actions">
              <Button
                variant="secondary"
                type="button"
                disabled={busy}
                onClick={() => setAction(null)}
              >
                돌아가기
              </Button>
              <Button
                type="submit"
                variant={action === "reject" ? "danger" : "primary"}
                busy={busy}
                disabled={
                  !sameResult ||
                  !checked ||
                  !reason.trim() ||
                  !approver.trim() ||
                  (!eligible && !retry)
                }
              >
                {action === "approve" ? "시연 승인 기록" : "반려 기록"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
