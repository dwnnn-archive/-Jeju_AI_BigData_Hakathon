import { Battery, Network, Droplets, CarFront } from "lucide-react";
import type { AnalysisRun } from "../analysis/types";
import { EmptyState } from "../../components/EmptyState";

const resources = [
  { key: "bess", name: "대형 ESS", detail: "BESS", icon: Battery },
  { key: "vpp", name: "분산형 ESS", detail: "VPP", icon: Network },
  { key: "p2x", name: "수소 전환", detail: "P2X", icon: Droplets },
  { key: "ev", name: "스마트 충전", detail: "EV", icon: CarFront },
] as const;

export function AllocationPanel({ run }: { run: AnalysisRun | null }) {
  if (!run?.allocation)
    return (
      <EmptyState
        title="배분 권고안이 없습니다"
        description="계산된 위험도에 따라 피크 1시간에 대한 자원별 권고안을 표시합니다."
      />
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
  return (
    <>
      <div className="allocation-grid">
        {resources.map(({ key, name, detail, icon: Icon }, index) => (
          <div className="resource" key={key}>
            <div className="resource-top">
              <span className="resource-icon">
                <Icon size={20} />
              </span>
              <small>
                {index + 1}순위 · {detail}
              </small>
            </div>
            <h3>{name}</h3>
            <div className="resource-value">
              {allocation.allocated_mwh[key].toFixed(0)}
              <span> / {allocation.capacities_mwh[key]} MWh</span>
            </div>
            <meter
              min={0}
              max={allocation.capacities_mwh[key] || 1}
              value={allocation.allocated_mwh[key]}
              aria-label={`${name} 권고 배분량`}
            />
            <p>
              {key === "ev" && ev
                ? fromHistory
                  ? `허브 충전소 ${ev.stations_open.toLocaleString()}곳 운영 중 · 충전 이력(${historyRange}) 기반 이용률`
                  : `허브 충전소 ${ev.stations_open.toLocaleString()}곳 운영 중 · 이용률 ${Math.round(ev.assumptions.idle_ratio * 100)}% 가정`
                : "시연 가용량 기준"}
            </p>
          </div>
        ))}
      </div>
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
      <div className="allocation-total">
        <span>
          피크 1시간 흡수 권고{" "}
          <strong>{allocation.absorbed_mwh.toFixed(1)} MWh</strong>
        </span>
        <span>
          잔여 <strong>{allocation.residual_mwh.toFixed(1)} MWh</strong>
        </span>
        <span>
          수소 환산 <strong>{allocation.hydrogen_kg.toFixed(0)} kg</strong>
        </span>
      </div>
      <p className="caption">
        설비 상태를 확인한 실제 제어안이 아닙니다.{" "}
        {ev
          ? fromHistory
            ? `스마트 충전(EV) 용량만 제주데이터허브 충전소 정보(기준 ${baseDate}, 전체 ${ev.stations_total.toLocaleString()}곳)와 과거 충전 이력(${historyRange}, 시간대·요일별 이용 패턴)으로 계산했습니다. 이력이 과거라 현재 이용 수준과 다를 수 있습니다. 나머지 자원은 시연 추정치입니다. `
            : `스마트 충전(EV) 용량만 제주데이터허브 충전소 정보(기준 ${baseDate}, 전체 ${ev.stations_total.toLocaleString()}곳)로 계산했고, 충전기 출력(완속 ${ev.assumptions.slow_kw}kW·급속 ${ev.assumptions.fast_kw}kW)과 이용률은 가정입니다. 나머지 자원은 시연 추정치입니다. `
          : "현재 자원 가용량은 시연 추정치이며 "}
        실제 저장·출력제한 명령을 전송하지 않습니다.
      </p>
    </>
  );
}
