import { useEffect, useRef, useState } from "react";
import { MessageCircle, Search, Sparkles } from "lucide-react";
import { Button } from "../../components/Button";
import type { AnalysisRun } from "../analysis/types";
import type { ChatAnswer } from "./types";

const toolLabels: Record<string, string> = {
  get_risk_summary: "위험 판정",
  get_hourly_forecast: "시간별 예측",
  get_allocation: "자원 배분",
  get_ev_stations: "충전소",
  get_data_sources: "데이터 출처",
  get_review_status: "검토 상태",
};
const reasonLabels: Record<string, string> = {
  no_key: "AI 연결 키가 없어 기본 답변을 사용했습니다.",
  unfaithful:
    "AI 답변의 숫자를 조회 결과와 맞출 수 없어 기본 답변을 사용했습니다.",
  no_tool_used: "AI가 근거를 조회하지 않아 기본 답변을 사용했습니다.",
  too_long: "AI 답변이 길어 기본 답변을 사용했습니다.",
};
const suggestions = [
  "내일 위험한가요? 몇 시가 가장 문제인가요?",
  "남는 전기는 어디로 얼마나 보내나요?",
  "어느 충전소가 좋을까요?",
  "이 결과는 실제 데이터인가요?",
];

type Item = { question: string; answer?: ChatAnswer; error?: string };

function reasonText(reason?: string | null) {
  if (!reason) return "기본 답변을 사용했습니다.";
  if (reasonLabels[reason]) return reasonLabels[reason];
  if (reason.startsWith("error:"))
    return "AI 호출에 실패해 기본 답변을 사용했습니다.";
  return "AI 답변을 쓸 수 없어 기본 답변을 사용했습니다.";
}

/** 결과에 대한 질문. AI가 읽기 전용 도구를 골라 조회한 근거로 답하고, 승인·발송은 하지 못한다. */
export function ChatPanel({
  run,
  ask,
}: {
  run: AnalysisRun | null;
  ask: (id: string, message: string) => Promise<ChatAnswer>;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const runId = run?.id;
  const tail = useRef<HTMLDivElement>(null);
  // 다른 분석을 보면 이전 대화를 이어 보이지 않는다.
  useEffect(() => {
    setItems([]);
    setText("");
  }, [runId]);
  useEffect(() => {
    tail.current?.scrollIntoView?.({ block: "nearest" });
  }, [items]);
  if (!run?.result) return null;

  async function send(question: string) {
    const value = question.trim();
    if (!value || busy || !run) return;
    setBusy(true);
    setText("");
    setItems((list) => [...list, { question: value }]);
    const id = run.id;
    try {
      const answer = await ask(id, value);
      setItems((list) =>
        list.map((item, i) =>
          i === list.length - 1 ? { ...item, answer } : item,
        ),
      );
    } catch (cause) {
      const error =
        cause instanceof Error ? cause.message : "답변을 받지 못했습니다.";
      setItems((list) =>
        list.map((item, i) =>
          i === list.length - 1 ? { ...item, error } : item,
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="chat" aria-labelledby="chat-title">
      <header className="chat-head">
        <MessageCircle size={20} aria-hidden="true" />
        <div>
          <h2 id="chat-title">결과에 대해 물어보기</h2>
          <p>
            AI가 이 분석의 조회 결과를 근거로 답합니다. 숫자는 조회한 값만 쓰며,
            승인·발송은 할 수 없습니다.
          </p>
        </div>
      </header>
      <div className="chat-suggest" aria-label="질문 예시">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            disabled={busy}
            onClick={() => void send(s)}
          >
            {s}
          </button>
        ))}
      </div>
      <div className="chat-log" aria-live="polite">
        {items.map((item, i) => (
          <div className="chat-turn" key={i}>
            <p className="chat-q">{item.question}</p>
            {item.answer ? (
              <div className="chat-a">
                <p>{item.answer.answer}</p>
                {item.answer.mode === "llm" ? (
                  <p className="chat-meta">
                    <span className="chat-badge chat-badge--ai">
                      <Sparkles size={12} aria-hidden="true" />
                      AI 답변
                    </span>
                    <span className="chat-tools">
                      <Search size={12} aria-hidden="true" />
                      조회:{" "}
                      {[...new Set(item.answer.tools_used.map((t) => t.name))]
                        .map((n) => toolLabels[n] || n)
                        .join(" · ")}
                    </span>
                  </p>
                ) : (
                  <p className="chat-meta">
                    <span className="chat-badge">기본 답변</span>
                    <span>{reasonText(item.answer.mode_reason)}</span>
                  </p>
                )}
              </div>
            ) : item.error ? (
              <p role="alert" className="chat-a chat-a--error">
                {item.error}
              </p>
            ) : (
              <p className="chat-a chat-a--wait" role="status">
                AI가 근거를 조회하는 중입니다. 최대 20초 정도 걸립니다.
              </p>
            )}
          </div>
        ))}
        <div ref={tail} />
      </div>
      <form
        className="chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          void send(text);
        }}
      >
        <label htmlFor="chat-input" className="sr-only">
          질문
        </label>
        <input
          id="chat-input"
          type="text"
          value={text}
          maxLength={500}
          placeholder="예: 12시 발전량과 수요는 얼마인가요?"
          onChange={(event) => setText(event.target.value)}
        />
        <Button type="submit" busy={busy} disabled={!text.trim()}>
          질문하기
        </Button>
      </form>
    </section>
  );
}
