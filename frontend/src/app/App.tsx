import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  BatteryCharging,
  CheckSquare2,
  History,
  Settings2,
  RefreshCw,
  ShieldCheck,
  ChevronRight,
  Menu,
} from "lucide-react";
import { createApi } from "../api/client";
import { useAnalysis } from "../features/analysis/useAnalysis";
import { AnalysisForm, regions } from "../features/analysis/AnalysisForm";
import type {
  AnalysisRequest,
  AnalysisSummary,
} from "../features/analysis/types";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { ForecastPage } from "../pages/ForecastPage";
import { AllocationPanel } from "../features/allocation/AllocationPanel";
import { ApprovalPanel } from "../features/approval/ApprovalPanel";
import { HistoryPanel } from "../features/history/HistoryPanel";

type Page = "forecast" | "allocation" | "approval" | "history";
const pages = [
  { id: "forecast", label: "발전량 예측", icon: BarChart3 },
  { id: "allocation", label: "자원 배분", icon: BatteryCharging },
  { id: "approval", label: "승인 관리", icon: CheckSquare2 },
  { id: "history", label: "분석 이력", icon: History },
] as const;
function tomorrow() {
  const now = new Date(Date.now() + 86400000);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}
function formatTime(value: number | null) {
  return value === null
    ? "아직 확인하지 않음"
    : new Intl.DateTimeFormat("ko-KR", {
        timeZone: "Asia/Seoul",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(value);
}

export function App() {
  const [page, setPage] = useState<Page>("forecast");
  const [apiKey, setApiKey] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [keyDraft, setKeyDraft] = useState("");
  const api = useMemo(() => createApi(apiKey), [apiKey]);
  const analysis = useAnalysis(api);
  const [form, setForm] = useState<AnalysisRequest>(
    analysis.active?.request || {
      date: tomorrow(),
      region: "jeju",
      mode: "demo",
      scenario: "critical",
    },
  );
  const [items, setItems] = useState<AnalysisSummary[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyBusy, setHistoryBusy] = useState(true);
  const historySequence = useRef(0);
  const [formError, setFormError] = useState("");
  const { run, transport, error, active } = analysis;
  const matches =
    !run ||
    ["date", "region", "mode", "scenario"].every(
      (key) =>
        form[key as keyof AnalysisRequest] ===
        run.request[key as keyof AnalysisRequest],
    );
  const unresolved = Boolean(
    active &&
    (transport !== "confirmed" ||
      ["queued", "running", "status_unknown", "decision_pending"].includes(
        run?.status || "queued",
      )),
  );
  const loadHistory = useCallback(async () => {
    const sequence = ++historySequence.current;
    setHistoryBusy(true);
    try {
      const next = await api.list();
      if (sequence !== historySequence.current) return;
      setItems(next);
      setHistoryError("");
    } catch (cause) {
      if (sequence !== historySequence.current) return;
      setHistoryError(
        cause instanceof Error ? cause.message : "이력을 확인할 수 없습니다.",
      );
    } finally {
      if (sequence === historySequence.current) setHistoryBusy(false);
    }
  }, [api]);
  useEffect(() => {
    if (page === "history") void loadHistory();
  }, [page, loadHistory]);
  function submit() {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(form.date)) {
      setFormError("예측 대상일을 선택하세요.");
      return;
    }
    setFormError("");
    void analysis.submit(form);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        본문으로 이동
      </a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">
            <Activity size={25} />
          </span>
          <div>
            <strong>제주 에너지</strong>
            <span>예측과 검토</span>
          </div>
        </div>
        <div className="nav-caption">WORKSPACE</div>
        <nav aria-label="주 메뉴">
          {pages.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${page === id ? "active" : ""}`}
              aria-current={page === id ? "page" : undefined}
              onClick={() => setPage(id)}
            >
              <Icon size={19} />
              <span>{label}</span>
              {page === id && <ChevronRight size={15} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="environment">
            <span className="env-dot" />
            <span>검토용 개발 환경</span>
          </div>
          <p>
            확인된 정보로 판단하고,
            <br />
            검토한 결과에 결정을 남깁니다.
          </p>
          <button
            className="nav-item"
            onClick={() => {
              setKeyDraft(apiKey);
              setSettingsOpen(true);
            }}
          >
            <Settings2 size={18} />
            연결 설정
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div>
            <Menu size={16} />
            <span>제주 출력제한 대응</span>
            <span className="divider">/</span>
            <strong>{pages.find((p) => p.id === page)?.label}</strong>
          </div>
          <span className="topbar-note">
            <ShieldCheck size={15} />
            확인 기반 의사결정
          </span>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <p className="eyebrow">JEJU ENERGY INTELLIGENCE</p>
              <h1>{pages.find((p) => p.id === page)?.label}</h1>
              <p>
                다음날의 에너지 흐름을 살펴보고, 대응이 필요한 시간을
                확인하세요.
              </p>
            </div>
            <span className="date-note">한국 표준시 · KST</span>
          </div>
          <div className="mode-banner">
            <span className="mode-tag">
              {form.mode === "demo"
                ? "시연 모드"
                : "외부 데이터 · 운영 검증 전"}
            </span>
            <p>
              {form.mode === "demo"
                ? "미리 정한 데이터로 분석과 검토 절차를 확인합니다. 실제 예측·설비 제어 결과가 아닙니다."
                : "외부 데이터 조회를 시도합니다. 미검증 결과는 실제 조치나 발송에 사용할 수 없습니다."}
            </p>
          </div>
          {page !== "history" && (
            <>
              <section className="panel control-panel" aria-label="분석 조건">
                <AnalysisForm
                  value={form}
                  onChange={setForm}
                  onSubmit={submit}
                  disabled={unresolved || transport === "sending"}
                />
                {formError && (
                  <p role="alert" className="field-error">
                    {formError}
                  </p>
                )}
              </section>
              <div className="status-row">
                <StatusBadge run={run} transport={transport} />
                <span className="last-confirmed">
                  서버 마지막 확인{" "}
                  <strong>{formatTime(analysis.lastConfirmed)}</strong>
                </span>
                {active && (
                  <Button
                    variant="ghost"
                    disabled={transport === "sending" || analysis.decisionBusy}
                    onClick={analysis.refresh}
                  >
                    <RefreshCw size={14} />
                    상태 확인
                  </Button>
                )}
              </div>
              {error && (
                <div role="alert" className="notice notice--warning">
                  <strong>{error}</strong>
                  {active && (
                    <>
                      <p>
                        분석 ID: <span className="mono">{active.id}</span>
                      </p>
                      <Button
                        variant="secondary"
                        onClick={() => void analysis.retrySame()}
                      >
                        같은 요청으로 접수 확인
                      </Button>
                    </>
                  )}
                </div>
              )}
              {run && (
                <div className="result-context">
                  <span>
                    표시된 결과의 대상:{" "}
                    <strong>
                      {run.request.date} · {regions[run.request.region]}
                    </strong>{" "}
                    · {run.simulation ? "시연 데이터" : "외부 데이터"}
                  </span>
                  <span className="mono">ID {run.id.slice(0, 8)}</span>
                </div>
              )}
              {!matches && (
                <p className="notice notice--warning">
                  선택 조건이 바뀌었습니다. 아래 결과는 기존 분석이며, 새 조건의
                  결과가 아닙니다.
                </p>
              )}
            </>
          )}
          {page === "forecast" && <ForecastPage run={run} />}
          {page === "allocation" && (
            <section className="panel">
              <div className="section-heading">
                <div>
                  <span className="eyebrow">RESOURCE ALLOCATION</span>
                  <h2>피크 시간의 자원 배분</h2>
                </div>
              </div>
              <AllocationPanel run={run} />
            </section>
          )}
          {page === "approval" && (
            <section className="panel">
              <ApprovalPanel
                run={run}
                transport={transport}
                matches={matches}
                busy={analysis.decisionBusy}
                reviewExpired={analysis.reviewExpired}
                onDecide={analysis.decide}
              />
            </section>
          )}
          {page === "history" && (
            <HistoryPanel
              loading={historyBusy}
              items={items}
              error={historyError}
              onRefresh={() => void loadHistory()}
              onSelect={(item) => {
                setForm(item.request);
                analysis.select(item.id, item.request);
                setPage("forecast");
              }}
            />
          )}
          {run?.sources &&
            Object.keys(run.sources).length > 0 &&
            page !== "history" && (
              <details className="sources">
                <summary>데이터 출처와 실행 기록</summary>
                <div className="source-grid">
                  {Object.entries(run.sources).map(([key, value]) => (
                    <div key={key}>
                      <strong>
                        {{
                          weather: "기상",
                          generation: "발전량",
                          demand: "수요",
                        }[key] || key}
                      </strong>
                      <span>{String(value.source || "미확인")}</span>
                      <small>
                        {value.simulated
                          ? "시연/대체 데이터"
                          : "외부 조회 또는 추정"}
                      </small>
                    </div>
                  ))}
                </div>
                <p className="caption">
                  실행 기록: {run.trace?.join(" → ") || "아직 없음"}
                </p>
              </details>
            )}
          <footer className="page-footer">
            <span>제주 에너지 · 의사결정 지원</span>
            <span>예측 · 검토 · 승인 기록</span>
          </footer>
        </main>
      </div>
      {settingsOpen && (
        <Modal title="API 연결 설정" onClose={() => setSettingsOpen(false)}>
          <p className="section-description">
            서버에 API 인증이 설정되어 있을 때 입력하세요. 키는 메모리에만
            유지되며 새로고침하면 지워집니다.
          </p>
          <form
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              setApiKey(keyDraft);
              setSettingsOpen(false);
            }}
          >
            <div className="field">
              <label htmlFor="api-key">API 인증 키</label>
              <input
                id="api-key"
                type="password"
                autoComplete="off"
                value={keyDraft}
                onChange={(e) => setKeyDraft(e.target.value)}
              />
            </div>
            <div className="modal-actions">
              <Button type="submit">연결 설정 적용</Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
