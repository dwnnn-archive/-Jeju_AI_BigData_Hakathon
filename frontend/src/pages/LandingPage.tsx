import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ChevronDown,
  CircleCheck,
  History,
  LayoutDashboard,
  Play,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import type { AnalysisRun, Transport } from "../features/analysis/types";
import { regions } from "../features/analysis/AnalysisForm";
import { HeroTurbines } from "../components/HeroTurbines";

export type LandingTarget =
  "dashboard" | "forecast" | "allocation" | "approval" | "history";

const slides: {
  label: string;
  title: [string, string];
  points: [string, string];
  cta: string;
  target: LandingTarget;
}[] = [
  {
    label: "발전량 예측",
    title: ["내일의 잉여전력을", "하루 먼저 확인합니다"],
    points: [
      "기상 예보와 전력 수요로 24시간 발전량 예측",
      "출력제한 위험 시간대를 한눈에 표시",
    ],
    cta: "대시보드 바로가기",
    target: "dashboard",
  },
  {
    label: "자원 배분",
    title: ["피크 1시간, 남는 전력을", "어디로 보낼지 권고합니다"],
    points: [
      "대형 ESS · 분산형 ESS · 수소 전환 · 스마트 충전 배분",
      "흡수율과 남는 전력량까지 함께 계산",
    ],
    cta: "배분 권고 보기",
    target: "allocation",
  },
  {
    label: "통보문 확인",
    title: ["AI가 통보문 초안을 쓰고", "담당자가 발송을 정합니다"],
    points: [
      "발송 결정과 사유, 실행 기록을 함께 보관",
      "시연 모드에서는 실제 문자·설비 명령을 보내지 않음",
    ],
    cta: "통보문 확인하러 가기",
    target: "approval",
  },
];
const riskLabel = { NORMAL: "정상 범위", CAUTION: "경계", CRITICAL: "위험" };
const pad = (h: number) => String(h).padStart(2, "0");

export function LandingPage({
  run,
  transport,
  onNavigate,
  onOpenSettings,
}: {
  run: AnalysisRun | null;
  transport: Transport;
  onNavigate: (target: LandingTarget) => void;
  onOpenSettings: () => void;
}) {
  // Slides follow page scroll: the hero is sticky inside a tall track and
  // each third of the track shows the next step (예측 → 배분 → 통보문 확인).
  const track = useRef<HTMLElement>(null);
  const [index, setIndex] = useState(0);
  useEffect(() => {
    let frame = 0;
    function update() {
      frame = 0;
      const el = track.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const range = rect.height - window.innerHeight;
      const progress =
        range > 0 ? Math.min(1, Math.max(0, -rect.top / range)) : 0;
      setIndex(
        Math.min(slides.length - 1, Math.floor(progress * slides.length)),
      );
    }
    function onScroll() {
      if (!frame) frame = requestAnimationFrame(update);
    }
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);
  function goTo(i: number) {
    const el = track.current;
    if (!el) return;
    const range = el.offsetHeight - window.innerHeight;
    const top = el.getBoundingClientRect().top + window.scrollY;
    const reduce = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    window.scrollTo({
      top: top + ((i + 0.5) / slides.length) * range,
      behavior: reduce ? "auto" : "smooth",
    });
  }
  const slide = slides[index];
  const result = transport === "confirmed" ? run?.result : null;

  return (
    <section
      className="hero-track"
      ref={track}
      style={{ ["--slides" as string]: slides.length }}
      aria-roledescription="carousel"
      aria-label="서비스 소개"
    >
      <div className="hero">
        <HeroTurbines />
        <div className="hero-bg" aria-hidden="true" />

        <nav className="hero-dots" aria-label="소개 슬라이드">
          {slides.map((s, i) => (
            <button
              key={s.label}
              className="hero-dot"
              aria-current={i === index ? "true" : undefined}
              aria-label={`${i + 1}. ${s.label}`}
              onClick={() => goTo(i)}
            >
              <span className="hero-dot-mark" aria-hidden="true" />
              {i === index && (
                <span className="hero-dot-label" aria-hidden="true">
                  {s.label}
                </span>
              )}
            </button>
          ))}
        </nav>

        <div className="hero-content" key={index} aria-live="polite">
          <p className="hero-eyebrow">
            <span aria-hidden="true">|</span> 제 주 에 너 지{" "}
            <span aria-hidden="true">|</span>
          </p>
          <h1 className="hero-title">
            {slide.title[0]}
            <br />
            {slide.title[1]}
          </h1>
          <ul className="hero-points">
            {slide.points.map((p) => (
              <li key={p}>
                <CircleCheck size={24} aria-hidden="true" />
                {p}
              </li>
            ))}
          </ul>
          <button className="hero-cta" onClick={() => onNavigate(slide.target)}>
            {slide.cta}
            <ArrowRight size={20} aria-hidden="true" />
          </button>
          {result && run && (
            <p className="hero-live">
              <span
                className={`hero-live-dot hero-live-dot--${result.risk.toLowerCase()}`}
              />
              최근 분석 · {result.date} {regions[run.request.region]} · 피크{" "}
              {pad(result.peak_hour)}시 {result.peak_surplus_mwh.toFixed(1)} MWh
              · {riskLabel[result.risk]}
              {run.simulation ? " (시연 데이터)" : ""}
            </p>
          )}
        </div>

        <aside className="quick-menu" aria-label="빠른 메뉴">
          <p className="quick-title">Quick menu</p>
          <ul>
            <li>
              <button onClick={() => onNavigate("forecast")}>
                <Play size={22} aria-hidden="true" />새 분석 요청
              </button>
            </li>
            <li>
              <button onClick={() => onNavigate("dashboard")}>
                <LayoutDashboard size={22} aria-hidden="true" />
                대시보드
              </button>
            </li>
            <li>
              <button onClick={() => onNavigate("approval")}>
                <ShieldCheck size={22} aria-hidden="true" />
                통보문 확인
              </button>
            </li>
            <li>
              <button onClick={() => onNavigate("history")}>
                <History size={22} aria-hidden="true" />
                분석 이력
              </button>
            </li>
            <li>
              <button onClick={onOpenSettings}>
                <Settings2 size={22} aria-hidden="true" />
                연결 설정
              </button>
            </li>
          </ul>
        </aside>

        <div className="hero-progress" aria-hidden="true">
          <span className="hero-progress-count">
            <strong>{String(index + 1).padStart(2, "0")}</strong> /{" "}
            {String(slides.length).padStart(2, "0")}
          </span>
          <span className="hero-progress-bar">
            <span
              style={{ width: `${((index + 1) / slides.length) * 100}%` }}
            />
          </span>
          {index < slides.length - 1 && (
            <span className="hero-scroll-hint">
              스크롤하면 다음 단계
              <ChevronDown size={16} />
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
