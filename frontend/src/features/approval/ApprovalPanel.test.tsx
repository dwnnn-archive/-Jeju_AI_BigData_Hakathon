import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { runFixture } from "../../test/fixtures";
import { ApprovalPanel } from "./ApprovalPanel";

it("requires a new review when the result identity changes in an open dialog", () => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  const onDecide = vi.fn().mockResolvedValue(undefined);
  const props = {
    run: runFixture(),
    transport: "confirmed" as const,
    matches: true,
    busy: false,
    onDecide,
  };
  const { rerender } = render(<ApprovalPanel {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "시연 승인 검토" }));
  fireEvent.change(screen.getByLabelText("검토 사유"), {
    target: { value: "확인했습니다" },
  });
  fireEvent.change(screen.getByLabelText("담당자 인증 토큰"), {
    target: { value: "test-only" },
  });
  fireEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "시연 승인 기록" })).toBeEnabled();
  rerender(
    <ApprovalPanel
      {...props}
      run={runFixture({ result_token: "b".repeat(64) })}
    />,
  );
  expect(screen.getByRole("button", { name: "시연 승인 기록" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "시연 승인 기록" }));
  expect(onDecide).not.toHaveBeenCalled();
});
