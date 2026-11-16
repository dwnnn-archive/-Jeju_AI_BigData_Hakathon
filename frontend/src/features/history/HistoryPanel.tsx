import type { AnalysisSummary } from "../analysis/types";
import { labels, phaseLabel } from "../analysis/state";
import { regions } from "../analysis/AnalysisForm";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";

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
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">ANALYSIS RECORDS</span>
          <h2>분석 이력</h2>
        </div>
        <Button variant="secondary" onClick={onRefresh} disabled={loading}>
          이력 새로고침
        </Button>
      </div>
      <p className="section-description">
        최근 30건 · 상태는 이력을 불러온 시점의 기록입니다. 결과를 열면 다시
        확인합니다.
      </p>
      {error && (
        <p className="notice notice--warning" role="alert">
          {error}
        </p>
      )}
      {loading && <p role="status">이력을 확인하고 있습니다.</p>}
      {items.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>대상일 / 지역</th>
                <th>단계</th>
                <th>데이터</th>
                <th>확인된 상태</th>
                <th>분석 ID</th>
                <th>결과</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.request.date}</strong>
                    <br />
                    <span className="muted">
                      {regions[item.request.region]}
                    </span>
                  </td>
                  <td>
                    {phaseLabel(
                      item.phase ?? item.request.phase,
                      item.check_no,
                    )}
                  </td>
                  <td>{item.simulation ? "시연" : "외부 · 검증 전"}</td>
                  <td>{labels[item.status]}</td>
                  <td className="mono">{item.id.slice(0, 8)}</td>
                  <td>
                    <Button
                      variant="ghost"
                      onClick={() => onSelect(item)}
                      aria-label={`${item.request.date} ${item.id.slice(0, 8)} 결과 열기`}
                    >
                      결과 열기
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : !loading && !error ? (
        <EmptyState
          title="저장된 분석이 없습니다"
          description="분석을 요청하면 접수 내역과 확인된 결과를 이곳에서 찾을 수 있습니다."
        />
      ) : null}
    </section>
  );
}
