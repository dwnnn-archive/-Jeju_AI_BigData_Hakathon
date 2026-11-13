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
