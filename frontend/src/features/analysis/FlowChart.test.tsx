import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { runFixture } from "../../test/fixtures";
import { FlowChart } from "./FlowChart";

it("explains surplus against the response threshold when generation stays below demand", () => {
  const result = runFixture().result!;
  expect(
    result.hourly.every((row) => row.generation_mwh < row.demand_mwh),
  ).toBe(true);
  render(
    <FlowChart
      hourly={result.hourly}
      warningRatio={result.thresholds.warning_ratio}
    />,
  );
  expect(screen.getByRole("img")).toHaveAccessibleName(
    "시간별 발전량과 수요. 12시부터 13시까지 발전량이 수요의 40% 대응 기준보다 많습니다.",
  );
  expect(
    screen.getByText(/수요의 40% 대응 기준 · 음영: 기준 초과분/),
  ).toBeInTheDocument();
});
