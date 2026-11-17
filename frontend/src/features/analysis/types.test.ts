import { expect, it } from "vitest";
import { runFixture } from "../../test/fixtures";
import { runSchema } from "./types";

it.each([
  { status: "running", started_at: null },
  { can_decide: true, decision_blocks: ["superseded"] },
  { simulation: false },
  { result: { ...runFixture().result!, date: "2026-11-16" } },
  {
    result: {
      ...runFixture().result!,
      hourly: runFixture().result!.hourly.slice(0, 23),
    },
  },
])("rejects inconsistent or incomplete server evidence: %j", (invalid) => {
  expect(runSchema.safeParse({ ...runFixture(), ...invalid }).success).toBe(
    false,
  );
});

it("accepts the intraday phase, its check number and the from_hour of the result", () => {
  const run = runFixture();
  const parsed = runSchema.safeParse({
    ...run,
    status: "completed",
    can_decide: false,
    decision_blocks: ["not_awaiting_approval"],
    phase: "intraday",
    check_no: 2,
    request: {
      ...run.request,
      scenario: "intraday_escalation",
      phase: "intraday",
    },
    result: { ...run.result!, from_hour: 7 },
  });
  expect(parsed.success).toBe(true);
  expect(parsed.success && parsed.data.check_no).toBe(2);
});

it("still accepts runs from before the phase field existed", () => {
  expect(runSchema.safeParse(runFixture()).success).toBe(true);
});
