import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { DateField } from "./DateField";
import { clampDate, dateLimits } from "../features/analysis/state";

it("limits live analysis to tomorrow and the day after (KST)", () => {
  const now = Date.parse("2026-11-19T14:30:00Z"); // KST 11-19 23:30
  expect(dateLimits("live", now)).toEqual({
    min: "2026-11-20",
    max: "2026-11-21",
  });
  expect(dateLimits("demo", now)).toEqual({});
  const limits = dateLimits("live", now);
  expect(clampDate("2026-11-10", limits)).toBe("2026-11-20");
  expect(clampDate("2026-12-01", limits)).toBe("2026-11-21");
  expect(clampDate("2026-11-21", limits)).toBe("2026-11-21");
  expect(clampDate("2026-12-01", {})).toBe("2026-12-01");
});

it("greys out and disables calendar days outside min..max", () => {
  const onChange = vi.fn();
  render(
    <DateField
      id="d"
      value="2026-11-20"
      onChange={onChange}
      min="2026-11-20"
      max="2026-11-21"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "달력 열기" }));
  expect(screen.getByRole("button", { name: /11월 20일/ })).toBeEnabled();
  expect(screen.getByRole("button", { name: /11월 21일/ })).toBeEnabled();
  const outside = screen.getByRole("button", { name: /11월 22일/ });
  expect(outside).toBeDisabled();
  expect(outside).toHaveAccessibleName(/선택할 수 없음/);
  fireEvent.click(outside);
  expect(onChange).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: /11월 19일/ })).toBeDisabled();
});

it("has no limit without min/max (demo mode)", () => {
  render(<DateField id="d" value="2026-11-20" onChange={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "달력 열기" }));
  expect(screen.getByRole("button", { name: /11월 1일/ })).toBeEnabled();
});
