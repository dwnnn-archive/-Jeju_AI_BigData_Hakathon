import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { runFixture } from "../../test/fixtures";
import { ApprovalPanel } from "./ApprovalPanel";

function setup(over: Record<string, unknown> = {}) {
  const regenerate = vi.fn().mockResolvedValue({
    draft: "AI 새 문안",
    mode: "llm",
    mode_reason: null,
  });
  const onRemeasure = vi.fn();
  const props = {
    run: runFixture(),
    transport: "confirmed" as const,
    matches: true,
    busy: false,
    onRemeasure,
    regenerate,
    ...over,
  };
  return {
    ...render(<ApprovalPanel {...props} />),
    regenerate,
    onRemeasure,
    props,
  };
}

it("shows no draft until 통보문 작성 is pressed, then lists the recipients", () => {
  setup();
  expect(screen.queryByText("통보문 수신 대상")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /통보문 작성/ }));
  expect(screen.getByText("통보문 수신 대상")).toBeInTheDocument();
  expect(screen.getByText("문자 발송을 승인한 시민")).toBeInTheDocument();
  expect(
    screen.getByText("관내 충전소 등 운영자 · 재생에너지 사업자"),
  ).toBeInTheDocument();
});

it("replaces the draft with the AI rewrite and says where it came from", async () => {
  const { regenerate } = setup();
  fireEvent.click(screen.getByRole("button", { name: /통보문 작성/ }));
  fireEvent.click(screen.getByRole("button", { name: /수정/ }));
  await waitFor(() =>
    expect(screen.getByText(/AI 새 문안/)).toBeInTheDocument(),
  );
  expect(regenerate).toHaveBeenCalledOnce();
  expect(screen.getByText(/AI가 새로 쓴 문안/)).toBeInTheDocument();
});

it("tells the officer when the AI could not write and the default text is shown", async () => {
  const { regenerate } = setup();
  regenerate.mockResolvedValue({
    draft: "기본 문안",
    mode: "template",
    mode_reason: "no_key",
  });
  fireEvent.click(screen.getByRole("button", { name: /통보문 작성/ }));
  fireEvent.click(screen.getByRole("button", { name: /수정/ }));
  await waitFor(() =>
    expect(screen.getByText(/AI 연결 키가 없어 기본 문안/)).toBeVisible(),
  );
});

it("re-measure calls back, and drafting is blocked while the server state is unconfirmed", () => {
  const { onRemeasure, rerender, props } = setup();
  fireEvent.click(screen.getByRole("button", { name: /재측정/ }));
  expect(onRemeasure).toHaveBeenCalledOnce();
  rerender(<ApprovalPanel {...props} transport="unknown" />);
  expect(screen.getByRole("button", { name: /통보문 작성/ })).toBeDisabled();
});

it("records the officer's confirmation once, without login, and then shows the record", async () => {
  const onConfirm = vi.fn().mockResolvedValue(undefined);
  const { rerender, props } = setup({ onConfirm });
  fireEvent.click(screen.getByRole("button", { name: /통보문 작성/ }));
  expect(screen.getByText("담당자 확인")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "확인했습니다" }));
  await waitFor(() => expect(onConfirm).toHaveBeenCalledOnce());
  // 서버 기록이 반영되면 버튼 대신 확인 기록이 보인다
  rerender(
    <ApprovalPanel
      {...props}
      onConfirm={onConfirm}
      run={runFixture({
        confirmation: { confirmed_at: "2026-11-20T03:12:00+09:00" },
      })}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /통보문 작성/ }));
  expect(screen.getByText("담당자 확인 완료")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "확인했습니다" }),
  ).not.toBeInTheDocument();
});

it("shows an error when the confirmation could not be recorded", async () => {
  const onConfirm = vi.fn().mockRejectedValue(new Error("기록 실패"));
  setup({ onConfirm });
  fireEvent.click(screen.getByRole("button", { name: /통보문 작성/ }));
  fireEvent.click(screen.getByRole("button", { name: "확인했습니다" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("기록 실패"),
  );
});
