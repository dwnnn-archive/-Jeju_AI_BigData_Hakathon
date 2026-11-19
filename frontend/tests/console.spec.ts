import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { runFixture } from "../src/test/fixtures";

async function analyze(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await page.getByLabel("시연 데이터").check({ force: true }); // 기본은 외부 데이터
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "계산 완료 · 통보문 확인 대기",
  );
}

test("real API: empty → result → draft on demand → AI rewrite, with keyboard and accessibility", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await page.getByLabel("시연 데이터").check({ force: true }); // 기본은 외부 데이터
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "분석 요청 전",
  );
  await expect(page.getByText("230.0", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "계산 완료 · 통보문 확인 대기",
  );
  await expect(
    page.getByRole("img", { name: /시간별 발전량과 수요/ }),
  ).toBeVisible();
  await page.screenshot({
    path: testInfo.outputPath("desktop-result.png"),
    fullPage: true,
  });
  const violations = (
    await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
      .analyze()
  ).violations;
  expect(violations).toEqual([]);
  await page.getByRole("button", { name: "통보문 확인", exact: true }).click();
  await expect(page.getByText("통보문 수신 대상")).toHaveCount(0);
  await page.getByRole("button", { name: "통보문 작성" }).click();
  await expect(page.getByText("통보문 수신 대상")).toBeVisible();
  await expect(page.getByText("문자 발송을 승인한 시민")).toBeVisible();
  await expect(
    page.getByText("관내 충전소 등 운영자 · 재생에너지 사업자"),
  ).toBeVisible();
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  // 담당자 확인: 로그인 없이 한 번 기록하고, 기록이 상태에 반영된다.
  await page.getByRole("button", { name: "확인했습니다" }).click();
  await expect(
    page.getByText("담당자 확인 완료", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "담당자 확인 완료",
  );
  await expect(page.getByRole("button", { name: "확인했습니다" })).toHaveCount(
    0,
  );
  // AI 키가 없는 환경: 새로 쓰기를 눌러도 기본 문안이며, 그 사실을 화면에 밝힌다.
  await page.getByRole("button", { name: /수정/ }).click();
  await expect(page.getByText(/AI 연결 키가 없어 기본 문안/)).toBeVisible({
    timeout: 15000,
  });
});

test("receipt delay and queue are never shown as running; only worker evidence starts running", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let state = runFixture({
    status: "queued",
    result: null,
    can_decide: false,
    started_at: null,
  });
  await page.route("**/api/v1/analyses", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    state = {
      ...state,
      id: route.request().headers()["idempotency-key"],
      request: route.request().postDataJSON(),
    };
    await gate;
    await route.fulfill({ status: 202, json: state });
  });
  await page.route("**/api/v1/analyses/*", (route) =>
    route.fulfill({
      json: { ...state, server_checked_at: new Date().toISOString() },
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await page.getByLabel("시연 데이터").check({ force: true }); // 기본은 외부 데이터
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toHaveText(
    "요청 전송 중",
  );
  await expect(
    page.getByRole("button", { name: "분석 요청", exact: true }),
  ).toBeDisabled();
  release();
  await expect(page.getByRole("status", { name: "분석 상태" })).toHaveText(
    "실행 대기 중",
  );
  state = {
    ...state,
    version: 2,
    status: "running",
    started_at: new Date().toISOString(),
    heartbeat_at: new Date().toISOString(),
    fresh_until_epoch: Date.now() / 1000 + 10,
  };
  await expect(page.getByRole("status", { name: "분석 상태" })).toHaveText(
    "분석 중",
  );
});

test("network loss blocks review and preserves the same request identity", async ({
  page,
}) => {
  await analyze(page);
  await page.getByRole("button", { name: "통보문 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "통보문 작성" })).toBeEnabled();
  await page.route("**/api/v1/analyses/*", (route) => route.abort());
  await page.getByRole("button", { name: "상태 확인", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toHaveText(
    "상태 확인 불가",
  );
  await expect(
    page.getByRole("button", { name: "통보문 작성" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "분석 요청", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "같은 요청으로 접수 확인", exact: true }),
  ).toBeVisible();
});

test("changed selection cannot draft a notice from the previous result", async ({
  page,
}) => {
  await analyze(page);
  await page.getByRole("button", { name: "통보문 확인", exact: true }).click();
  await page.getByRole("radio", { name: "한림", exact: true }).check();
  await expect(
    page.getByRole("button", { name: "통보문 작성" }),
  ).toBeDisabled();
  await page.getByRole("radio", { name: "제주 전체", exact: true }).check();
  await expect(page.getByRole("button", { name: "통보문 작성" })).toBeEnabled();
});

test("mobile result has no document overflow and navigation keeps the selected analysis", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await analyze(page);
  await expect(
    page.getByRole("img", { name: /시간별 발전량과 수요/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("mobile-result.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "자원 배분", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("자원 배분");
  await page.getByRole("button", { name: "통보문 확인", exact: true }).click();
  await expect(page.getByRole("button", { name: "통보문 작성" })).toBeEnabled();
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
});

test("history does not claim there are no records before the server responds", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/analyses?limit=30", async (route) => {
    await gate;
    await route.fulfill({ status: 503, json: { detail: "temporary failure" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await page.getByRole("button", { name: "분석 이력", exact: true }).click();
  await expect(page.getByText("이력을 확인하고 있습니다.")).toBeVisible();
  await expect(page.getByText("저장된 분석이 없습니다")).toHaveCount(0);
  release();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByText("저장된 분석이 없습니다")).toHaveCount(0);
});

test("intraday check button: normal day-ahead → 1st normal → 2nd critical → approval", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await page.getByLabel("시연 데이터").check({ force: true }); // 기본은 외부 데이터
  await page.getByLabel("당일 위험 전환").check({ force: true });
  await page.getByLabel("행원").check({ force: true }); // 다른 테스트와 기록이 섞이지 않게 한다
  const status = page.getByRole("status", { name: "분석 상태" });
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(status).toContainText("계산 완료", { timeout: 15000 });
  await expect(page.getByText("정상 범위").first()).toBeVisible();
  // 하루 업무 흐름: 하루 전 분석은 끝났고 1차 점검이 다음 단계다.
  const flow = page.getByRole("list", { name: "담당자 하루 업무 흐름" });
  await expect(flow.locator(".workday-step--current")).toContainText(
    "1차 점검",
  );

  const check = page.getByRole("button", { name: "당일 점검 요청" });
  await check.click();
  await expect(page.getByText("당일 1차 점검").first()).toBeVisible({
    timeout: 15000,
  });
  await expect(status).toContainText("계산 완료", { timeout: 15000 });
  await expect(flow.locator(".workday-step--current")).toContainText(
    "2차 점검",
  );

  await check.click();
  await expect(page.getByText("당일 2차 점검").first()).toBeVisible({
    timeout: 15000,
  });
  await expect(status).toContainText("통보문 확인 대기", { timeout: 15000 });
  await expect(flow.locator(".workday-step--current")).toContainText(
    "통보문 확인",
  );
  // 위험이 나온 뒤에는 점검 버튼이 사라진다.
  await expect(check).toHaveCount(0);
});

test("question panel: asks about the result and labels the answer source", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await page.getByLabel("시연 데이터").check({ force: true }); // 기본은 외부 데이터
  await page.getByLabel("한림").check({ force: true }); // 다른 테스트와 기록이 섞이지 않게 한다
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "계산 완료",
    { timeout: 15000 },
  );
  const panel = page.getByRole("region", { name: "결과에 대해 물어보기" });
  await expect(panel).toBeVisible();
  await panel
    .getByRole("textbox", { name: "질문" })
    .fill("배분은 어떻게 되나요?");
  await panel.getByRole("button", { name: "질문하기" }).click();
  // AI 키가 없는 환경이므로 기본 답변이고, 그 사실과 이유를 화면에 밝힌다.
  await expect(panel.getByText("기본 답변", { exact: true })).toBeVisible({
    timeout: 15000,
  });
  await expect(panel.getByText(/AI 연결 키가 없어/)).toBeVisible();
  await expect(panel.getByText(/수소 환산/)).toBeVisible();
});

test("external-data mode rejects dates outside tomorrow..day after with a clear popup", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  // 기본은 외부 데이터 모드이고 안내가 보인다.
  await expect(
    page.getByText("내일부터 모레까지 분석할 수 있습니다", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("단, 시연모드에는 날짜 제한이 없습니다"),
  ).toBeVisible();
  // 달력에서 오늘(과거 포함)은 회색으로 비활성화된다.
  await page.getByRole("button", { name: "달력 열기" }).click();
  await expect(
    page.getByRole("button", { name: /\(선택할 수 없음\)/ }).first(),
  ).toBeDisabled();
  await page.keyboard.press("Escape");
  // 직접 입력한 과거 날짜는 서버가 거절하고 작은 창으로 알린다.
  await page.locator("#date").fill("2026-01-05");
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  const popup = page.getByRole("dialog", {
    name: "분석할 수 없는 날짜입니다.",
  });
  await expect(popup).toBeVisible();
  await popup.getByRole("button", { name: "확인" }).click();
  await expect(popup).toHaveCount(0);
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "분석 요청 전",
  );
  // 시연 모드는 같은 날짜도 제한 없이 접수한다.
  await page.getByLabel("시연 데이터").check({ force: true });
  await page.locator("#date").fill("2026-01-05");
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "계산 완료",
    { timeout: 15000 },
  );
});
