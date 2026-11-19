import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { runFixture } from "../../test/fixtures";
import { AllocationPanel } from "./AllocationPanel";

const base = runFixture();

function withHub(
  topStations: unknown[],
  basis: "history_profile" | "assumption",
) {
  return runFixture({
    allocation: {
      ...base.allocation!,
      availability_source: "jejudatahub_ev_stations+assumptions",
      ev_basis: {
        stations_open: 2969,
        stations_total: 3180,
        slow_chargers: 6005,
        fast_chargers: 2462,
        base_date: "20250921",
        basis,
        history_months:
          basis === "history_profile" ? ["202103", "202204"] : undefined,
        top_stations: topStations,
        assumptions: { slow_kw: 7, fast_kw: 50, idle_ratio: 0.5 },
      },
    } as never,
  });
}

const stations = [
  {
    name: "한국마사회 제주본부",
    detail: "주차장",
    slow_chargers: 81,
    fast_chargers: 10,
    capacity_mwh: 0.533,
    share: 0.006,
    latitude: 33.4098,
    longitude: 126.3931,
  },
  {
    name: "채비 제주 초급속 충전소",
    detail: "",
    slow_chargers: 0,
    fast_chargers: 20,
    capacity_mwh: 0.5,
    share: 0.006,
    latitude: null,
    longitude: null,
  },
];

it("shows hub top stations with the limits stated and handles missing coordinates", () => {
  render(<AllocationPanel run={withHub(stations, "assumption")} />);
  const table = screen.getByRole("table");
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(3); // 머리글 + 2곳
  expect(within(rows[1]).getByText("한국마사회 제주본부")).toBeInTheDocument();
  expect(within(rows[1]).getByText("81기 · 10기")).toBeInTheDocument();
  expect(within(rows[1]).getByText("533 kWh")).toBeInTheDocument();
  expect(within(rows[1]).getByText("33.410, 126.393")).toBeInTheDocument();
  expect(within(rows[2]).getByText("-")).toBeInTheDocument(); // 좌표 없음
  expect(screen.getByText(/충전소별 실제 혼잡도와 실시간/)).toBeInTheDocument();
  expect(screen.getByText(/이용률 50% 가정/)).toBeInTheDocument();
});

it("labels history-based capacity and hides the table without hub data", () => {
  const { rerender } = render(
    <AllocationPanel run={withHub(stations, "history_profile")} />,
  );
  expect(
    screen.getByText(/충전 이력\(2021~2022\) 기반 이용률/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/이력이 과거라 현재 이용 수준과 다를 수 있습니다/),
  ).toBeInTheDocument();

  rerender(<AllocationPanel run={base} />);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.getAllByText("시연 가용량 기준")).toHaveLength(1);
  expect(screen.getByText("자료 기반")).toBeInTheDocument();
  expect(screen.getByText("가정값")).toBeInTheDocument();
  expect(screen.getByText("보도 기준")).toBeInTheDocument();
});

function allocated(values: Record<string, number>, residual = 0) {
  return runFixture({
    allocation: {
      ...base.allocation!,
      allocated_mwh: values,
      capacities_mwh: { bess: 37.7, vpp: 30, p2x: 3.3, ev: 111.1 },
      residual_mwh: residual,
      absorbed_mwh: Object.values(values).reduce((a, b) => a + b, 0),
    } as never,
  });
}

it("explains why later resources are zero when an earlier one absorbs everything", () => {
  render(
    <AllocationPanel
      run={allocated({ bess: 37.3, vpp: 0, p2x: 0, ev: 0 })}
      onPrev={() => {}}
      onNext={() => {}}
    />,
  );
  expect(
    screen.getByText(/앞 순위 자원이 다 차야 다음 순위로 넘어갑니다/),
  ).toBeInTheDocument();
  expect(screen.getByText(/ESS 충전까지만으로 흡수되어/)).toBeInTheDocument();
  expect(screen.getByText(/37\.7 MWh를 넘을 때부터/)).toBeInTheDocument();
});

it("says nothing about skipped resources when every resource is used", () => {
  render(
    <AllocationPanel
      run={allocated({ bess: 37.7, vpp: 30, p2x: 3.3, ev: 50 })}
      onPrev={() => {}}
      onNext={() => {}}
    />,
  );
  expect(screen.queryByText(/앞 순위 자원이 다 차야/)).not.toBeInTheDocument();
});
