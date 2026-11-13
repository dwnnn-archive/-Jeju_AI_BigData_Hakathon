// Measures local DOM click -> committed heading -> next animation frame; not physical input latency.
import { chromium } from "@playwright/test";
import { existsSync } from "node:fs";
const browser = await chromium.launch({
  executablePath: existsSync("/usr/bin/chromium")
    ? "/usr/bin/chromium"
    : undefined,
  args: ["--no-sandbox"],
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  await page.goto(process.env.PREVIEW_URL || "http://127.0.0.1:5173");
  await page.getByRole("button", { name: "분석 요청", exact: true }).click();
  await page.getByText("계산 완료 · 검토 필요", { exact: true }).waitFor();
  await page.locator(".recharts-wrapper").waitFor();
  const timings = [];
  for (let i = 0; i < 30; i++) {
    const target = ["자원 배분", "승인 관리", "발전량 예측"][i % 3];
    timings.push(
      await page.evaluate(
        (label) =>
          new Promise((resolve) => {
            const started = performance.now();
            const observer = new MutationObserver(() => {
              if (document.querySelector("h1")?.textContent === label) {
                observer.disconnect();
                requestAnimationFrame(() =>
                  resolve(performance.now() - started),
                );
              }
            });
            observer.observe(document.querySelector("main"), {
              subtree: true,
              childList: true,
              characterData: true,
            });
            [...document.querySelectorAll("nav button")]
              .find((button) => button.textContent === label)
              .click();
          }),
        target,
      ),
    );
  }
  timings.sort((a, b) => a - b);
  console.log(
    JSON.stringify(
      {
        measurement:
          "local headless Chromium, DOM click to heading commit + next frame, loaded result",
        samples: timings.length,
        median_ms: +timings[15].toFixed(2),
        p95_ms: +timings[28].toFixed(2),
        max_ms: +timings[29].toFixed(2),
        physical_input_latency_included: false,
      },
      null,
      2,
    ),
  );
} finally {
  await browser.close();
}
