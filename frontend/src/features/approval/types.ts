import { z } from "zod";

/** /draft 응답. mode는 AI가 새로 썼는지(llm), 기본 문안을 썼는지(template) 알려 준다. */
export const draftSchema = z.object({
  draft: z.string(),
  mode: z.enum(["llm", "template"]),
  mode_reason: z.string().nullable().optional(),
});
export type DraftAnswer = z.infer<typeof draftSchema>;
