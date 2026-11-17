import { describe, expect, it } from "vitest";
import { acceptSnapshot, statusLabel, canReview, phaseLabel } from "./state";
import { runFixture } from "../../test/fixtures";

describe("confirmed state only", () => {
  it("does not turn a click or uncertain receipt into running", () => {
    expect(statusLabel("sending", null)).toBe("요청 전송 중");
    expect(statusLabel("unknown", runFixture({ status: "running" }))).toBe(
      "상태 확인 불가",
    );
    expect(statusLabel("confirmed", runFixture({ status: "queued" }))).toBe(
      "실행 대기 중",
    );
  });
  it("ignores old versions and rejects another analysis", () => {
    const current = runFixture({ version: 3 });
    expect(
      acceptSnapshot(current, runFixture({ version: 2 }), current.id),
    ).toBe(current);
    expect(() =>
      acceptSnapshot(
        current,
        runFixture({ id: "00000000-0000-4000-8000-000000000002" }),
        current.id,
      ),
    ).toThrow();
  });
  it("requires fresh evidence, matching form and server permission", () => {
    const run = runFixture();
    expect(canReview(run, "confirmed", true)).toBe(true);
    expect(canReview(run, "unknown", true)).toBe(false);
    expect(canReview(run, "confirmed", false)).toBe(false);
    expect(
      canReview(runFixture({ can_decide: false }), "confirmed", true),
    ).toBe(false);
  });
});

it("labels the decision phase for day-ahead and intraday checks", () => {
  expect(phaseLabel(undefined)).toBe("하루 전 계획");
  expect(phaseLabel("day_ahead", 0)).toBe("하루 전 계획");
  expect(phaseLabel("intraday", 1)).toBe("당일 1차 점검");
  expect(phaseLabel("intraday")).toBe("당일 점검");
});
