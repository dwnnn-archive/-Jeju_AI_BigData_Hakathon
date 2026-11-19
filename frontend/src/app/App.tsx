import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  History,
  House,
  LayoutDashboard,
  LogIn,
  LogOut,
  Settings2,
  RefreshCw,
  SunMedium,
} from "lucide-react";
import { createApi } from "../api/client";
import { useAnalysis } from "../features/analysis/useAnalysis";
import { AnalysisForm } from "../features/analysis/AnalysisForm";
import { canIntradayCheck, dateLimits } from "../features/analysis/state";
import type {
  AnalysisRequest,
  AnalysisSummary,
} from "../features/analysis/types";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { ForecastPage } from "../pages/ForecastPage";
import { DashboardPage } from "../pages/DashboardPage";
import { LandingPage } from "../pages/LandingPage";
import { LoginPage, type Session } from "../pages/LoginPage";
import { AllocationPanel } from "../features/allocation/AllocationPanel";
import { ApprovalPanel } from "../features/approval/ApprovalPanel";
import { HistoryPanel } from "../features/history/HistoryPanel";
import { ChatPanel } from "../features/chat/ChatPanel";

type Step = "forecast" | "allocation" | "approval";
type Page = "landing" | "login" | "dashboard" | Step | "history";
const steps = [
  {
    id: "forecast",
    label: "발전량 예측",
    short: "예측",
    headline: "발전량 예측",
    description:
      "다음날 시간별 발전량과 수요를 비교해 대응이 필요한 시간을 찾습니다.",
  },
  {
    id: "allocation",
    label: "자원 배분",
    short: "배분",
    headline: "자원 배분",
    description:
      "피크 1시간의 잉여전력을 어떤 자원에 얼마나 흡수할 수 있는지 참고용 대응 후보로 제안합니다.",
  },
  {
    id: "approval",
    label: "통보문 확인",
    short: "통보문",
    headline: "통보문 확인",
    description:
      "AI가 만든 통보문 초안을 담당자가 확인하고, 발송 여부를 정합니다.",
  },
] as const;
const nav = [
  { id: "landing", label: "소개", icon: House },
  { id: "dashboard", label: "대시보드", icon: LayoutDashboard },
  { id: "analysis", label: "분석", icon: BarChart3 },
  { id: "history", label: "분석 이력", icon: History },
] as const;
const isStep = (page: Page): page is Step =>
  page === "forecast" || page === "allocation" || page === "approval";
function pageLabel(page: Page) {
  if (page === "landing") return "소개";
  if (page === "login") return "로그인";
  if (page === "dashboard") return "대시보드";
  if (page === "history") return "분석 이력";
  return steps.find((s) => s.id === page)!.label;
}
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
  const [page, setPage] = useState<Page>("landing");
  const [lastStep, setLastStep] = useState<Step>("forecast");
  const [apiKey, setApiKey] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [keyDraft, setKeyDraft] = useState("");
  // Officer login lives only in memory: a refresh logs out (no token storage).
  const [session, setSession] = useState<Session | null>(null);
  const [returnTo, setReturnTo] = useState<Page>("dashboard");
  const api = useMemo(() => createApi(apiKey), [apiKey]);
  const analysis = useAnalysis(api);
  const [form, setForm] = useState<AnalysisRequest>(
    analysis.active?.request || {
      date: tomorrow(),
      region: "jeju",
      // 기본은 외부 데이터. 시연 데이터는 화면에서 직접 고른다.
      mode: "live",
      scenario: "critical",
    },
  );
  const [items, setItems] = useState<AnalysisSummary[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyBusy, setHistoryBusy] = useState(true);
  const historySequence = useRef(0);
  const [formError, setFormError] = useState("");
  const { run, transport, error, active } = analysis;
  const limits = dateLimits(form.mode);
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
  const intradayReady = canIntradayCheck(run, transport);
  function requestIntraday() {
    if (!run) return;
    setFormError("");
    void analysis.submit({ ...run.request, phase: "intraday" });
  }
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
    if (page === "history" || page === "dashboard") void loadHistory();
  }, [page, loadHistory]);
  useEffect(() => {
    if (isStep(page)) setLastStep(page);
  }, [page]);
  function submit(request: AnalysisRequest = form) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(request.date)) {
      setFormError("예측 대상일을 선택하세요.");
      return;
    }
    setFormError("");
    setForm(request);
    void analysis.submit(request);
  }
  function openItem(item: AnalysisSummary) {
    setForm(item.request);
    analysis.select(item.id, item.request);
    setPage("forecast");
  }
  function openLogin() {
    setReturnTo(page === "login" || page === "landing" ? "dashboard" : page);
    setPage("login");
  }
  async function login(approverId: string, token: string) {
    const confirmed = await api.checkLogin(approverId, token);
    setSession({ approverId: confirmed, token });
    setPage(returnTo);
  }
  // 헤더 아래 선이 메뉴 순서(소개 → 대시보드 → 분석 → 분석 이력)대로 1/4씩 초록색으로 찬다.
  useEffect(() => {
    const stage: Partial<Record<Page, number>> = {
      landing: 1,
      dashboard: 2,
      forecast: 3,
      allocation: 3,
      approval: 3,
      history: 4,
    };
    const root = document.documentElement;
    root.style.setProperty("--scroll-progress", String((stage[page] ?? 0) / 4));
    return () => {
      root.style.removeProperty("--scroll-progress");
    };
  }, [page]);
  const activeStep = isStep(page) ? steps.find((s) => s.id === page)! : null;

  return (
    <div
      className={`app-shell app-shell--gnb ${page === "landing" ? "is-landing" : ""}`}
    >
      <a className="skip-link" href="#main">
        본문으로 이동
      </a>
      <header className={`gnb ${page === "landing" ? "gnb--overlay" : ""}`}>
        <button
          className="gnb-brand"
          onClick={() => setPage("landing")}
          aria-label="제주 출력제한 길잡이 소개 화면으로"
        >
          <span className="brand-mark">
            <Activity size={22} aria-hidden="true" />
          </span>
          <span>
            <strong>제주 출력제한 길잡이</strong>
            <small>출력제한 예측, 대응 보조 AI agent</small>
          </span>
        </button>
        <nav className="gnb-nav" aria-label="주 메뉴">
          {nav.map(({ id, label, icon: Icon }) => {
            const current = id === "analysis" ? isStep(page) : page === id;
            return (
              <button
                key={id}
                className="gnb-link"
                aria-current={current ? "page" : undefined}
                onClick={() => setPage(id === "analysis" ? lastStep : id)}
              >
                <Icon size={20} aria-hidden="true" />
                {label}
              </button>
            );
          })}
        </nav>
        <div className="gnb-actions">
          <span className="gnb-env">
            <span className="env-dot" aria-hidden="true" />
            시연 모드
          </span>
          <button
            className="gnb-pill gnb-pill--icon"
            onClick={() => {
              setKeyDraft(apiKey);
              setSettingsOpen(true);
            }}
            aria-label="연결 설정"
            title="연결 설정"
          >
            <Settings2 size={18} aria-hidden="true" />
          </button>
          {session ? (
            <>
              <span className="gnb-user">{session.approverId} 담당자</span>
              <button
                className="gnb-pill"
                onClick={() => setSession(null)}
                aria-label="로그아웃"
              >
                <LogOut size={18} aria-hidden="true" />
                <span>로그아웃</span>
              </button>
            </>
          ) : (
            <button
              className="gnb-pill"
              onClick={openLogin}
              aria-current={page === "login" ? "page" : undefined}
              aria-label="로그인"
            >
              <LogIn size={18} aria-hidden="true" />
              <span>로그인</span>
            </button>
          )}
        </div>
      </header>
      <div className="workspace">
        <main
          id="main"
          className={
            page === "landing"
              ? "main--landing"
              : isStep(page) || page === "history"
                ? "main--editorial"
                : undefined
          }
        >
          {page === "landing" ? (
            <LandingPage
              run={run}
              transport={transport}
              onNavigate={(target) => setPage(target)}
              onOpenSettings={() => {
                setKeyDraft(apiKey);
                setSettingsOpen(true);
              }}
            />
          ) : page === "login" ? (
            <LoginPage onLogin={login} />
          ) : page === "dashboard" ? (
            <DashboardPage
              run={run}
              transport={transport}
              date={form.date}
              limits={limits}
              onDateChange={(date) => setForm({ ...form, date })}
              onSubmit={() => submit({ ...form, region: "jeju" })}
              submitDisabled={unresolved || transport === "sending"}
              formError={formError}
              onGoReview={() => setPage("allocation")}
              onOpenForecast={() => setPage("forecast")}
            />
          ) : (
            <header className="ed-head">
              <p className="dv-eyebrow">
                {activeStep
                  ? `분석 · ${String(steps.indexOf(activeStep) + 1).padStart(2, "0")} / 03 · ${pageLabel(page)}`
                  : "분석 기록 · 한국 표준시 KST"}
              </p>
              <h1 className="dv-hero dv-hero--md">
                {activeStep ? activeStep.headline : "분석 이력"}
              </h1>
              <p className="dv-lead">
                {activeStep
                  ? activeStep.description
                  : "최근 분석 기록을 확인하고 결과를 다시 엽니다."}
              </p>
            </header>
          )}
          {activeStep && (
            <>
              <nav className="dv-tabs ed-steps" aria-label="분석 단계">
                {steps.map((step, index) => (
                  <button
                    key={step.id}
                    className="dv-tab"
                    aria-current={page === step.id ? "page" : undefined}
                    aria-label={step.label}
                    onClick={() => setPage(step.id)}
                  >
                    <span className="ed-step-num" aria-hidden="true">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <span aria-hidden="true">{step.label}</span>
                  </button>
                ))}
              </nav>
              <section className="ed-conditions" aria-label="분석 조건">
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
                {form.mode === "demo" &&
                  form.scenario === "intraday_escalation" && (
                    <p className="dv-caption">
                      대상일이 오늘로 맞춰집니다. 분석 요청으로 하루 전
                      계획(정상)을 만든 뒤 <strong>당일 점검 요청</strong>을
                      눌러 1차(정상), 2차(위험) 점검을 차례로 확인하세요.
                    </p>
                  )}
                <p className="ed-mode">
                  <strong>
                    {form.mode === "demo"
                      ? "시연 모드"
                      : "외부 데이터 · 운영 검증 전"}
                  </strong>
                  {form.mode === "demo"
                    ? "미리 정한 데이터로 분석과 검토 절차를 확인합니다. 실제 예측·설비 제어 결과가 아닙니다."
                    : "외부 데이터 조회를 시도합니다. 운영 환경 검증 전인 결과는 실제 조치나 발송에 사용할 수 없습니다."}
                </p>
              </section>
              <div className="status-row ed-statusline">
                <StatusBadge run={run} transport={transport} />
                <span className="last-confirmed">
                  서버 마지막 확인{" "}
                  <strong>{formatTime(analysis.lastConfirmed)}</strong>
                </span>
                {intradayReady && (
                  <Button
                    variant="secondary"
                    disabled={unresolved || transport === "sending"}
                    onClick={requestIntraday}
                  >
                    <SunMedium size={14} aria-hidden="true" />
                    당일 점검 요청
                  </Button>
                )}
                {active && (
                  <Button
                    variant="ghost"
                    disabled={transport === "sending" || analysis.decisionBusy}
                    onClick={analysis.refresh}
                  >
                    <RefreshCw size={14} aria-hidden="true" />
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
              {!matches && (
                <p className="notice notice--warning">
                  선택 조건이 바뀌었습니다. 아래 결과는 기존 분석이며, 새 조건의
                  결과가 아닙니다.
                </p>
              )}
            </>
          )}
          {page === "forecast" && (
            <ForecastPage run={run} onNext={() => setPage("allocation")} />
          )}
          {page === "allocation" && (
            <AllocationPanel
              run={run}
              onPrev={() => setPage("forecast")}
              onNext={() => setPage("approval")}
            />
          )}
          {page === "approval" && (
            <section className="ed-approval">
              <ApprovalPanel
                run={run}
                transport={transport}
                matches={matches}
                busy={unresolved}
                onRemeasure={() => run && submit({ ...run.request })}
                regenerate={api.regenerateDraft}
                onConfirm={async () => {
                  if (!run?.result_token) return;
                  await api.confirm(run.id, run.result_token);
                  analysis.refresh();
                }}
              />
            </section>
          )}
          {page === "history" && (
            <HistoryPanel
              loading={historyBusy}
              items={items}
              error={historyError}
              onRefresh={() => void loadHistory()}
              onSelect={openItem}
            />
          )}
          {activeStep && <ChatPanel run={run} ask={api.chat} />}
          {run?.sources &&
            Object.keys(run.sources).length > 0 &&
            activeStep && (
              <details className="dv-details sources">
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
          {page !== "landing" && (
            <footer className="page-footer">
              <span>제주 출력제한 길잡이 · 의사결정 지원</span>
              <span>
                예측값은 검토용 참고 정보이며 실제 조치 승인을 대신하지
                않습니다.
              </span>
            </footer>
          )}
        </main>
      </div>
      {analysis.rejection && (
        <Modal title={analysis.rejection} onClose={analysis.clearRejection}>
          <p>
            외부 데이터 분석은 내일부터 모레까지만 할 수 있습니다. 예측 대상일을
            다시 선택하세요.
          </p>
          <div className="modal-actions">
            <Button onClick={analysis.clearRejection}>확인</Button>
          </div>
        </Modal>
      )}
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
