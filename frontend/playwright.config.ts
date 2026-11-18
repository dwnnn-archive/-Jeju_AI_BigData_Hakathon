import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  // 서버를 막 켠 직후 첫 분석은 3~4초 걸린다.
  expect: { timeout: 15000 },
  use: {
    baseURL: "http://127.0.0.1:5173",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    launchOptions: {
      executablePath: existsSync("/usr/bin/chromium")
        ? "/usr/bin/chromium"
        : undefined,
      args: ["--no-sandbox"],
    },
  },
  webServer: [
    {
      command:
        "cd ../backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/health",
      env: {
        // 실행마다 새 DB를 쓴다(당일 점검 횟수 한도 등 이전 실행의 기록이 남지 않게).
        DATABASE_PATH: `/tmp/jeju-playwright-${Date.now()}.sqlite`,
        APPROVER_TOKEN: "local-review-test",
        // 실제 AI를 호출하지 않는다(비용·결과 변동 방지). 질문은 기본 답변 경로로 확인한다.
        ANTHROPIC_API_KEY: "",
        // 수집해 둔 실제 충전소 파일이 e2e 결과를 바꾸지 않게 한다.
        EV_SNAPSHOT_PATH: "/tmp/jeju-playwright-no-ev.json",
        EV_PROFILE_PATH: "/tmp/jeju-playwright-no-ev-profile.json",
      },
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
    },
  ],
});
