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
  expect(screen.getAllByText("시연 가용량 기준")).toHaveLength(4);
});
