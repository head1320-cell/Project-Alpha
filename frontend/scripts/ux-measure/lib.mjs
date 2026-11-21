// UI/UX 재기 스크립트의 공용 배관 — 주소 · 로그인 · 브라우저 · 맥락. ★재는 논리는 스크립트마다 따로 있다★(여기는 배관뿐).
// 쓰는 법 · 환경변수 · 한계는 같은 폴더의 README.md.
import { existsSync } from "node:fs";
import { chromium } from "@playwright/test";

/** 재는 대상 — 이미 떠 있는 화면 서버(`next start`)의 주소. 스크립트는 서버를 띄우지 않는다. */
export const BASE = (process.env.UX_BASE_URL || "http://localhost:3000").replace(/\/+$/, "");
// 로컬 mock 서버의 기본 계정이다(`KIS_USE_MOCK=1` 로 띄운 개발 서버 — e2e 와 같은 고정물). 다른 서버를 잴 때는 환경변수로 준다.
const USER = process.env.UX_USER || "admin";
const PASSWORD = process.env.UX_PASSWORD || "frm123!";
const TOKEN_KEY = "project-alpha.auth-token";
// playwright.config.ts 와 같은 규칙 — 샌드박스에 깔린 브라우저가 있으면 그것을, 아니면 Playwright 가 깐 것을 쓴다.
const SANDBOX_CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

/** e2e 의 도우미(대비 검사 · 끝난 백테스트 실행의 모의 응답)를 그대로 쓴다 — 재기와 시험이 같은 자로 잰다. Node 의 타입 벗기기로 .ts 를 바로 읽는다(Node 22.18 이상). */
export const H = await import(new URL("../../e2e/helpers.ts", import.meta.url).href);

/** 첫 인자(결과 자리)를 읽는다. 없으면 쓰는 법을 찍고 끝낸다. */
export function outArg(usage) {
  const out = process.argv[2];
  if (!out || out.startsWith("-")) {
    console.error(usage);
    process.exit(2);
  }
  return out;
}

export async function launch() {
  const exe = process.env.PW_CHROMIUM_PATH || (existsSync(SANDBOX_CHROMIUM) ? SANDBOX_CHROMIUM : undefined);
  return chromium.launch(exe ? { executablePath: exe } : {});
}

/** 로그인해 토큰을 돌려준다. ★토큰 · 응답 몸은 어디에도 찍지 않는다★ — 실패하면 상태 코드만 말한다. */
export async function login(browser) {
  const ctx = await browser.newContext();
  try {
    const r = await ctx.request.post(`${BASE}/api/backend/api/v1/auth/login`, { data: { username: USER, password: PASSWORD } });
    if (!r.ok()) throw new Error(`로그인 실패(상태 ${r.status()}) — 서버가 떠 있는지, UX_USER · UX_PASSWORD 가 맞는지 확인하세요`);
    const token = (await r.json()).access_token;
    if (!token) throw new Error("로그인 응답에 토큰이 없습니다");
    return token;
  } finally {
    await ctx.close();
  }
}

/** 새 브라우저 맥락 — 토큰(있으면)과 테마를 첫 그림 전에 심는다. `theme: null` 이면 테마를 건드리지 않는다. */
export async function context(browser, { token = null, theme = "light", viewport = { width: 1440, height: 900 }, ...rest } = {}) {
  const ctx = await browser.newContext({ viewport, ...rest });
  await ctx.addInitScript(([k, t, th]) => {
    try {
      if (t) localStorage.setItem(k, t);
      if (th) localStorage.setItem("alpha_theme", th);
    } catch {}
  }, [TOKEN_KEY, token, theme]);
  return ctx;
}

/** 화면을 열고 잠잠해질 때까지 기다린다(네트워크가 끝나지 않는 화면은 20초 뒤 그대로 잰다). */
export async function open(page, route, waitMs = 900) {
  await page.goto(BASE + route, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(waitMs);
}
