import { randomBytes } from "node:crypto";
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

// 증권 계좌 금고 키(Fernet · url-safe base64 32바이트) — ★이 실행에서만 쓰는 값을 그때 만든다★(저장소에 키를 두지 않는다).
// `rule-arming.spec.ts` 가 실제 서버에 모의투자 계좌를 연결한다 — 키가 없으면 서버는 연결을 503 으로 거절한다.
// 합성 데이터 모드(`KIS_USE_MOCK=1`)라 연결한 계좌는 증권사에 닿지 않는다. 이미 떠 있는 서버를 다시 쓰는 로컬 실행에서는
// 그 서버를 띄울 때 `BROKER_CRED_KEY` 를 줘야 한다(안 주면 그 스펙이 첫 줄에서 그렇게 말하고 실패한다).
const VAULT_KEY = process.env.BROKER_CRED_KEY || randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_");

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
      // mock 서버는 외부로 나가지 않는다(2026-11-13 · `mock_gate.mock_allowed()`): 기동 때 KIS 마스터를 내려받지 않고 중앙은행 정책문도 수집하지 않는다.
      // 2026-11-12 에는 그 다운로드가 네트워크가 열린 CI 에서만 성공해 같은 E2E 가 "업종·지수 구성을 아는 서버"와 "모르는 서버"를 따로 봤고(CI 전용 실패 6건),
      // 그때는 여기서 `LIFECYCLE_MASTER_COLLECT=0` 으로 막았다. ★지금은 그 스위치를 일부러 주지 않는다★ — 제품 기본 동작이 막는지를 CI E2E 가 본다.
      command:
        // `MINUTE_BARS_DIR` — 분봉 백테스트 스펙이 심는 분봉의 자리(`e2e/intraday.spec.ts` · `e2e/fixtures/intraday/seed_bars.py`). 저장소 밖이라 작업 트리에 파일이 남지 않는다.
        `cd .. && KIS_USE_MOCK=1 BROKER_CRED_KEY=${VAULT_KEY} MINUTE_BARS_DIR=/tmp/e2e_minute_bars DATABASE_URL=sqlite:////tmp/e2e_pw.db python3 -m uvicorn main_api:app --port 8000 --log-level warning`,
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
