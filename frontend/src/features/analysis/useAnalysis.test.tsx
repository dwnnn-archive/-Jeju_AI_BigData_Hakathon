import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Api } from "../../api/client";
import { runFixture } from "../../test/fixtures";
import { useAnalysis } from "./useAnalysis";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (cause: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function apiMock(): Api {
  return { get: vi.fn(), submit: vi.fn(), decide: vi.fn(), list: vi.fn() };
}
function visibility(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: hidden,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}
beforeEach(() => {
  sessionStorage.clear();
  visibility(false);
});

describe("confirmed execution state", () => {
  it("does not claim running while receipt is unresolved; retries reuse the ID", async () => {
    const receipt = deferred<ReturnType<typeof runFixture>>();
    const api = apiMock();
    vi.mocked(api.submit)
      .mockReturnValueOnce(receipt.promise)
      .mockImplementation(async (id) =>
        runFixture({ id, status: "queued", result: null, can_decide: false }),
      );
    vi.mocked(api.get).mockRejectedValue(new Error("response lost"));
    const { result } = renderHook(() => useAnalysis(api));
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.submit(runFixture().request);
    });
    expect(result.current.transport).toBe("sending");
    expect(result.current.run).toBeNull();
    await act(async () => {
      receipt.reject(new Error("response lost"));
      await pending;
    });
    await waitFor(() => expect(result.current.transport).toBe("unknown"));
    const firstId = vi.mocked(api.submit).mock.calls[0][0];
    await act(async () => {
      await result.current.retrySame();
    });
    expect(vi.mocked(api.submit).mock.calls[1][0]).toBe(firstId);
  });

  it("serializes polls and discards a response started before tab visibility changed", async () => {
    const first = deferred<ReturnType<typeof runFixture>>();
    const second = deferred<ReturnType<typeof runFixture>>();
    const api = apiMock();
    vi.mocked(api.get)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useAnalysis(api));
    act(() => result.current.select(runFixture().id, runFixture().request));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    act(() => {
      visibility(true);
      visibility(false);
    });
    expect(api.get).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve(runFixture()));
    expect(result.current.transport).not.toBe("confirmed");
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    await act(async () =>
      second.resolve(
        runFixture({ can_decide: false, decision_blocks: ["superseded"] }),
      ),
    );
    expect(result.current.run?.can_decide).toBe(false);
    expect(result.current.transport).toBe("confirmed");
  });

  it("does not apply an old result after selecting another analysis", async () => {
    const old = deferred<ReturnType<typeof runFixture>>();
    const other = runFixture({ id: "00000000-0000-4000-8000-000000000002" });
    const api = apiMock();
    vi.mocked(api.get)
      .mockReturnValueOnce(old.promise)
      .mockResolvedValue(other);
    const { result } = renderHook(() => useAnalysis(api));
    act(() => result.current.select(runFixture().id, runFixture().request));
    act(() => result.current.select(other.id, other.request));
    await waitFor(() => expect(result.current.run?.id).toBe(other.id));
    await act(async () => old.resolve(runFixture()));
    expect(result.current.run?.id).toBe(other.id);
  });
});

it("treats a confirmed expired result as known, while disabling review", async () => {
  const api = apiMock();
  vi.mocked(api.get).mockResolvedValue(
    runFixture({
      expires_at: "2000-01-01T00:00:00+00:00",
      can_decide: false,
      decision_blocks: ["result_expired"],
    }),
  );
  const { result } = renderHook(() => useAnalysis(api));
  act(() => result.current.select(runFixture().id, runFixture().request));
  await waitFor(() => expect(result.current.run).not.toBeNull());
  expect(result.current.transport).toBe("confirmed");
  expect(result.current.run?.can_decide).toBe(false);
});
