import { z } from "zod";

const energy = z.number().finite().nonnegative();
const time = z.string().datetime({ offset: true });
export const requestSchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  region: z.enum(["jeju", "hallim", "jocheon", "haengwon"]),
  mode: z.enum(["demo", "live"]),
  scenario: z.enum(["normal", "critical", "boundary", "boundary_stable"]),
  query: z.string().nullable().optional(),
});
export const statusSchema = z.enum([
  "queued",
  "running",
  "status_unknown",
  "interrupted",
  "awaiting_approval",
  "completed",
  "approved",
  "rejected",
  "failed",
  "decision_pending",
]);
const risk = z.enum(["NORMAL", "CAUTION", "CRITICAL"]);
const amounts = z.object({
  bess: energy,
  vpp: energy,
  p2x: energy,
  ev: energy,
});
const decision = z.object({
  action: z.enum(["approve", "reject"]),
  reason: z.string(),
  actor: z.string(),
});
export const runSchema = z
  .object({
    id: z.string().uuid(),
    version: z.number().int().positive(),
    status: statusSchema,
    request: requestSchema,
    created_at: time,
    started_at: time.nullable(),
    heartbeat_at: time.nullable(),
    finished_at: time.nullable(),
    expires_at: time.nullable(),
    server_checked_at: time,
    fresh_until_epoch: z.number().finite().nullable(),
    result_token: z
      .string()
      .regex(/^[a-f0-9]{64}$/)
      .nullable(),
    error: z.string().nullable(),
    can_decide: z.boolean(),
    decision_blocks: z.array(z.string()),
    operationally_validated: z.boolean(),
    simulation: z.boolean(),
    result: z
      .object({
        date: z.string(),
        timezone: z.literal("Asia/Seoul"),
        interval_hours: z.literal(1),
        energy_unit: z.literal("MWh"),
        risk,
        peak_hour: z.number().int().min(0).max(23),
        peak_surplus_mwh: energy,
        peak_ratio: energy,
        thresholds: z.object({
          warning_ratio: energy,
          critical_ratio: energy,
          surplus_basis: z.string(),
        }),
        hourly: z
          .array(
            z.object({
              hour: z.number().int().min(0).max(23),
              generation_mwh: energy,
              demand_mwh: energy,
              ratio: energy,
              surplus_mwh: energy,
              risk,
            }),
          )
          .length(24)
          .refine(
            (rows) => new Set(rows.map((r) => r.hour)).size === 24,
            "Duplicate hour",
          ),
      })
      .nullable(),
    allocation: z
      .object({
        allocated_mwh: amounts,
        capacities_mwh: amounts,
        absorbed_mwh: energy,
        residual_mwh: energy,
        absorption_pct: energy.max(100),
        hydrogen_kg: energy,
        scope: z.literal("peak_hour_only"),
        availability_source: z.string(),
        availability_verified: z.boolean(),
      })
      .nullable(),
    draft: z.string().nullable(),
    decision: decision.nullable(),
    decision_intent: decision.nullable(),
    notification: z
      .object({
        id: z.string(),
        status: z.enum([
          "pending",
          "sending",
          "mock_sent",
          "blocked",
          "delivery_unknown",
          "sent",
        ]),
        attempts: z.number().int().nonnegative(),
        detail: z.string().nullable(),
      })
      .passthrough()
      .nullable(),
    sources: z.record(z.string(), z.record(z.string(), z.unknown())),
    trace: z.array(z.string()).optional(),
    refresh_count: z.number().optional(),
    boundary_unresolved: z.boolean().optional(),
  })
  .superRefine((run, ctx) => {
    if (
      run.status === "running" &&
      (!run.started_at || !run.heartbeat_at || !run.fresh_until_epoch)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Missing worker execution evidence",
      });
    }
    if (
      run.can_decide &&
      (run.decision_blocks.length > 0 ||
        !run.expires_at ||
        !run.simulation ||
        run.boundary_unresolved)
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Contradictory review conditions",
      });
    }
    if (run.simulation !== (run.request.mode === "demo")) {
      ctx.addIssue({ code: "custom", message: "Contradictory data mode" });
    }
    if (
      run.can_decide &&
      (!run.result || !run.result_token || run.status !== "awaiting_approval")
    ) {
      ctx.addIssue({
        code: "custom",
        message: "Inconsistent approval eligibility",
      });
    }
    if (run.result && run.result.date !== run.request.date) {
      ctx.addIssue({
        code: "custom",
        message: "Result date differs from request",
      });
    }
  });
export const summarySchema = z.object({
  id: z.string().uuid(),
  status: statusSchema,
  request: requestSchema,
  created_at: time,
  version: z.number().int().positive(),
  simulation: z.boolean(),
});
export type AnalysisRun = z.infer<typeof runSchema>;
export type AnalysisRequest = z.infer<typeof requestSchema>;
export type AnalysisSummary = z.infer<typeof summarySchema>;
export type Transport =
  "idle" | "sending" | "checking" | "confirmed" | "unknown";
