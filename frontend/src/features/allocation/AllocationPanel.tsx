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
            <p>시연 가용량 기준</p>
          </div>
        ))}
      </div>
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
        설비 상태를 확인한 실제 제어안이 아닙니다. 현재 자원 가용량은 시연
        추정치이며 실제 저장·출력제한 명령을 전송하지 않습니다.
      </p>
    </>
  );
}
