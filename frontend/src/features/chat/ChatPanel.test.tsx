import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { runFixture } from "../../test/fixtures";
import { ChatPanel } from "./ChatPanel";
import type { ChatAnswer } from "./types";

const llm: ChatAnswer = {
  answer: "내일은 위험 등급이고 피크 잉여전력은 230.0 MWh입니다.",
  mode: "llm",
  mode_reason: null,
  tools_used: [
    { name: "get_risk_summary", input: {} },
    { name: "get_risk_summary", input: {} },
    { name: "get_data_sources", input: {} },
  ],
};

it("shows nothing until there is a result", () => {
  const { container } = render(
    <ChatPanel run={runFixture({ result: null })} ask={vi.fn()} />,
  );
  expect(container).toBeEmptyDOMElement();
});

it("sends the question, shows the answer with the tools it looked up", async () => {
  const ask = vi.fn().mockResolvedValue(llm);
  render(<ChatPanel run={runFixture()} ask={ask} />);
  fireEvent.change(screen.getByLabelText("질문"), {
    target: { value: "내일 위험한가요?" },
  });
  fireEvent.click(screen.getByRole("button", { name: "질문하기" }));
  expect(ask).toHaveBeenCalledWith(runFixture().id, "내일 위험한가요?");
  expect(await screen.findByText(llm.answer)).toBeInTheDocument();
  expect(screen.getByText("AI 답변")).toBeInTheDocument();
  // 같은 도구는 한 번만 표시한다
  expect(
    screen.getByText(/조회:\s*위험 판정 · 데이터 출처/),
  ).toBeInTheDocument();
});

it("labels a rule-based answer and says why AI was not used", async () => {
  const ask = vi.fn().mockResolvedValue({
    answer: "2026-11-14 피크 잉여전력 230.00 MWh.",
    mode: "rules",
    mode_reason: "no_key",
    tools_used: [],
  });
  render(<ChatPanel run={runFixture()} ask={ask} />);
  fireEvent.click(
    screen.getByRole("button", { name: /어느 충전소가 좋을까요/ }),
  );
  expect(await screen.findByText("기본 답변")).toBeInTheDocument();
  expect(screen.getByText(/AI 연결 키가 없어/)).toBeInTheDocument();
  expect(screen.queryByText("AI 답변")).not.toBeInTheDocument();
});

it("shows an error instead of an answer when the request fails", async () => {
  const ask = vi
    .fn()
    .mockRejectedValue(new Error("서버가 현재 요청을 처리할 수 없습니다."));
  render(<ChatPanel run={runFixture()} ask={ask} />);
  fireEvent.change(screen.getByLabelText("질문"), {
    target: { value: "질문" },
  });
  fireEvent.click(screen.getByRole("button", { name: "질문하기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "처리할 수 없습니다",
  );
});

it("does not allow a second question while one is waiting, and clears on another run", async () => {
  let resolve: (v: ChatAnswer) => void = () => {};
  const ask = vi
    .fn()
    .mockReturnValue(new Promise<ChatAnswer>((r) => (resolve = r)));
  const { rerender } = render(<ChatPanel run={runFixture()} ask={ask} />);
  fireEvent.change(screen.getByLabelText("질문"), {
    target: { value: "첫 질문" },
  });
  fireEvent.click(screen.getByRole("button", { name: "질문하기" }));
  expect(screen.getByRole("status")).toHaveTextContent("조회하는 중");
  fireEvent.click(
    screen.getByRole("button", { name: /이 결과는 실제 데이터인가요/ }),
  );
  expect(ask).toHaveBeenCalledTimes(1);
  resolve(llm);
  await waitFor(() => expect(screen.getByText(llm.answer)).toBeInTheDocument());
  rerender(
    <ChatPanel run={runFixture({ id: "other-run-id-0000" })} ask={ask} />,
  );
  expect(screen.queryByText("첫 질문")).not.toBeInTheDocument();
});
