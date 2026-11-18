import { describe, expect, it } from "vitest";
import {
  acceptSnapshot,
  statusLabel,
  canReview,
  phaseLabel,
  canIntradayCheck,
  workdaySteps,
} from "./state";
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

describe("intraday check button and workday flow", () => {
  const normal = (extra = {}) =>
    runFixture({
      status: "completed",
      request: {
        date: "2026-11-18",
        region: "jeju",
        mode: "demo",
        scenario: "intraday_escalation",
      },
      result: { ...runFixture().result!, date: "2026-11-18", risk: "NORMAL" },
      ...extra,
    });
  it("shows only for a confirmed NORMAL result of today", () => {
    expect(canIntradayCheck(normal(), "confirmed", "2026-11-18")).toBe(true);
    expect(canIntradayCheck(normal(), "confirmed", "2026-11-19")).toBe(false);
    expect(canIntradayCheck(normal(), "unknown", "2026-11-18")).toBe(false);
    expect(canIntradayCheck(null, "confirmed", "2026-11-18")).toBe(false);
    expect(
      canIntradayCheck(
        runFixture({ status: "awaiting_approval" }),
        "confirmed",
        "2026-11-15",
      ),
    ).toBe(false);
  });
  it("marks the step the current analysis is at", () => {
    const states = (run: Parameters<typeof workdaySteps>[0]) =>
      workdaySteps(run).map((s) => s.state);
    expect(states(null)[0]).toBe("current");
    expect(states(normal())).toEqual([
      "done",
      "current",
      "todo",
      "todo",
      "todo",
      "todo",
    ]);
    expect(
      states(normal({ phase: "intraday", check_no: 1 })).slice(0, 3),
    ).toEqual(["done", "done", "current"]);
    expect(states(runFixture())[3]).toBe("current"); // 위험 · 승인 대기
  });
});
