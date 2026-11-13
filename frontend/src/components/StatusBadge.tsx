import { CheckCircle2, Clock3, AlertCircle, LoaderCircle } from "lucide-react";
import { statusLabel } from "../features/analysis/state";
import type { AnalysisRun, Transport } from "../features/analysis/types";
export function StatusBadge({
  run,
  transport,
}: {
  run: AnalysisRun | null;
  transport: Transport;
}) {
  const label = statusLabel(transport, run);
  const unknown = transport === "unknown" || run?.status === "status_unknown";
  const failed = run?.status === "failed" || run?.status === "interrupted";
  const processing =
    ["sending", "checking"].includes(transport) || run?.status === "running";
  const Icon =
    unknown || failed
      ? AlertCircle
      : processing
        ? LoaderCircle
        : run?.result
          ? CheckCircle2
          : Clock3;
  return (
    <span
      className={`status-badge ${unknown || failed ? "status-badge--warning" : ""}`}
      role="status"
      aria-label="분석 상태"
    >
      <Icon size={15} aria-hidden="true" />
      {label}
    </span>
  );
}
