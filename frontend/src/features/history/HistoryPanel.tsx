import type { AnalysisSummary } from "../analysis/types";
import { labels, phaseLabel } from "../analysis/state";
import { regions } from "../analysis/AnalysisForm";
import { longDate } from "../analysis/FlowChart";

const timeFormat = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function HistoryPanel({
  items,
  error,
  loading,
  onSelect,
  onRefresh,
}: {
  items: AnalysisSummary[];
  error: string;
  loading: boolean;
  onSelect: (item: AnalysisSummary) => void;
  onRefresh: () => void;
}) {
  const waiting = items.filter(
    (i) => i.status === "awaiting_approval" && !i.confirmation,
  ).length;
  const confirmed = items.filter(
    (i) => i.status === "awaiting_approval" && i.confirmation,
  ).length;
  return (
    <section className="ed-history" aria-labelledby="ed-history-title">
      <div className="ed-history-head">
        <h2 id="ed-history-title">
          최근 {items.length}건
          {waiting > 0 && <span> · 통보문 확인 대기 {waiting}건</span>}
          {confirmed > 0 && <span> · 확인 완료 {confirmed}건</span>}
        </h2>
        <button
          type="button"
          className="dv-link"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? "확인 중" : "이력 새로고침 ›"}
        </button>
      </div>
      <p className="dv-caption ed-history-note">
        최근 30건 · 상태는 이력을 불러온 시점의 기록입니다. 결과를 열면 다시
        확인합니다.
      </p>
      {error && (
        <p className="notice notice--warning" role="alert">
          {error}
        </p>
      )}
      {loading && !items.length && (
        <p role="status" className="dv-caption">
          이력을 확인하고 있습니다.
        </p>
      )}
      {items.length ? (
        <ul className="ed-history-list">
          {items.map((item) => (
            <li key={item.id}>
              <div className="ed-history-main">
                <strong>{longDate(item.request.date)}</strong>
                <span>
                  {regions[item.request.region]} ·{" "}
                  {phaseLabel(item.phase ?? item.request.phase, item.check_no)}{" "}
                  · {item.simulation ? "시연" : "외부 · 운영 검증 전"} · 접수{" "}
                  {timeFormat.format(new Date(item.created_at))}
                </span>
              </div>
              <span
                className={`ed-status ed-status--${item.status === "awaiting_approval" ? "pending" : item.status === "failed" || item.status === "interrupted" ? "bad" : "plain"}`}
              >
                {item.status === "awaiting_approval" && item.confirmation
                  ? "담당자 확인 완료"
                  : labels[item.status]}
              </span>
              <span className="mono ed-history-id">{item.id.slice(0, 8)}</span>
              <button
                type="button"
                className="dv-link"
                onClick={() => onSelect(item)}
                aria-label={`${item.request.date} ${item.id.slice(0, 8)} 결과 열기`}
              >
                결과 열기 ›
              </button>
            </li>
          ))}
        </ul>
      ) : !loading && !error ? (
        <section className="ed-empty">
          <h2>저장된 분석이 없습니다.</h2>
          <p>
            분석을 요청하면 접수 내역과 확인된 결과를 이곳에서 찾을 수 있습니다.
          </p>
        </section>
      ) : null}
    </section>
  );
}
