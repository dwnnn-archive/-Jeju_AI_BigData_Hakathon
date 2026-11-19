import { useEffect, useState } from "react";
import {
  ShieldCheck,
  Send,
  Copy,
  Pencil,
  RefreshCw,
  Users,
} from "lucide-react";
import { DraftView } from "./DraftView";
import { Button } from "../../components/Button";
import { blockLabels } from "../analysis/state";
import { conditionFacts } from "../analysis/RunConditions";
import type { AnalysisRun, Transport } from "../analysis/types";
import type { DraftAnswer } from "./types";

type Props = {
  run: AnalysisRun | null;
  transport: Transport;
  matches: boolean;
  /** 분석이 진행 중이면 재측정을 막는다. */
  busy: boolean;
  onRemeasure: () => void;
  regenerate: (id: string, previous?: string) => Promise<DraftAnswer>;
  /** 담당자가 통보문을 확인했다고 한 번 기록한다(로그인·발송 없음). */
  onConfirm?: () => Promise<void>;
};

/** 통보문을 받을 대상. 사전 정보 제공이며 실제 문자는 기관 시스템으로 발송한다. */
export const recipients = [
  { name: "문자 발송을 승인한 시민", note: "문자 알림 수신에 동의한 시민" },
  {
    name: "관내 충전소 등 운영자 · 재생에너지 사업자",
    note: "충전 수요 조정, 출력 조정 협조 요청",
  },
];

const reasonLabels: Record<string, string> = {
  no_key: "AI 연결 키가 없어 기본 문안을 보여 줍니다.",
  unfaithful:
    "AI 문안의 숫자를 계산 결과와 맞출 수 없어 기본 문안을 보여 줍니다.",
  no_text: "AI가 문안을 돌려주지 않아 기본 문안을 보여 줍니다.",
};
function reasonText(reason?: string | null) {
  if (reason && reasonLabels[reason]) return reasonLabels[reason];
  return "AI 호출에 실패해 기본 문안을 보여 줍니다.";
}

const notificationLabels: Record<string, string> = {
  mock_sent: "시연 발송 처리 완료",
  pending: "발송 대기",
  sending: "발송 응답 확인 중",
  sent: "알림 수신처 응답 확인",
  blocked: "실제 발송 차단",
  delivery_unknown: "발송 결과 확인 불가",
};

export function ApprovalPanel({
  run,
  transport,
  matches,
  busy,
  onRemeasure,
  regenerate,
  onConfirm,
}: Props) {
  const runId = run?.id;
  const [shown, setShown] = useState(false);
  const [override, setOverride] = useState<DraftAnswer | null>(null);
  const [rewriting, setRewriting] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState("");
  // 다른 분석을 보면 이전 분석의 통보문을 이어 보이지 않는다.
  useEffect(() => {
    setShown(false);
    setOverride(null);
    setError("");
    setConfirmError("");
  }, [runId, run?.result_token]);
  const ready = Boolean(
    run?.result && run.draft && transport === "confirmed" && matches,
  );
  const current = run && override ? { ...run, draft: override.draft } : run;
  async function rewrite() {
    if (!run || !current?.draft) return;
    setRewriting(true);
    setError("");
    try {
      setOverride(await regenerate(run.id, current.draft));
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "새 통보문을 받지 못했습니다.",
      );
    } finally {
      setRewriting(false);
    }
  }
  async function confirmDraft() {
    if (!onConfirm || confirming) return;
    setConfirming(true);
    setConfirmError("");
    try {
      await onConfirm();
    } catch (cause) {
      setConfirmError(
        cause instanceof Error
          ? cause.message
          : "확인 기록을 남기지 못했습니다.",
      );
    } finally {
      setConfirming(false);
    }
  }
  async function copyDraft() {
    if (!current?.draft) return;
    try {
      await navigator.clipboard.writeText(current.draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="approval-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">MESSAGE ASSISTANT</span>
          <h2>통보문 발송 도우미</h2>
        </div>
        <ShieldCheck size={22} />
      </div>
      <p className="section-description">
        결과를 다시 측정하거나, 이 결과로 통보문을 작성할 수 있습니다. 문구를
        확인하고 발송할지는 도청 에너지 담당 부서 담당자가 정합니다.
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
          <span>발송 방식</span>
          <strong>시연 · 모의 발송만 가능</strong>
        </div>
      </div>
      <div className="review-actions">
        <Button
          variant="secondary"
          disabled={!run || busy || transport === "sending"}
          onClick={onRemeasure}
        >
          <RefreshCw size={14} aria-hidden="true" />
          재측정
        </Button>
        <Button disabled={!ready || shown} onClick={() => setShown(true)}>
          <Pencil size={14} aria-hidden="true" />
          통보문 작성
        </Button>
      </div>
      {transport !== "confirmed" && run && (
        <p className="notice notice--warning">
          최신 서버 상태를 확인하기 전에는 통보문을 작성할 수 없습니다.
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
            {blockLabels[code] || "서버에서 제한했습니다."}
          </p>
        ))}
      {shown && current?.draft ? (
        <>
          <div className="draft-recipients">
            <h3>
              <Users size={16} aria-hidden="true" />
              통보문 수신 대상
            </h3>
            <ul>
              {recipients.map((r) => (
                <li key={r.name}>
                  <strong>{r.name}</strong>
                  <span>{r.note}</span>
                </li>
              ))}
            </ul>
          </div>
          <DraftView run={current} />
          <div className="draft-copy">
            <Button
              variant="secondary"
              busy={rewriting}
              disabled={!ready}
              onClick={() => void rewrite()}
            >
              <Pencil size={14} aria-hidden="true" />
              수정 (AI가 새로 작성)
            </Button>
            <Button variant="ghost" onClick={() => void copyDraft()}>
              <Copy size={14} aria-hidden="true" />
              {copied ? "복사했습니다" : "통보문 복사"}
            </Button>
          </div>
          {rewriting && (
            <p role="status" className="caption">
              AI가 새 통보문을 쓰는 중입니다. 최대 30초 정도 걸립니다.
            </p>
          )}
          {override && !rewriting && (
            <p className="caption" role="status">
              {override.mode === "llm"
                ? "AI가 새로 쓴 문안입니다. 숫자는 계산 결과와 대조했습니다."
                : reasonText(override.mode_reason)}
            </p>
          )}
          {error && (
            <p role="alert" className="notice notice--warning">
              {error}
            </p>
          )}
          <div className="confirm-box">
            {run?.confirmation ? (
              <>
                <ShieldCheck size={18} aria-hidden="true" />
                <div>
                  <strong>담당자 확인 완료</strong>
                  <p>
                    {new Intl.DateTimeFormat("ko-KR", {
                      timeZone: "Asia/Seoul",
                      dateStyle: "medium",
                      timeStyle: "short",
                    }).format(new Date(run.confirmation.confirmed_at))}
                    {" · 로그인 없이 남긴 확인 기록입니다."}
                  </p>
                </div>
              </>
            ) : (
              <>
                <div>
                  <strong>담당자 확인</strong>
                  <p>
                    통보문 내용을 확인했으면 기록을 남깁니다. 로그인은 필요
                    없고, 기록만 남을 뿐 문자는 발송되지 않습니다.
                  </p>
                </div>
                <Button
                  busy={confirming}
                  disabled={!ready || !onConfirm}
                  onClick={() => void confirmDraft()}
                >
                  확인했습니다
                </Button>
              </>
            )}
          </div>
          {confirmError && (
            <p role="alert" className="notice notice--warning">
              {confirmError}
            </p>
          )}
          <p className="caption">
            수정은 이 화면의 문안만 바꿉니다. 시연에서는 실제 문자가 발송되지
            않으며, 기관의 문자 발송 시스템에 붙여 넣어 사용합니다. 실제 전력
            설비에는 명령을 보내지 않습니다.
          </p>
        </>
      ) : (
        <div className="draft-empty">
          {run?.result
            ? "‘통보문 작성’을 누르면 이 결과로 통보문 초안이 나옵니다."
            : "분석 결과가 있어야 통보문을 작성할 수 있습니다."}
        </div>
      )}
      {run?.decision && (
        <div className="decision-record">
          <ShieldCheck size={18} />
          <div>
            <strong>
              {run.decision.action === "approve"
                ? "발송 결정 기록: 확정"
                : "발송 결정 기록: 보류"}
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
    </div>
  );
}
