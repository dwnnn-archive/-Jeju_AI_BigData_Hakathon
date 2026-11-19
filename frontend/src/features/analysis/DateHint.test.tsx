import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { DateHint } from "./DateHint";

it("tells the officer which dates can be analysed and that demo mode is unlimited", () => {
  render(<DateHint />);
  expect(
    screen.getByText(/내일부터 모레까지 분석할 수 있습니다/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/오늘은 당일 점검, 과거 날짜는 지원하지 않습니다/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/단, 시연모드에는 날짜 제한이 없습니다/),
  ).toBeInTheDocument();
});
