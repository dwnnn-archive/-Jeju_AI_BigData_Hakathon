import type { AnalysisRun } from "../analysis/types";
import { fmt, pad } from "../analysis/FlowChart";
import { RunConditions } from "../analysis/RunConditions";

const resources = [
  { key: "bess", name: "ESS 충전", detail: "대형 ESS · BESS" },
  { key: "vpp", name: "VPP 유연성 자원", detail: "분산형 ESS · VPP" },
  { key: "p2x", name: "수전해 수소 생산", detail: "수소 전환 · P2X" },
  { key: "ev", name: "전기차 충전 전환", detail: "스마트 충전 · EV" },
] as const;

/** 자원별 용량 근거. VPP는 근거 자료를 찾지 못한 가정값이다. */
const basisNote = {
  bess: { tag: "자료 기반", text: "제주 ESS 계량 자료의 실적 기준(하한)" },
  vpp: { tag: "가정값", text: "근거 자료 없음 · 시연용 추정치입니다" },
  p2x: { tag: "보도 기준", text: "행원 실증단지 3.3 MW(보도), 공식 통계 아님" },
} as const;

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
        <h2>대응 후보 제안이 없습니다.</h2>
        <p>
          {run?.result
            ? "피크 잉여전력이 위험 기준 미만이라 자원 배분이 필요하지 않습니다."
            : "분석 결과가 확인되면 피크 1시간에 대한 자원별 대응 후보 제안을 표시합니다."}
        </p>
      </section>
    );
  const allocation = run.allocation;
  const ev = allocation.ev_basis;
  const fromHistory = ev?.basis === "history_profile";
  const historyRange = ev?.history_months?.length
    ? `${ev.history_months[0].slice(0, 4)}~${ev.history_months[ev.history_months.length - 1].slice(0, 4)}`
    : "";
  const baseDate = ev?.base_date
    ? `${ev.base_date.slice(0, 4)}-${ev.base_date.slice(4, 6)}`
    : "";

  const peak = run.result
    ? `${pad(run.result.peak_hour)}:00–${pad((run.result.peak_hour + 1) % 24)}:00`
    : "피크 1시간";
  return (
    <>
      <RunConditions run={run} />
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
                  {key !== "ev" && (
                    <span className={`basis-tag basis-tag--${key}`}>
                      {basisNote[key].tag}
                    </span>
                  )}
                  <p>
                    {key === "ev" && ev
                      ? fromHistory
                        ? `허브 충전소 ${ev.stations_open.toLocaleString()}곳 운영 중 · 충전 이력(${historyRange}) 기반 이용률`
                        : `허브 충전소 ${ev.stations_open.toLocaleString()}곳 운영 중 · 이용률 ${Math.round(ev.assumptions.idle_ratio * 100)}% 가정`
                      : key === "ev"
                        ? "시연 가용량 기준"
                        : basisNote[key].text}
                  </p>
                  <meter
                    className="ed-meter"
                    min={0}
                    max={cap || 1}
                    value={value}
                    aria-label={`${name} 제안 배분량`}
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

      {ev?.top_stations?.length ? (
        <section className="ev-top" aria-labelledby="ev-top-title">
          <h3 id="ev-top-title">
            {run.result?.peak_hour != null
              ? `${String(run.result.peak_hour).padStart(2, "0")}시 `
              : ""}
            충전 여력이 큰 충전소 TOP {ev.top_stations.length}
          </h3>
          <table>
            <thead>
              <tr>
                <th scope="col">순위</th>
                <th scope="col">충전소</th>
                <th scope="col">완속 · 급속</th>
                <th scope="col">여력</th>
                <th scope="col">좌표</th>
              </tr>
            </thead>
            <tbody>
              {ev.top_stations.map((station, index) => (
                <tr
                  key={`${station.name}-${station.latitude}-${station.longitude}`}
                >
                  <td>{index + 1}</td>
                  <td>{station.name}</td>
                  <td>
                    {station.slow_chargers}기 · {station.fast_chargers}기
                  </td>
                  <td>{(station.capacity_mwh * 1000).toFixed(0)} kWh</td>
                  <td>
                    {station.latitude != null && station.longitude != null
                      ? `${station.latitude.toFixed(3)}, ${station.longitude.toFixed(3)}`
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="caption">
            순위는 충전소별 설치 규모(충전기 수 × 전력)로 매겼습니다. 충전소별
            실제 혼잡도와 실시간 사용 여부는 반영하지 못합니다.
          </p>
        </section>
      ) : null}
      <dl className="dv-kpis ed-kpis ed-kpis--3">
        <div>
          <dt>흡수 제안량</dt>
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
        참고용 대응 후보 제안이며 도청이 배분을 정하는 것이 아닙니다. 설비
        상태를 확인한 실제 제어안도 아닙니다.{" "}
        {ev
          ? fromHistory
            ? `스마트 충전(EV) 용량만 제주데이터허브 충전소 정보(기준 ${baseDate}, 전체 ${ev.stations_total.toLocaleString()}곳)와 과거 충전 이력(${historyRange}, 시간대·요일별 이용 패턴)으로 계산했습니다. 이력이 과거라 현재 이용 수준과 다를 수 있습니다. 나머지 자원은 카드의 근거 표시(자료 기반·보도 기준·가정값)를 따르며, 가정값은 확인이 필요합니다. `
            : `스마트 충전(EV) 용량만 제주데이터허브 충전소 정보(기준 ${baseDate}, 전체 ${ev.stations_total.toLocaleString()}곳)로 계산했고, 충전기 출력(완속 ${ev.assumptions.slow_kw}kW·급속 ${ev.assumptions.fast_kw}kW)과 이용률은 가정입니다. 나머지 자원은 카드의 근거 표시(자료 기반·보도 기준·가정값)를 따르며, 가정값은 확인이 필요합니다. `
          : "현재 자원 가용량은 시연 추정치이며 "}
        실제 저장·출력제한 명령을 전송하지 않습니다.
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
                통보문 확인 <span aria-hidden="true">›</span>
              </strong>
            </button>
          )}
        </nav>
      )}
    </>
  );
}
