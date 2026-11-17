import { useEffect, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const pad = (n: number) => String(n).padStart(2, "0");
const iso = (y: number, m: number, d: number) => `${y}-${pad(m + 1)}-${pad(d)}`;

function kstToday() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}
function addDays(isoDate: string, days: number) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + days));
  return iso(t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate());
}

/**
 * Native date input (typing and labels keep working) plus a calendar popover
 * that opens below the field, aligned to its right edge.
 */
export function DateField({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const today = kstToday();
  const base = /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : today;
  const [view, setView] = useState(() => ({
    y: Number(base.slice(0, 4)),
    m: Number(base.slice(5, 7)) - 1,
  }));
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  function toggle() {
    if (!open)
      setView({ y: Number(base.slice(0, 4)), m: Number(base.slice(5, 7)) - 1 });
    setOpen(!open);
  }
  function pick(date: string) {
    onChange(date);
    setOpen(false);
    trigger.current?.focus();
  }
  function shift(delta: number) {
    const t = new Date(Date.UTC(view.y, view.m + delta, 1));
    setView({ y: t.getUTCFullYear(), m: t.getUTCMonth() });
  }

  const lead = new Date(Date.UTC(view.y, view.m, 1)).getUTCDay();
  const days = new Date(Date.UTC(view.y, view.m + 1, 0)).getUTCDate();
  const tomorrow = addDays(today, 1);

  return (
    <div className="datefield" ref={root}>
      <input
        id={id}
        type="date"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
      />
      <button
        type="button"
        ref={trigger}
        className="datefield-trigger"
        aria-label="달력 열기"
        aria-expanded={open}
        aria-controls={`${id}-calendar`}
        onClick={toggle}
        disabled={disabled}
      >
        <CalendarDays size={20} aria-hidden="true" />
      </button>
      {open && (
        <div
          id={`${id}-calendar`}
          className="datefield-pop"
          role="dialog"
          aria-label="날짜 선택"
        >
          <div className="datefield-head">
            <strong>
              {view.y}년 {view.m + 1}월
            </strong>
            <div>
              <button
                type="button"
                aria-label="이전 달"
                onClick={() => shift(-1)}
              >
                <ChevronLeft size={18} aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label="다음 달"
                onClick={() => shift(1)}
              >
                <ChevronRight size={18} aria-hidden="true" />
              </button>
            </div>
          </div>
          <div className="datefield-grid">
            {WEEKDAYS.map((w, i) => (
              <span
                key={w}
                className={`datefield-wd ${i === 0 ? "is-sun" : ""}`}
                aria-hidden="true"
              >
                {w}
              </span>
            ))}
            {Array.from({ length: lead }, (_, i) => (
              <span key={`b${i}`} aria-hidden="true" />
            ))}
            {Array.from({ length: days }, (_, i) => {
              const d = iso(view.y, view.m, i + 1);
              const selected = d === value;
              return (
                <button
                  key={d}
                  type="button"
                  className={[
                    "datefield-day",
                    selected && "is-selected",
                    d === today && "is-today",
                    (lead + i) % 7 === 0 && "is-sun",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  aria-pressed={selected}
                  aria-label={`${view.m + 1}월 ${i + 1}일${d === today ? " 오늘" : ""}`}
                  onClick={() => pick(d)}
                >
                  {i + 1}
                </button>
              );
            })}
          </div>
          <div className="datefield-quick">
            <button type="button" onClick={() => pick(today)}>
              오늘
            </button>
            <button type="button" onClick={() => pick(tomorrow)}>
              내일
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
