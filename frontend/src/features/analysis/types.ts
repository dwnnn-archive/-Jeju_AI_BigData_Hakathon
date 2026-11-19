import { z } from "zod";

const energy = z.number().finite().nonnegative();
const time = z.string().datetime({ offset: true });
export const requestSchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  region: z.enum(["jeju", "hallim", "jocheon", "haengwon"]),
  mode: z.enum(["demo", "live"]),
  scenario: z.enum([
    "normal",
    "critical",
    "boundary",
    "boundary_stable",
    "intraday_escalation",
  ]),
  phase: z.enum(["day_ahead", "intraday"]).optional(),
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
/** 담당자가 통보문을 확인했다고 남긴 기록(로그인·발송 없음). */
const confirmation = z.object({ confirmed_at: z.string() });
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
        from_hour: z.number().int().min(0).max(23).optional(),
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
        // EV 용량을 제주데이터허브 충전소 목록으로 계산했을 때만 들어온다.
        ev_basis: z
          .object({
            stations_open: z.number(),
            stations_total: z.number(),
            slow_chargers: z.number(),
            fast_chargers: z.number(),
            base_date: z.string(),
            // history_profile: 충전 이력(월별·요일별)으로 이용률·평균 전력을 계산. assumption: 가정값.
            basis: z.enum(["history_profile", "assumption"]),
            history_months: z.array(z.string()).optional(),
            // 충전소별 설치 규모 기준 상위 목록(충전소별 혼잡도는 반영하지 않음).
            top_stations: z
              .array(
                z.object({
                  name: z.string(),
                  detail: z.string(),
                  slow_chargers: z.number(),
                  fast_chargers: z.number(),
                  capacity_mwh: z.number(),
                  share: z.number(),
                  latitude: z.number().nullable(),
                  longitude: z.number().nullable(),
                }),
              )
              .optional(),
            free_fraction: z
              .object({ slow: z.number(), fast: z.number() })
              .optional(),
            assumptions: z.object({
              slow_kw: z.number(),
              fast_kw: z.number(),
              idle_ratio: z.number(),
            }),
          })
          .optional(),
      })
      .nullable(),
    draft: z.string().nullable(),
    confirmation: confirmation.nullable().optional(),
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
    phase: z.enum(["day_ahead", "intraday"]).optional(),
    check_no: z.number().int().nonnegative().optional(),
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
  phase: z.enum(["day_ahead", "intraday"]).optional(),
  check_no: z.number().int().nonnegative().optional(),
  confirmation: confirmation.nullable().optional(),
});
export type AnalysisRun = z.infer<typeof runSchema>;
export type AnalysisRequest = z.infer<typeof requestSchema>;
export type AnalysisSummary = z.infer<typeof summarySchema>;
export type Transport =
  "idle" | "sending" | "checking" | "confirmed" | "unknown";
