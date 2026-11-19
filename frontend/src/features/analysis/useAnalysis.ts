import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type Api } from "../../api/client";
import { acceptSnapshot } from "./state";
import {
  requestSchema,
  type AnalysisRequest,
  type AnalysisRun,
  type Transport,
} from "./types";

type Pending = { id: string; request: AnalysisRequest };
const savedKey = "jeju.pending-analysis";
function readSaved(): Pending | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(savedKey) || "null");
    if (
      value &&
      typeof value.id === "string" &&
      /^[a-f0-9-]{36}$/.test(value.id)
    ) {
      return { id: value.id, request: requestSchema.parse(value.request) };
    }
  } catch {
    /* Missing/invalid local reference is not server state. */
  }
  return null;
}
function remember(pending: Pending) {
  try {
    sessionStorage.setItem(savedKey, JSON.stringify(pending));
  } catch {
    /* Storage may be disabled. */
  }
}

export function useAnalysis(api: Api) {
  const [active, setActive] = useState<Pending | null>(readSaved);
  const [run, setRun] = useState<AnalysisRun | null>(null);
  const [transport, setTransport] = useState<Transport>(
    active ? "checking" : "idle",
  );
  const [error, setError] = useState("");
  // 날짜 범위를 벗어나 접수가 거절된 경우. 접수된 분석이 없으므로 상태 확인 불가로 보이지 않는다.
  const [rejection, setRejection] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [reviewExpired, setReviewExpired] = useState(false);
  const [lastConfirmed, setLastConfirmed] = useState<number | null>(null);
  const latest = useRef<AnalysisRun | null>(null);
  const busy = useRef(false);
  const epoch = useRef(0);
  const expiry = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const reviewExpiry = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  const accept = useCallback((value: AnalysisRun, id: string, elapsed = 0) => {
    const next = acceptSnapshot(latest.current, value, id);
    if (next !== value) return;
    latest.current = next;
    setRun(next);
    clearTimeout(expiry.current);
    clearTimeout(reviewExpiry.current);
    const checkedAt = Date.parse(value.server_checked_at);
    const remaining = Math.min(
      7000,
      value.fresh_until_epoch === null
        ? Infinity
        : value.fresh_until_epoch * 1000 - checkedAt - elapsed,
    );
    const reviewRemaining =
      value.status === "awaiting_approval" && value.expires_at
        ? Date.parse(value.expires_at) - checkedAt - elapsed
        : Infinity;
    setReviewExpired(reviewRemaining <= 0);
    // Longer deadlines are re-evaluated by polling; confirmation itself lasts at most 7s.
    if (reviewRemaining > 0 && reviewRemaining <= 7000) {
      reviewExpiry.current = setTimeout(
        () => setReviewExpired(true),
        reviewRemaining,
      );
    }
    setLastConfirmed(Date.now());
    setError("");
    setTransport(
      remaining > 0 && value.status !== "status_unknown"
        ? "confirmed"
        : "unknown",
    );
    expiry.current = setTimeout(
      () => setTransport("unknown"),
      Math.max(0, remaining),
    );
  }, []);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let failures = 0;
    let inFlight = false;
    let visibilityVersion = 0;
    const token = ++epoch.current;
    const poll = async () => {
      if (cancelled || document.hidden || busy.current || inFlight) return;
      inFlight = true;
      const observedVisibility = visibilityVersion;
      const started = performance.now();
      try {
        const value = await api.get(active.id);
        if (
          cancelled ||
          token !== epoch.current ||
          busy.current ||
          document.hidden ||
          observedVisibility !== visibilityVersion
        )
          return;
        accept(value, active.id, performance.now() - started);
        failures = 0;
        timer = setTimeout(
          poll,
          ["queued", "running", "decision_pending"].includes(value.status)
            ? 1000
            : 5000,
        );
      } catch (cause) {
        if (
          cancelled ||
          token !== epoch.current ||
          document.hidden ||
          observedVisibility !== visibilityVersion
        )
          return;
        clearTimeout(expiry.current);
        clearTimeout(reviewExpiry.current);
        setTransport("unknown");
        setError(
          cause instanceof Error ? cause.message : "상태를 확인할 수 없습니다.",
        );
        if (++failures < 3) timer = setTimeout(poll, 3000);
      } finally {
        inFlight = false;
        if (
          !cancelled &&
          token === epoch.current &&
          !document.hidden &&
          observedVisibility !== visibilityVersion
        )
          timer = setTimeout(poll, 0);
      }
    };
    const visibility = () => {
      clearTimeout(timer);
      visibilityVersion++;
      setTransport("checking");
      clearTimeout(expiry.current);
      clearTimeout(reviewExpiry.current);
      if (!document.hidden) void poll();
    };
    void poll();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearTimeout(expiry.current);
      clearTimeout(reviewExpiry.current);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [active, api, accept, refreshKey]);

  const submit = useCallback(
    async (body: AnalysisRequest, existing?: Pending) => {
      if (busy.current) return;
      busy.current = true;
      epoch.current++;
      clearTimeout(expiry.current);
      clearTimeout(reviewExpiry.current);
      setActive(null);
      setLastConfirmed(null);
      setRun(null);
      latest.current = null;
      setTransport("sending");
      setError("");
      setRejection("");
      const pending = existing || { id: crypto.randomUUID(), request: body };
      remember(pending);
      let rejected = false;
      const started = performance.now();
      try {
        const value = await api.submit(pending.id, pending.request);
        accept(value, pending.id, performance.now() - started);
      } catch (cause) {
        if (cause instanceof ApiError && cause.code === "date_out_of_range") {
          rejected = true;
          setTransport("idle");
          setRejection(cause.message);
          try {
            sessionStorage.removeItem(savedKey);
          } catch {
            /* Storage may be disabled. */
          }
          return;
        }
        setTransport("unknown");
        setError(
          cause instanceof Error
            ? cause.message
            : "접수 여부를 확인할 수 없습니다.",
        );
      } finally {
        busy.current = false;
        if (!rejected) setActive(pending);
      }
    },
    [api, accept],
  );

  const select = useCallback((id: string, request: AnalysisRequest) => {
    if (busy.current) return;
    epoch.current++;
    latest.current = null;
    setLastConfirmed(null);
    setRun(null);
    setTransport("checking");
    const pending = { id, request };
    remember(pending);
    setActive(pending);
  }, []);

  const refresh = useCallback(() => {
    if (busy.current) return;
    setTransport("checking");
    setRefreshKey((value) => value + 1);
  }, []);

  const decide = useCallback(
    async (
      action: "approve" | "reject",
      reason: string,
      token: string,
      approver: string,
    ) => {
      if (
        !active ||
        busy.current ||
        transport !== "confirmed" ||
        !latest.current ||
        token !== latest.current.result_token
      )
        throw new Error("확인된 최신 결과를 다시 검토하세요.");
      busy.current = true;
      epoch.current++;
      clearTimeout(expiry.current);
      clearTimeout(reviewExpiry.current);
      setDecisionBusy(true);
      setTransport("checking");
      const started = performance.now();
      try {
        const value = await api.decide(
          active.id,
          action,
          reason,
          token,
          approver,
        );
        accept(value, active.id, performance.now() - started);
      } catch (cause) {
        setTransport("unknown");
        setError(
          cause instanceof Error
            ? cause.message
            : "결정 결과를 확인하지 못했습니다.",
        );
        throw cause;
      } finally {
        busy.current = false;
        setDecisionBusy(false);
        setRefreshKey((value) => value + 1);
      }
    },
    [active, api, accept, transport],
  );

  return {
    reviewExpired,
    active,
    run,
    transport,
    error,
    rejection,
    clearRejection: () => setRejection(""),
    lastConfirmed,
    decisionBusy,
    submit,
    select,
    refresh,
    decide,
    retrySame: () => active && submit(active.request, active),
  };
}
