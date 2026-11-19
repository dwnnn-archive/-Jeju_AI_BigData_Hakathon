import { z } from "zod";
import { chatSchema } from "../features/chat/types";
import { draftSchema } from "../features/approval/types";
import {
  runSchema,
  summarySchema,
  type AnalysisRequest,
} from "../features/analysis/types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
  }
}
const base = import.meta.env.VITE_API_BASE || "";
export function createApi(key: string) {
  async function request(
    path: string,
    init: RequestInit = {},
    approver?: string,
    timeoutMs = 8000,
  ): Promise<unknown> {
    let response: Response;
    try {
      response = await fetch(base + "/api/v1" + path, {
        ...init,
        cache: "no-store",
        signal: AbortSignal.timeout(timeoutMs),
        headers: {
          "Content-Type": "application/json",
          ...(key ? { "X-API-Key": key } : {}),
          ...(approver ? { "X-Approver-Token": approver } : {}),
          ...init.headers,
        },
      });
    } catch {
      throw new ApiError(
        "서버 응답을 확인하지 못했습니다. 요청이 접수됐을 수 있으므로 같은 분석 ID로 확인하세요.",
      );
    }
    if (!response.ok) {
      const messages: Record<number, string> = {
        401: "인증 정보를 확인하세요.",
        404: "해당 분석의 접수를 확인하지 못했습니다.",
        409: "현재 결과 또는 결정 조건이 변경되었습니다. 상태를 다시 확인하세요.",
        422: "요청 형식이 올바르지 않습니다.",
        503: "서버가 현재 요청을 처리할 수 없습니다.",
      };
      throw new ApiError(
        messages[response.status] || "서버 처리 결과를 확인하지 못했습니다.",
        response.status,
      );
    }
    try {
      return await response.json();
    } catch {
      throw new ApiError("서버 응답 형식을 확인할 수 없습니다.");
    }
  }
  function parseRun(data: unknown) {
    const parsed = runSchema.safeParse(data);
    if (!parsed.success)
      throw new ApiError("서버 상태의 필수 정보를 검증하지 못했습니다.");
    return parsed.data;
  }
  return {
    get: async (id: string) =>
      parseRun(await request("/analyses/" + encodeURIComponent(id))),
    submit: async (id: string, body: AnalysisRequest) =>
      parseRun(
        await request("/analyses", {
          method: "POST",
          headers: { "Idempotency-Key": id },
          body: JSON.stringify(body),
        }),
      ),
    // LLM이 도구를 고르며 여러 번 조회하므로 일반 요청보다 오래 기다린다.
    chat: async (id: string, message: string) => {
      const data = await request(
        "/analyses/" + encodeURIComponent(id) + "/chat",
        { method: "POST", body: JSON.stringify({ message }) },
        undefined,
        60000,
      );
      const parsed = chatSchema.safeParse(data);
      if (!parsed.success)
        throw new ApiError("질문 답변의 형식을 확인하지 못했습니다.");
      return parsed.data;
    },
    // AI가 통보문 문안을 새로 쓴다(저장된 분석은 바뀌지 않는다).
    regenerateDraft: async (id: string, previous?: string) => {
      const data = await request(
        "/analyses/" + encodeURIComponent(id) + "/draft",
        {
          method: "POST",
          body: JSON.stringify({ previous: previous ?? null }),
        },
        undefined,
        60000,
      );
      const parsed = draftSchema.safeParse(data);
      if (!parsed.success)
        throw new ApiError("통보문 응답의 형식을 확인하지 못했습니다.");
      return parsed.data;
    },
    checkLogin: async (approverId: string, token: string) => {
      try {
        const data = await request(
          "/auth/check",
          {
            method: "POST",
            body: JSON.stringify({ approver_id: approverId }),
          },
          token,
        );
        return z.object({ approver_id: z.string() }).parse(data).approver_id;
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 401)
          throw new ApiError(
            "담당자 ID 또는 인증 토큰이 올바르지 않습니다.",
            401,
          );
        if (cause instanceof ApiError && cause.status === 503)
          throw new ApiError(
            "서버에 승인 토큰(APPROVER_TOKEN)이 설정되지 않아 로그인할 수 없습니다.",
            503,
          );
        if (cause instanceof ApiError && cause.status === 404)
          throw new ApiError(
            "서버가 로그인 확인을 지원하지 않습니다. 백엔드를 최신 코드로 다시 실행하세요.",
            404,
          );
        throw cause;
      }
    },
    list: async () =>
      z.array(summarySchema).parse(await request("/analyses?limit=30")),
    decide: async (
      id: string,
      action: "approve" | "reject",
      reason: string,
      token: string,
      approver: string,
    ) =>
      parseRun(
        await request(
          "/analyses/" + id + "/decision",
          {
            method: "POST",
            body: JSON.stringify({ action, reason, result_token: token }),
          },
          approver,
        ),
      ),
  };
}
export type Api = ReturnType<typeof createApi>;
