import type { AnalysisRun } from "../analysis/types";
import { fmt, pad } from "../analysis/FlowChart";

const resources = [
  { key: "bess", name: "ESS 충전", detail: "대형 ESS · BESS" },
  { key: "vpp", name: "VPP 유연성 자원", detail: "분산형 ESS · VPP" },
  { key: "p2x", name: "수전해 수소 생산", detail: "수소 전환 · P2X" },
  { key: "ev", name: "전기차 충전 전환", detail: "스마트 충전 · EV" },
] as const;

export function AllocationPanel({
  run,
  onNext,
  onPrev,
}: {
  run: AnalysisRun | null;
  onNext?: () => void;
  onPrev?: () => void;
}) {
  if (!run?.allocation)
    return (
      <section className="ed-empty">
        <h2>배분 권고안이 없습니다.</h2>
        <p>
          {run?.result
            ? "피크 잉여전력이 위험 기준 미만이라 자원 배분이 필요하지 않습니다."
            : "분석 결과가 확인되면 피크 1시간에 대한 자원별 권고안을 표시합니다."}
        </p>
      </section>
    );
  const allocation = run.allocation;
  const peak = run.result
    ? `${pad(run.result.peak_hour)}:00–${pad((run.result.peak_hour + 1) % 24)}:00`
    : "피크 1시간";
  return (
    <>
      <section className="dv-alloc ed-alloc" aria-labelledby="ed-alloc-title">
        <div>
          <h2 id="ed-alloc-title">
            {fmt(allocation.absorbed_mwh)} MWh를
            <br />
            어디에 배분할까요.
          </h2>
          <p>
            {peak} 피크 1시간 기준이며,
            <br />
            우선순위대로 가용량을 채웁니다.
          </p>
        </div>
        <ul>
          {resources.map(({ key, name, detail }, index) => {
            const value = allocation.allocated_mwh[key];
            const cap = allocation.capacities_mwh[key];
            return (
              <li key={key} className={value > 0 ? undefined : "is-idle"}>
                <span className="ed-rank" aria-label={`${index + 1}순위`}>
                  <b aria-hidden="true">{index + 1}</b>
                  <small aria-hidden="true">순위</small>
                </span>
                <div>
                  <strong>{name}</strong>
                  <span>{detail}</span>
                  <meter
                    className="ed-meter"
                    min={0}
                    max={cap || 1}
                    value={value}
                    aria-label={`${name} 권고 배분량`}
                  />
                </div>
                <p>
                  {fmt(value)}
                  <small>/ {fmt(cap)} MWh</small>
                </p>
              </li>
            );
          })}
        </ul>
      </section>

      <dl className="dv-kpis ed-kpis ed-kpis--3">
        <div>
          <dt>흡수 권고량</dt>
          <dd>
            {fmt(allocation.absorbed_mwh)}
            <small>MWh</small>
          </dd>
        </div>
        <div>
          <dt>배분 후 잔여량</dt>
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
      <p className="dv-caption">
        설비 상태를 확인한 실제 제어안이 아닙니다. 현재 자원 가용량은 시연
        추정치이며 실제 저장·출력제한 명령을 전송하지 않습니다.
      </p>
      {(onPrev || onNext) && (
        <nav className="ed-stepnav" aria-label="단계 이동">
          {onPrev && (
            <button type="button" className="ed-stepnav-prev" onClick={onPrev}>
              <span>
                <span aria-hidden="true">‹ </span>이전 단계
              </span>
              <strong>발전량 예측</strong>
            </button>
          )}
          {onNext && (
            <button type="button" className="ed-stepnav-next" onClick={onNext}>
              다음 단계
              <strong>
                검토·승인 <span aria-hidden="true">›</span>
              </strong>
            </button>
          )}
        </nav>
      )}
    </>
  );
}
