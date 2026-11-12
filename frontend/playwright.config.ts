import { existsSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

// E2E harness — drives the REAL Next.js frontend against the REAL FastAPI backend
// (main_api in KIS_USE_MOCK=1 mode, SQLite). This exercises real routes/components with
// deterministic mock data, so "zero 404 / zero console error" assertions are meaningful.
//
// `next start` requires a prior `next build`. In CI: build, then `playwright test`.
// Locally, servers already running are reused (reuseExistingServer).
// Use the sandbox's pre-installed chromium when present (local dev); otherwise let
// Playwright use the browser it installed (CI runs `playwright install chromium`).
const SANDBOX_CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const CHROMIUM =
  process.env.PW_CHROMIUM_PATH || (existsSync(SANDBOX_CHROMIUM) ? SANDBOX_CHROMIUM : undefined);

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: CHROMIUM ? { executablePath: CHROMIUM } : {},
    // 기본은 "캔버스 환영 줄을 이미 본 사람"(BN N2) — 첫 방문 화면은 그 테스트 묶음에서만 storageState 를 비워 확인한다.
    storageState: { cookies: [], origins: [{ origin: "http://localhost:3000", localStorage: [{ name: "alpha_pg_welcomed", value: "1" }] }] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // LIFECYCLE_MASTER_COLLECT=0 — 기동 때 KIS 마스터를 내려받지 않는다. 그 다운로드는 mock 모드에서도 실제 외부 호출이라
      // 네트워크가 열린 CI 에서만 성공해, 같은 E2E 가 "업종·지수 구성을 아는 서버"와 "모르는 서버"를 따로 봤다(2026-11-12 · CI 전용 실패 6건).
      command:
        "cd .. && KIS_USE_MOCK=1 LIFECYCLE_MASTER_COLLECT=0 DATABASE_URL=sqlite:////tmp/e2e_pw.db python3 -m uvicorn main_api:app --port 8000 --log-level warning",
      url: "http://localhost:8000/api/v1/macro/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "BACKEND_URL=http://localhost:8000 npx next start -p 3000",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
