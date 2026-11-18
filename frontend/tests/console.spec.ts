import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { runFixture } from "../src/test/fixtures";

async function analyze(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "계산 완료 · 검토 필요",
  );
}

test("real API: empty → result → review → mock notification, with keyboard and accessibility", async ({
  page,
}, testInfo) => {
  await page.goto("/");
  await page.getByRole("button", { name: "분석", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "분석 요청 전",
  );
  await expect(page.getByText("230.0", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "계산 완료 · 검토 필요",
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
  const open = page.getByRole("button", {
    name: "발송 확정",
    exact: true,
  });
  await open.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(open).toBeFocused();
  await open.click();
  await page
    .getByLabel("검토 사유")
    .fill("시연 데이터와 배분 범위를 확인했습니다.");
  await page.getByLabel("담당자 인증 토큰").fill("local-review-test");
  await page.getByRole("checkbox").check();
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "발송 확정 기록", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("status", { name: "분석 상태" })).toContainText(
    "발송 확정됨",
  );
  await expect(
    page.getByText("시연 발송 처리 완료", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "알림 상태이며, 저장·출력제한 등 설비 동작의 완료를 뜻하지 않습니다.",
    ),
  ).toBeVisible();
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
  await expect(
    page.getByRole("button", { name: "발송 확정", exact: true }),
  ).toBeEnabled();
  await page.route("**/api/v1/analyses/*", (route) => route.abort());
  await page.getByRole("button", { name: "상태 확인", exact: true }).click();
  await expect(page.getByRole("status", { name: "분석 상태" })).toHaveText(
    "상태 확인 불가",
  );
  await expect(
    page.getByRole("button", { name: "발송 확정", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "분석 요청", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "같은 요청으로 접수 확인", exact: true }),
  ).toBeVisible();
});

test("changed selection cannot approve the previous result, and unauthorized approval is not success", async ({
  page,
}) => {
  await analyze(page);
  await page.getByRole("button", { name: "통보문 확인", exact: true }).click();
  await page.getByRole("radio", { name: "한림", exact: true }).check();
  await expect(
    page.getByRole("button", { name: "발송 확정", exact: true }),
  ).toBeDisabled();
  await page.getByRole("radio", { name: "제주 전체", exact: true }).check();
  await page.getByRole("button", { name: "발송 확정", exact: true }).click();
  await page.getByLabel("검토 사유").fill("인증 실패 확인");
  await page.getByLabel("담당자 인증 토큰").fill("wrong-token");
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "발송 확정 기록", exact: true })
    .click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "인증 정보를 확인하세요.",
  );
  await expect(
    page.getByText("발송 결정 기록: 확정", { exact: true }),
  ).toHaveCount(0);
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
  await expect(
    page.getByRole("button", { name: "발송 확정", exact: true }),
  ).toBeEnabled();
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
  await expect(status).toContainText("검토 필요", { timeout: 15000 });
  await expect(flow.locator(".workday-step--current")).toContainText(
    "통보문 확인",
  );
  // 위험이 나온 뒤에는 점검 버튼이 사라진다.
  await expect(check).toHaveCount(0);
});
