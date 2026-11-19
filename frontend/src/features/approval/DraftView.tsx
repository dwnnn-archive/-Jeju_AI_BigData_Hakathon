import { FileCheck2, Info } from "lucide-react";
import type { AnalysisRun } from "../analysis/types";
import { fmt, longDate, pad, resourceNames } from "../analysis/FlowChart";

const riskLabel = { NORMAL: "정상", CAUTION: "경계", CRITICAL: "위험" };

/**
 * Readable view of the notification draft. Numbers come from the same server
 * snapshot as the draft (both are bound by result_token); the exact draft
 * text stays available below, unchanged.
 */
export function DraftView({ run }: { run: AnalysisRun }) {
  const { result, allocation, draft } = run;
  if (!draft) return null;
  if (!result || !allocation) {
    return (
      <div className="draft">
        <div>
          <FileCheck2 size={16} aria-hidden="true" />
          통보문 초안
        </div>
        <pre>{draft}</pre>
      </div>
    );
  }
  const hours = `${pad(result.peak_hour)}:00–${pad((result.peak_hour + 1) % 24)}:00`;
  // 배분 순서(EV 먼저)대로 보여 준다.
  const keys = ["ev", "bess", "vpp", "p2x"] as const;
  return (
    <article className="draft-doc" aria-labelledby="draft-title">
      <header className="draft-doc-head">
        <span className="draft-doc-kicker">
          <FileCheck2 size={16} aria-hidden="true" />
          통보문 초안
        </span>
        <span className={`draft-risk draft-risk--${result.risk.toLowerCase()}`}>
          {riskLabel[result.risk]}
        </span>
      </header>
      <h3 id="draft-title">제주 출력제한 상황 요약</h3>
      <p className="draft-doc-when">
        {longDate(result.date)} <strong>{hours}</strong> KST · 피크 1시간
      </p>

      <dl className="draft-doc-facts">
        <div>
          <dt>피크 잉여전력</dt>
          <dd>
            {fmt(result.peak_surplus_mwh)}
            <small>MWh</small>
          </dd>
        </div>
        <div>
          <dt>흡수율</dt>
          <dd>
            {fmt(allocation.absorption_pct)}
            <small>%</small>
          </dd>
        </div>
        <div>
          <dt>배분 후 잔여</dt>
          <dd>
            {fmt(allocation.residual_mwh)}
            <small>MWh</small>
          </dd>
        </div>
        <div>
          <dt>수소 환산 · 13 kg/MWh 가정</dt>
          <dd>
            {fmt(allocation.hydrogen_kg)}
            <small>kg</small>
          </dd>
        </div>
      </dl>

      <h4 className="draft-doc-sub">자원별 배분</h4>
      <ul className="draft-doc-alloc">
        {keys.map((key) => (
          <li key={key}>
            <span>{resourceNames[key]}</span>
            <strong>
              {fmt(allocation.allocated_mwh[key])}
              <small>MWh</small>
            </strong>
          </li>
        ))}
      </ul>

      <p className="draft-doc-note">
        <Info size={18} aria-hidden="true" />
        피크 1시간 대응 후보 제안(참고)입니다. 자원 가용량은 시연 추정치이며
        현장 검증과 담당자 승인이 필요합니다.
      </p>

      <section className="draft-doc-raw" aria-labelledby="draft-raw-title">
        <h4 id="draft-raw-title">발송될 통보문 원문</h4>
        <pre>{draft}</pre>
      </section>
    </article>
  );
}
