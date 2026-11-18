import { z } from "zod";

/** /chat 응답. mode는 AI가 도구를 골라 답했는지(llm), 기본 답변(rules)인지 알려 준다. */
export const chatSchema = z.object({
  answer: z.string(),
  mode: z.enum(["llm", "rules"]),
  mode_reason: z.string().nullable().optional(),
  tools_used: z
    .array(
      z.object({ name: z.string(), input: z.record(z.string(), z.unknown()) }),
    )
    .default([]),
});
export type ChatAnswer = z.infer<typeof chatSchema>;
