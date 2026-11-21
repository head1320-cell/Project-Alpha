import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { test, expect, type Page } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 판 배치(G6 2a-1 · 작업 공간 2단계) — 백테스트 › 분봉 규칙 (설계 `docs/superpowers/specs/2026-11-19-workspace-panels-design.md` · 계획 §9 · ★실제 서버★)
// ────────────────────────────────────────────────────────────────────────────
// 이 파일의 첫 묶음은 ★판 배치를 끈 화면이 G6 전과 같다★는 것을 건다 — 골든(`golden/intraday-dom.json`)은 G6 코드를 쓰기 전의 빌드에서 떴다
// (`UPDATE_WS_GOLDEN=1`). 뼈대는 깊이를 제한한 DOM(태그 · 클래스 · 순서 · role · aria · data · style · 글 없음 · React id 는 나온 순서의 자리표)이고,
// 더한 것은 넓은 창의 '배치' 단추(`.ws-open`) 하나뿐이어야 한다. 깊은 내용은 기존 분봉 스펙 16 이 건다(한 줄도 고치지 않는다).
// 둘째 묶음부터는 판 배치를 켠 화면 — 판 여섯 · 탭 · 판 메뉴(키보드만) · 끌어 놓기(같은 함수) · ★배치 조작이 시행을 늘리지 않고 절을 다시 마운트하지
// 않는다★(POST 수 · GET /trials 의 runs 합 · DOM 노드 표식 · 절 안 입력) · 저장 · 깨진 저장 · 이름 붙인 배치 · 파일 · 좁은 창 쌓기 · 합쳐 보임 · 끄기.
// 데이터는 다른 분봉 스펙과 같은 고정물(seed_bars.py) — 손 계산 열흘 035720 · 합성 사흘 005930 · 000660.
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";
const HERE = "/backtest/intraday";
const GOLDEN = path.join(__dirname, "golden", "intraday-dom.json");
const HAND = { tickers: "035720", from: "2026-03-02", to: "2026-03-13" };
const SYNTH = { tickers: "005930, 000660", from: "2026-04-01", to: "2026-04-03" };
const WIDE = { width: 1440, height: 900 };
const HUGE = { width: 1920, height: 1080 };
const PHONE = { width: 390, height: 844 };
const WRITE = process.env.UPDATE_WS_GOLDEN === "1";
const K = { layout: "ws.intraday", on: "ws.intraday.on", saved: "ws.intraday.saved" };

type DomState = { skeleton: string[]; boxes?: Record<string, number[]> };
type DomGolden = { note: string; states: Record<string, DomState> };

test.beforeAll(() => {
  execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", "seed_bars.py")],
    { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
});

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

async function open(page: Page, viewport = WIDE): Promise<string> {
  await page.setViewportSize(viewport);
  const token = await login(page);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeAttached();
  return token;
}

/** 이 브라우저의 저장을 바꾸고 다시 연다(null = 지움). */
async function seed(page: Page, values: Record<string, string | null>): Promise<void> {
  await page.evaluate((v) => { for (const [k, x] of Object.entries(v)) { if (x === null) localStorage.removeItem(k); else localStorage.setItem(k, x); } }, values);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeAttached();
}

const stored = async (page: Page): Promise<unknown> => JSON.parse(await page.evaluate((k) => localStorage.getItem(k) ?? "null", K.layout));
const tab = (page: Page, id: string) => page.locator(`.ws-tab[data-tab="${id}"]`);
const panel = (page: Page, id: string) => page.locator(`.ws-panel[data-panel="${id}"]`);
const head = (page: Page, area: string) => page.locator(`.ws-head[data-area="${area}"]`);
const live = (page: Page) => page.locator(".ws-live");
const item = (page: Page, name: string | RegExp) => page.locator(".ws-menu").getByRole("menuitem", { name });
const radio = (page: Page, name: string) => page.locator(".ws-menu").getByRole("menuitemradio", { name });
const ids = (page: Page, area: string) => head(page, area).locator(".ws-tab").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.tab));

/** '배치' 메뉴에서 판 배치를 켠다(마우스) — 처음 배치는 '두 열'. */
async function wsOn(page: Page): Promise<void> {
  await page.locator(".ws-open").first().click();
  await radio(page, "판 배치").click();
  await expect(page.locator(".itd")).toHaveAttribute("data-ws", "tabs");
}

/** 칸 머리의 판 메뉴에서 한 항목(마우스). */
async function panelMenu(page: Page, area: string, name: string | RegExp, check = false): Promise<void> {
  await head(page, area).locator(".ws-menu-open").click();
  await (check ? page.locator(".ws-menu").getByRole("menuitemcheckbox", { name }) : item(page, name)).click();
}

/** 시행을 남기는 POST 를 센다(배치 조작이 시행을 늘리지 않는다는 것을 건다). */
function countPosts(page: Page): string[] {
  const posts: string[] = [];
  page.on("request", (r) => { if (r.method() === "POST" && /\/intraday\/(simulate|validate|divergence)/.test(r.url())) posts.push(r.url()); });
  return posts;
}

/** 내 시행들의 실행 횟수 합(서버 기록 — 읽기만). */
async function runsSum(page: Page, token: string): Promise<number> {
  const r = await page.request.get(`${API}/intraday/trials?limit=200`, { headers: { authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  const js = await r.json() as { trials: { runs: number }[] };
  return js.trials.reduce((s, t) => s + t.runs, 0);
}

async function setHand(page: Page): Promise<void> {
  await page.locator(".itd-tickers").fill(HAND.tickers);
  await page.locator(".itd-from").fill(HAND.from);
  await page.locator(".itd-to").fill(HAND.to);
  await field(page, "minutes").fill("1");
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);

async function setSynth(page: Page): Promise<void> {
  await page.locator(".itd-tickers").fill(SYNTH.tickers);
  await page.locator(".itd-from").fill(SYNTH.from);
  await page.locator(".itd-to").fill(SYNTH.to);
  await field(page, "minutes").fill("5");
  await field(page, "stop_pct").fill("0.4");
  await field(page, "target_pct").fill("0.8");
  await field(page, "commission_bp").fill("1.5");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
}

async function run(page: Page): Promise<void> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/simulate") && r.method() === "POST");
  await page.locator(".itd-run").click();
  await sent;
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 60_000 });
}

async function judge(page: Page): Promise<void> {
  const sent = page.waitForRequest((r) => r.url().includes("/intraday/validate") && r.method() === "POST");
  await page.locator(".itd-judge-btn").click();
  await sent;
  await expect(page.locator(".itd-verdict")).toBeVisible({ timeout: 60_000 });
}

/**
 * `.itd` 아래 DOM 의 뼈대. 깊이 3 까지(작업 칸 · 두 칸 · 칸의 절) + `.itd-out-bar` 는 끝까지. '배치' 단추(`.ws-open`)는 뺀다(더한 것 하나).
 * React id(useId)는 나온 순서의 자리표로 바꾼다 — 판 배치 코드가 훅을 더해 번호가 밀려도 뼈대는 같다.
 */
function skeleton(page: Page): Promise<string[]> {
  return page.locator(".itd").evaluate((root) => {
    const out: string[] = [];
    const ids = new Map<string, string>();
    const idOf = (v: string) => { if (!ids.has(v)) ids.set(v, `@${ids.size}`); return ids.get(v)!; };
    const REF = new Set(["id", "aria-labelledby", "aria-controls", "aria-describedby", "for", "aria-activedescendant"]);
    const KEEP = (n: string) => n === "role" || n === "hidden" || n === "tabindex" || n === "type" || n === "disabled" || n === "style" || n === "open" ||
      n.startsWith("aria-") || n.startsWith("data-");
    const walk = (el: Element, depth: number, deep: boolean) => {
      if (el.classList.contains("ws-open")) return;
      const attrs: string[] = [];
      for (const a of Array.from(el.attributes).sort((x, y) => x.name.localeCompare(y.name))) {
        if (a.name === "class") continue;
        if (REF.has(a.name)) {
          const fixed = a.value.split(/\s+/).map((v) => (/[«»:]/.test(v) ? idOf(v) : v)).join(" ");
          attrs.push(`${a.name}=${fixed}`);
        } else if (KEEP(a.name)) attrs.push(`${a.name}=${a.value}`);
      }
      const cls = Array.from(el.classList).join(".");
      out.push(`${"  ".repeat(depth)}${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""}${attrs.length ? ` [${attrs.join(" ")}]` : ""}`);
      const full = deep || el.classList.contains("itd-out-bar");
      if (depth >= 3 && !full) return;
      for (const c of Array.from(el.children)) walk(c, depth + 1, full);
    };
    walk(root, 0, false);
    return out;
  });
}

/** 판 배치를 끈 두 칸(1440 × 900)의 상자 — x · y · 폭 · 높이(정수 px). */
async function boxes(page: Page): Promise<Record<string, number[]>> {
  const out: Record<string, number[]> = {};
  for (const sel of [".itd-work", ".itd-set", ".itd-split-bar", ".itd-out", ".itd-out-bar", ".itd-set-toggle", ".itd-out-empty"]) {
    const b = await page.locator(sel).first().boundingBox();
    expect(b, sel).not.toBeNull();
    out[sel] = [b!.x, b!.y, b!.width, b!.height].map((v) => Math.round(v));
  }
  return out;
}

function readGolden(): DomGolden {
  return JSON.parse(fs.readFileSync(GOLDEN, "utf-8")) as DomGolden;
}

const written: Record<string, DomState> = {};
test.afterAll(() => {
  if (!WRITE || Object.keys(written).length === 0) return;
  const prev: DomGolden = fs.existsSync(GOLDEN) ? readGolden() : { note: "", states: {} };
  const next: DomGolden = {
    note: "판 배치(G6 2a-1)를 끈 분봉 화면의 DOM 뼈대 — G6 코드를 쓰기 전 빌드(c9f8318)에서 UPDATE_WS_GOLDEN=1 로 떴다. 더한 것은 '배치' 단추(.ws-open) 하나뿐이어야 한다.",
    states: { ...prev.states, ...written },
  };
  fs.writeFileSync(GOLDEN, `${JSON.stringify(next, null, 1)}\n`, "utf-8");
});

async function same(page: Page, name: string, withBoxes: boolean): Promise<void> {
  const got: DomState = { skeleton: await skeleton(page) };
  if (withBoxes) got.boxes = await boxes(page);
  if (WRITE) { written[name] = got; return; }
  const want = readGolden().states[name];
  expect(want, `골든에 ${name} 이 없습니다`).toBeTruthy();
  expect(got.skeleton.join("\n")).toBe(want.skeleton.join("\n"));
  if (want.boxes) {
    for (const [sel, b] of Object.entries(want.boxes)) {
      const g = got.boxes?.[sel];
      expect(g, sel).toBeTruthy();
      for (let i = 0; i < 4; i++) expect(Math.abs(g![i] - b[i]), `${sel}[${i}] ${JSON.stringify(g)} ↔ ${JSON.stringify(b)}`).toBeLessThanOrEqual(1);
    }
  }
}

test.describe("판 배치를 끈 화면은 G6 전과 같다(골든)", () => {
  test("1440 × 900 · 실행 전 · 뼈대와 상자", async ({ page }) => {
    await open(page);
    await expect(page.locator(".itd")).toHaveAttribute("data-split", "");
    await same(page, "1440-open", true);
  });

  test("1440 × 900 · 합성 실행 뒤 · 판정 뒤", async ({ page }) => {
    await open(page);
    await setSynth(page);
    await run(page);
    await same(page, "1440-run", false);
    await judge(page);
    await same(page, "1440-judge", false);
  });

  test("390 × 844 · 실행 전 · 한 열", async ({ page }) => {
    await open(page, PHONE);
    await expect(page.locator(".itd")).not.toHaveAttribute("data-split", /.*/);
    await same(page, "390-open", false);
  });
});

test("판 배치를 끈 넓은 창에는 '배치' 단추가 결과 칸 막대에 하나 · 한 열에는 없다", async ({ page }) => {
  test.skip(WRITE, "골든을 뜨는 돌림");
  await open(page);
  await expect(page.locator(".itd-out-bar .ws-open")).toHaveCount(1);
  await expect(page.locator(".ws-open")).toHaveCount(1);
  await expect(page.locator(".ws-open")).toHaveText("배치");
  await expect(page.locator(".ws-open")).toHaveAttribute("aria-haspopup", "menu");
  await expect(page.locator(".ws-open")).toHaveAttribute("aria-expanded", "false");
  await expect(page.locator(".ws, .ws-grid, .ws-panel, .ws-head, .ws-bar")).toHaveCount(0);
  await page.setViewportSize({ width: 1200, height: 900 });
  await expect(page.locator(".ws-open")).toHaveCount(0);
});

test.describe("판 배치를 켠 화면", () => {
  test.skip(WRITE, "골든을 뜨는 돌림");

  test("켜기: '배치' 메뉴(키보드 ↓ ↑ Home End Escape)에서 '판 배치' → 두 열 처음 배치 · 판 여섯 · 기존 두 칸 요소 없음 · 페이지는 구르지 않는다", async ({ page }) => {
    await open(page);
    const open_ = page.locator(".ws-open");
    await open_.focus();
    await page.keyboard.press("ArrowDown");
    await expect(open_).toHaveAttribute("aria-expanded", "true");
    const menu = page.locator(".ws-menu");
    await expect(menu).toHaveAttribute("role", "menu");
    await expect(radio(page, "기본 배치")).toBeFocused();
    await expect(radio(page, "기본 배치")).toHaveAttribute("aria-checked", "true");
    await expect(radio(page, "판 배치")).toHaveAttribute("aria-checked", "false");
    await page.keyboard.press("End");
    await expect(item(page, "배치 관리")).toBeFocused();
    await page.keyboard.press("Home");
    await expect(radio(page, "기본 배치")).toBeFocused();
    await page.keyboard.press("ArrowUp");                                              // 둘러 돈다
    await expect(item(page, "배치 관리")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);
    await expect(open_).toBeFocused();
    await expect(open_).toHaveAttribute("aria-expanded", "false");
    // Enter 로 열고 ↓ 한 번 → '판 배치' → Enter
    await page.keyboard.press("Enter");
    await expect(radio(page, "기본 배치")).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(radio(page, "판 배치")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "tabs");
    await expect(page.locator(".itd")).not.toHaveAttribute("data-split", /.*/);
    await expect(page.locator(".itd-work, .itd-split-bar, .itd-set-toggle")).toHaveCount(0);
    await expect(page.locator(".ws-panel")).toHaveCount(6);
    await expect(page.locator(".ws-head")).toHaveCount(2);
    expect(await ids(page, "0:0")).toEqual(["setup"]);
    expect(await ids(page, "1:0")).toEqual(["result", "bars", "verdict", "daytype", "regime"]);
    await expect(tab(page, "result")).toHaveAttribute("aria-selected", "true");
    await expect(panel(page, "result")).toBeVisible();
    for (const id of ["bars", "verdict", "daytype", "regime"]) await expect(panel(page, id)).toBeHidden();
    await expect(panel(page, "setup")).toHaveAttribute("role", "tabpanel");
    await expect(page.getByRole("tablist", { name: "첫째 열의 판" })).toBeVisible();
    expect(await page.evaluate((k) => localStorage.getItem(k), K.on)).toBe("1");
    expect(Math.round((await panel(page, "setup").boundingBox())!.width)).toBe(480);
    const main = await page.locator(".terminal-main").evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight }));
    expect(main.sh, JSON.stringify(main)).toBeLessThanOrEqual(main.ch + 1);
    await expect(page.locator(".ws-open")).toHaveCount(1);                             // 판 배치에서는 작업 공간 위 막대에
    await expect(page.locator(".ws-bar .ws-open")).toHaveCount(1);
  });

  test("탭: 누르기 · ← → Home End(둘러 돎) · 가려진 판은 hidden · Tab 은 가려진 판으로 가지 않는다 · 고른 탭은 저장에 남는다", async ({ page }) => {
    await open(page);
    await wsOn(page);
    await tab(page, "verdict").click();
    await expect(panel(page, "verdict")).toBeVisible();
    await expect(panel(page, "result")).toHaveAttribute("hidden", "");
    await expect(tab(page, "verdict")).toHaveAttribute("aria-selected", "true");
    await expect(tab(page, "result")).toHaveAttribute("tabindex", "-1");
    await page.keyboard.press("ArrowRight");
    await expect(tab(page, "daytype")).toBeFocused();
    await expect(panel(page, "daytype")).toBeVisible();
    await page.keyboard.press("Home");
    await expect(tab(page, "result")).toBeFocused();
    await page.keyboard.press("End");
    await expect(tab(page, "regime")).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(tab(page, "result")).toBeFocused();
    await page.keyboard.press("ArrowLeft");
    await expect(tab(page, "regime")).toBeFocused();
    expect(((await stored(page)) as { cols: { rows: { active: string }[] }[] }).cols[1].rows[0].active).toBe("regime");
    await expect(page.locator(".ws-note")).toHaveCount(0);                          // 저장이 되면 실패 글이 없다(저장 실패 시험의 짝)
    // Tab: 탭 목록 → 판 메뉴 단추 → 보이는 판(가려진 판의 단추로는 가지 않는다)
    await page.keyboard.press("Tab");
    await expect(head(page, "1:0").locator(".ws-menu-open")).toBeFocused();
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.closest(".ws-panel")?.getAttribute("data-panel") ?? null)).toBe("regime");
  });

  test("판 메뉴(키보드만): '판정'을 '새 열(오른쪽 끝)'로 → 셋째 열 · 앞 탭 · 낭독 · 초점은 그 판의 탭 · 저장 꼴", async ({ page }) => {
    await open(page, HUGE);
    await wsOn(page);
    await tab(page, "verdict").click();
    const btn = head(page, "1:0").locator(".ws-menu-open");
    await expect(btn).toHaveAccessibleName("‘판정’ 판 메뉴");
    await btn.focus();
    await page.keyboard.press("Enter");
    const names = await page.locator(".ws-menu [role^=menuitem]").evaluateAll((els) => els.map((e) => e.textContent?.trim()));
    expect(names).toEqual(["첫째 열", "새 열(왼쪽 끝)", "새 열(오른쪽 끝)", "이 열 위에 새 칸", "이 열 아래에 새 칸", "이 칸만 크게", "닫기"]);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");
    await expect(item(page, "새 열(오른쪽 끝)")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator(".ws-head")).toHaveCount(3);
    expect(await ids(page, "2:0")).toEqual(["verdict"]);
    await expect(tab(page, "verdict")).toHaveAttribute("aria-selected", "true");
    await expect(tab(page, "verdict")).toBeFocused();
    await expect(live(page)).toContainText("‘판정’ 판을 셋째 열로 옮겼습니다.");
    // 앞 탭(판정)을 옮겼으므로 떠난 칸은 그 자리의 이웃(하루 유형)이 앞 탭 — 순수 규칙(ws-layout '앞 탭을 옮기면 …')과 같은 꼴
    expect(await stored(page)).toEqual({ v: 1, screen: "intraday", closed: [], cols: [
      { w: 480, rows: [{ tabs: ["setup"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["result", "bars", "daytype", "regime"], active: "daytype" }] },
      { w: 480, rows: [{ tabs: ["verdict"], active: "verdict" }] },   // 새 열 폭 = max(판정 최소 폭 144, colNew 480)
    ] });
    await expect(tab(page, "daytype")).toHaveAttribute("aria-selected", "true");
  });

  test("끌어 놓기: 메뉴와 같은 저장 꼴 · 끄는 동안 놓일 자리가 그려진다 · Escape 로 취소", async ({ page }) => {
    await open(page, HUGE);
    await wsOn(page);
    const t = (await tab(page, "verdict").boundingBox())!;
    const col = (await panel(page, "result").boundingBox())!;
    await page.mouse.move(t.x + t.width / 2, t.y + t.height / 2);
    await page.mouse.down();
    await page.mouse.move(t.x + t.width / 2 + 3, t.y + t.height / 2);           // 4px 안: 아직 누르기
    await expect(page.locator(".ws-drop")).toHaveCount(0);
    await page.mouse.move(col.x + col.width - 6, col.y + col.height / 2, { steps: 6 });
    await expect(page.locator(".ws-drop")).toBeVisible();
    await expect(page.locator(".ws")).toHaveAttribute("data-dragging", "verdict");
    // 포인터 곁 글 = 판 메뉴의 옮기기 항목과 같은 말(놓을 자리가 보이지 않는 사용자도 끄는 동안 읽는다 · 낭독하지 않는 장식)
    const chip = page.locator(".ws-drag-chip");
    await expect(chip).toHaveText("판정 · 새 열(오른쪽 끝)");
    await expect(chip).toHaveAttribute("data-ok", "true");
    await expect(chip).toHaveAttribute("aria-hidden", "true");
    await page.mouse.up();
    await expect(page.locator(".ws-drop")).toHaveCount(0);
    await expect(chip).toHaveCount(0);
    expect(await stored(page)).toEqual({ v: 1, screen: "intraday", closed: [], cols: [
      { w: 480, rows: [{ tabs: ["setup"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["result", "bars", "daytype", "regime"], active: "result" }] },
      { w: 480, rows: [{ tabs: ["verdict"], active: "verdict" }] },   // 새 열 폭 = max(판정 최소 폭 144, colNew 480)
    ] });
    await expect(live(page)).toContainText("‘판정’ 판을 셋째 열로 옮겼습니다.");
    // Escape 취소
    const before = await stored(page);
    const d = (await tab(page, "daytype").boundingBox())!;
    const col2 = (await panel(page, "result").boundingBox())!;                     // 셋째 열이 생겨 둘째 열이 좁아졌다 — 다시 잰다
    await page.mouse.move(d.x + d.width / 2, d.y + d.height / 2);
    await page.mouse.down();
    // 셋째 열이 이미 있어 새 열은 놓을 수 없다 — 놓일 자리를 그리지 않고 글이 그렇게 말한다(겨눈 것이 새 열이라 다른 자리로 돌리지 않는다)
    await page.mouse.move(col2.x + col2.width - 6, col2.y + col2.height / 2, { steps: 6 });
    await expect(chip).toHaveText("하루 유형 · 놓을 수 없는 자리");
    await expect(chip).toHaveAttribute("data-ok", "false");
    await expect(page.locator(".ws-drop")).toHaveCount(0);
    await page.mouse.move(col2.x + col2.width / 2, col2.y + col2.height / 2, { steps: 6 });
    await expect(page.locator(".ws-drop")).toBeVisible();
    await expect(chip).toHaveAttribute("data-ok", "true");
    await page.keyboard.press("Escape");
    await expect(page.locator(".ws-drop")).toHaveCount(0);
    await expect(chip).toHaveCount(0);
    await page.mouse.up();
    expect(await stored(page)).toEqual(before);
    await expect(live(page)).toContainText("옮기기를 취소했습니다.");
  });

  test("★상태 보존★: 실행 · 판정 뒤 옮기고 · 닫고 · 다시 열고 · 쌓기를 오가도 POST 수 · 시행 수 불변 · 절의 DOM 노드와 입력이 그대로", async ({ page }) => {
    const token = await open(page, HUGE);
    await wsOn(page);
    const posts = countPosts(page);
    await setSynth(page);
    await run(page);
    await tab(page, "verdict").click();
    await judge(page);
    expect(posts.length).toBe(2);
    const runs0 = await runsSum(page, token);
    await tab(page, "daytype").click();
    await page.locator(".itd-dt-k").fill("4");
    await panel(page, "result").locator(".itd-result").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 1; });
    await panel(page, "daytype").locator(".itd-dt-k").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 2; });
    await panel(page, "verdict").locator(".itd-verdict").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 3; });
    // 옮기기(메뉴 · 새 열) · 옮기기(아래 칸) · 닫기 · 다시 열기 · 이 칸만 크게 · 쌓기 오가기 · 다시 옮기기
    await panelMenu(page, "1:0", "새 열(오른쪽 끝)");
    await expect(page.locator(".ws-head")).toHaveCount(3);
    await tab(page, "regime").click();
    await panelMenu(page, "1:0", "닫기");
    await page.locator(".ws-open").click();
    await item(page, "‘시장 국면’ 다시 열기").click();
    await tab(page, "verdict").click();
    await panelMenu(page, "1:0", "이 열 아래에 새 칸");
    await panelMenu(page, "2:0", "이 칸만 크게", true);
    await page.keyboard.press("Escape");
    await page.setViewportSize({ width: 1200, height: 900 });
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "stack");
    await page.setViewportSize(HUGE);
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "tabs");
    await tab(page, "bars").click();
    await tab(page, "result").click();
    // 확인
    expect(posts.length, posts.join("\n")).toBe(2);
    expect(await runsSum(page, token)).toBe(runs0);
    expect(await page.locator(".itd-result").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(1);
    expect(await page.locator(".itd-dt-k").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(2);
    expect(await page.locator(".itd-verdict").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(3);
    await expect(page.locator(".itd-dt-k")).toHaveValue("4");
    await expect(page.locator(".itd-tickers")).toHaveValue(SYNTH.tickers);
  });

  test("봉과 체결: 결과 판에는 한 줄과 단추 · 봉과 체결 판에 차트 · 가렸다 보이면 그 폭으로 · 닫으면 '다시 열기'", async ({ page }) => {
    await open(page);
    await wsOn(page);
    // 실행 전 판의 문장
    await expect(panel(page, "result").locator(".ws-empty")).toHaveText("실행 결과가 이 자리에 나옵니다. 설정을 정하고 실행하십시오.");
    await tab(page, "bars").click();
    await expect(panel(page, "bars").locator(".ws-empty")).toHaveText("실행 결과가 이 자리에 나옵니다. 설정을 정하고 실행하십시오.");
    await tab(page, "verdict").click();
    await expect(panel(page, "verdict").locator(".ws-empty")).toHaveText("판정은 실행 결과가 나온 뒤에 할 수 있습니다.");
    await setHand(page);
    await run(page);
    const res = panel(page, "result");
    await expect(res.locator(".ws-elsewhere")).toContainText("봉과 체결은 ‘봉과 체결’ 판에 있습니다.");
    await expect(res.locator(".itd-day")).toHaveCount(0);
    await expect(res.locator(".ws-empty")).toHaveCount(0);
    await res.locator(".ws-elsewhere-go").click();
    await expect(tab(page, "bars")).toHaveAttribute("aria-selected", "true");
    await expect(tab(page, "bars")).toBeFocused();
    const svg = panel(page, "bars").locator("svg.cdl");
    await expect(svg).toBeVisible({ timeout: 30_000 });
    const w1 = Number(await svg.getAttribute("width"));
    expect(w1).toBeGreaterThan(100);
    await tab(page, "result").click();
    await expect(panel(page, "bars")).toBeHidden();
    await tab(page, "bars").click();
    await expect(svg).toBeVisible();
    expect(Number(await svg.getAttribute("width"))).toBe(w1);
    // 닫으면 결과 판의 단추가 '다시 열기'
    await panelMenu(page, "1:0", "닫기");
    await expect(panel(page, "bars")).toHaveCount(0);
    await tab(page, "result").click();
    await expect(res.locator(".ws-elsewhere-go")).toHaveText("봉과 체결 판 다시 열기");
    await res.locator(".ws-elsewhere-go").click();
    await expect(tab(page, "bars")).toHaveAttribute("aria-selected", "true");
  });

  test("실행하면 결과 판 탭이 앞으로 · 낭독 · 판정 판은 실행 결과가 없으면 문장", async ({ page }) => {
    await open(page);
    await wsOn(page);
    await tab(page, "daytype").click();
    await setSynth(page);
    await page.locator(".itd-run").click();
    await expect(tab(page, "result")).toHaveAttribute("aria-selected", "true");
    await expect(live(page)).toContainText("‘결과’ 판을 앞으로 냈습니다.");
    await expect(panel(page, "result").locator(".itd-result")).toBeVisible({ timeout: 60_000 });
    expect(await panel(page, "result").evaluate((el) => el.scrollTop)).toBeLessThan(1);
  });

  test("저장: 새로 고쳐도 그 배치 ↔ 깨진 저장은 처음 배치 + 사유 글 · 모르는 판은 고쳐 열고 사유 글", async ({ page }) => {
    await open(page, HUGE);
    await wsOn(page);
    await tab(page, "verdict").click();
    await panelMenu(page, "1:0", "새 열(오른쪽 끝)");
    const kept = await stored(page);
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.locator(".ws-head")).toHaveCount(3);
    expect(await stored(page)).toEqual(kept);
    await expect(page.locator(".ws-note")).toHaveCount(0);
    await seed(page, { [K.layout]: "{oops", [K.on]: "1" });
    await expect(page.locator(".ws-head")).toHaveCount(2);
    await expect(page.locator(".ws-note")).toContainText("저장된 배치를 읽지 못해 처음 배치(두 열)로 열었습니다. 사유: JSON 꼴이 아닙니다.");
    const bad = { v: 1, screen: "intraday", closed: [], cols: [
      { w: 480, rows: [{ tabs: ["setup", "trades"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["result", "bars", "verdict", "daytype", "regime"], active: "result" }] }] };
    await seed(page, { [K.layout]: JSON.stringify(bad) });
    await expect(page.locator(".ws-note")).toContainText("저장된 배치를 고쳐 열었습니다. 모르는 판 ‘trades’를 뺐습니다.");
    expect(await ids(page, "0:0")).toEqual(["setup"]);
  });

  test("이름 붙인 배치: 저장 · 적용 · 이름 바꾸기 · 지우기 · 아홉째는 거절(사유)", async ({ page }) => {
    await open(page, HUGE);
    await wsOn(page);
    await page.locator(".ws-open").click();
    await item(page, "배치 관리").click();
    const sheet = page.locator(".tx-sheet[data-sheet=\"ws\"]");
    await expect(sheet).toBeVisible();
    await sheet.locator(".ws-name").fill("관제용");
    await sheet.locator(".ws-save").click();
    await expect(sheet.locator(".ws-sheet-msg")).toHaveText("‘관제용’ 배치를 저장했습니다.");
    await expect(sheet.locator(".ws-saved-name")).toHaveText(["관제용"]);
    await sheet.locator(".tx-sheet-x").click();
    await tab(page, "verdict").click();
    await panelMenu(page, "1:0", "새 열(오른쪽 끝)");
    await expect(page.locator(".ws-head")).toHaveCount(3);
    await page.locator(".ws-open").click();
    await item(page, "관제용").click();
    await expect(page.locator(".ws-head")).toHaveCount(2);
    // 이름 바꾸기 · 지우기
    await page.locator(".ws-open").click();
    await item(page, "배치 관리").click();
    await sheet.locator(".ws-saved-rename").first().click();
    await sheet.locator(".ws-rename-input").fill("관제");
    await sheet.locator(".ws-rename-ok").click();
    await expect(sheet.locator(".ws-saved-name")).toHaveText(["관제"]);
    await sheet.locator(".ws-saved-remove").first().click();
    await expect(sheet.locator(".ws-saved-name")).toHaveCount(0);
    // 여덟 개를 채운 뒤 아홉째
    for (let i = 1; i <= 8; i++) { await sheet.locator(".ws-name").fill(`배치 ${i}`); await sheet.locator(".ws-save").click(); }
    await expect(sheet.locator(".ws-saved-name")).toHaveCount(8);
    await sheet.locator(".ws-name").fill("배치 9");
    await sheet.locator(".ws-save").click();
    await expect(sheet.locator(".ws-sheet-msg")).toHaveText("이름 붙인 배치는 8개까지입니다. 하나를 지운 뒤 저장하십시오.");
    await expect(sheet.locator(".ws-sheet-msg")).toHaveAttribute("data-tone", "err");
    await expect(sheet.locator(".ws-saved-name")).toHaveCount(8);
  });

  test("파일: 내보낸 파일 = 저장 꼴 · 가져오기는 엄격(다른 화면 · 모르는 판 · 64KB 넘음 → 사유 · 지금 배치 그대로) ↔ 맞는 파일은 적용", async ({ page }) => {
    await open(page, HUGE);
    await wsOn(page);
    // 시트 글의 약속(계좌 · 종목 · 설정은 싣지 않습니다)을 동작으로 — 화면에 종목을 넣어 두고 내보낸다
    await page.locator(".itd-tickers").fill("005930, 000660");
    await page.locator(".ws-open").click();
    await item(page, "배치 관리").click();
    const sheet = page.locator(".tx-sheet[data-sheet=\"ws\"]");
    await expect(sheet.locator(".tj-note").filter({ hasText: "파일에는" })).toHaveText("파일에는 판의 자리 · 열 폭 · 칸 높이 · 이름 붙인 배치의 이름만 있습니다(계좌 · 종목 · 설정은 싣지 않습니다). 가져오기는 꼴이 하나라도 틀리면 파일 전체를 거절합니다.");
    const dl = page.waitForEvent("download");
    await sheet.locator(".ws-export").click();
    const file = await dl;
    expect(file.suggestedFilename()).toMatch(/^workspace-intraday-\d{4}-\d{2}-\d{2}\.json$/);
    const text = fs.readFileSync((await file.path())!, "utf-8");
    const out = JSON.parse(text) as { kind: string; v: number; screen: string; current: unknown; saved: unknown[] };
    expect(Object.keys(out).sort()).toEqual(["current", "kind", "saved", "screen", "v"]);
    expect(text).not.toContain("005930");
    expect(out.kind).toBe("project-alpha.workspace");
    expect(out.screen).toBe("intraday");
    // 켜기만 한 화면: 배치 열쇠는 비어 있고(켬만 남는다) 그리는 배치는 처음 배치(두 열) — 내보낸 지금 배치가 바로 그 배치다
    expect(await stored(page)).toBeNull();
    expect(out.current).toEqual({ v: 1, screen: "intraday", closed: [], cols: [
      { w: 480, rows: [{ tabs: ["setup"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["result", "bars", "verdict", "daytype", "regime"], active: "result" }] }] });
    const before = await stored(page);
    const put = (name: string, body: string) => sheet.locator(".ws-import-file").setInputFiles({ name, mimeType: "application/json", buffer: Buffer.from(body) });
    await put("other.json", JSON.stringify({ ...out, screen: "my-account" }));
    await expect(sheet.locator(".ws-sheet-msg")).toContainText("가져오지 않았습니다. 지금 배치는 그대로입니다.");
    await expect(sheet.locator(".ws-sheet-reasons")).toContainText("다른 화면(‘my-account’)의 배치 파일입니다.");
    const cur = out.current as { cols: { rows: { tabs: string[] }[] }[] };
    cur.cols[0].rows[0].tabs.push("trades");
    await put("unknown.json", JSON.stringify({ ...out, current: cur }));
    await expect(sheet.locator(".ws-sheet-reasons")).toContainText("지금 배치: 모르는 판 ‘trades’를 뺐습니다.");
    await put("big.json", "x".repeat(64 * 1024 + 1));
    await expect(sheet.locator(".ws-sheet-reasons")).toContainText("파일이 64KB를 넘습니다.");
    expect(await stored(page)).toEqual(before);
    const three = { kind: "project-alpha.workspace", v: 1, screen: "intraday", saved: [], current: { v: 1, screen: "intraday", closed: [], cols: [
      { w: 480, rows: [{ tabs: ["setup"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["result", "verdict"], active: "result" }] },
      { w: 480, rows: [{ tabs: ["bars", "daytype", "regime"], active: "bars" }] }] } };
    await put("three.json", JSON.stringify(three));
    await expect(sheet.locator(".ws-sheet-msg")).toHaveText("가져왔습니다. 지금 배치와 이름 붙인 배치 0개를 적용했습니다.");
    await expect(sheet.locator(".ws-sheet-msg")).toHaveAttribute("data-tone", "ok");
    expect(await stored(page)).toEqual(three.current);
    await sheet.locator(".tx-sheet-x").click();
    await expect(page.locator(".ws-head")).toHaveCount(3);
  });

  test("좁은 창: 1200 × 900 에서 같은 상자 안 한 열로 쌓기(머리 · 구분선 없음 · 판 이름 · 문장) · 노드와 입력 보존 ↔ 1440 에서 돌아온다", async ({ page }) => {
    await open(page);
    await wsOn(page);
    await tab(page, "daytype").click();
    await page.locator(".itd-dt-k").fill("4");
    await page.locator(".itd-dt-k").evaluate((el) => { (el as unknown as { __ws: number }).__ws = 7; });
    await page.setViewportSize({ width: 1200, height: 900 });
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "stack");
    await expect(page.locator(".ws-head, .ws-col-slot, .ws-row-bar")).toHaveCount(0);
    await expect(page.locator(".ws-panel-name")).toHaveText(["설정", "결과", "봉과 체결", "판정", "하루 유형", "시장 국면"]);
    // 판 이름은 보이는 머리로 선다(탭이 없으니) ↔ 아래 1440 의 탭 보기에서는 낭독용(1px)
    expect((await page.locator(".ws-panel-name").first().boundingBox())!.height).toBeGreaterThan(12);
    for (const id of ["setup", "result", "bars", "verdict", "daytype", "regime"]) {
      await expect(panel(page, id)).toBeVisible();
      await expect(panel(page, id)).toHaveAttribute("role", "region");
    }
    await expect(page.getByRole("region", { name: "하루 유형" })).toBeVisible();
    await expect(page.locator(".ws-note")).toContainText("창이 좁아 판을 한 열로 쌓아 보입니다. 넓히면 저장한 배치로 돌아갑니다.");
    expect(await page.locator(".itd-dt-k").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(7);
    await expect(page.locator(".itd-dt-k")).toHaveValue("4");
    const main = await page.locator(".terminal-main").evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight }));
    expect(main.sh).toBeGreaterThan(main.ch);
    await page.setViewportSize(WIDE);
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "tabs");
    await expect(page.locator(".ws-head")).toHaveCount(2);
    await expect(tab(page, "daytype")).toHaveAttribute("aria-selected", "true");
    expect(await page.locator(".itd-dt-k").evaluate((el) => (el as unknown as { __ws?: number }).__ws)).toBe(7);
    expect((await page.locator(".ws-panel-name").first().boundingBox())!.height).toBeLessThanOrEqual(1);
  });

  test("판 이름과 판 안 첫 절의 제목이 같은 판: 그 이름의 제목은 하나(쌓기는 판 이름 · 탭은 절 제목) · 절의 부제와 다른 판의 절 제목은 그대로", async ({ page }) => {
    // 봉과 체결 · 판정 · 하루 유형 · 시장 국면은 판 안 첫 절이 판 이름을 제목으로 단다 — 쌓기에서 같은 제목이 두 번 서고 탭에서는 낭독용 이름과 겹쳤다(2a-1 내 실수 ⑨)
    const NAMES: Record<string, string> = { setup: "설정", result: "결과", bars: "봉과 체결", verdict: "판정", daytype: "하루 유형", regime: "시장 국면" };
    const TITLED = ["bars", "verdict", "daytype", "regime"];
    const heading = (id: string) => panel(page, id).getByRole("heading", { name: NAMES[id], exact: true });
    const firstSec = (id: string) => panel(page, id).locator(":scope > .ws-panel-name + .tx-sec > .tx-sec-head");
    await open(page);
    await wsOn(page);
    // 실행 전: 문장만 있는 판은 판 이름이 그 판의 제목(낭독)으로 남는다
    for (const id of ["bars", "verdict"]) {
      await tab(page, id).click();
      await expect(panel(page, id).locator(".ws-empty"), id).toBeVisible();
      await expect(heading(id), id).toHaveCount(1);
    }
    await setSynth(page);
    await run(page);
    await tab(page, "verdict").click();
    await judge(page);
    // 탭: 판마다 그 이름의 제목(낭독 포함)은 하나 · 같은 제목의 절은 보인다
    for (const id of Object.keys(NAMES)) {
      await tab(page, id).click();
      await expect(heading(id), id).toHaveCount(1);
      if (TITLED.includes(id)) {
        await expect(firstSec(id).locator(".tx-sec-t"), id).toHaveText(NAMES[id]);
        await expect(firstSec(id).locator(".tx-sec-t"), id).toBeVisible();
      }
    }
    // 쌓기: 판 이름이 판의 제목 · 같은 글의 절 제목은 그리지 않는다 · 그 절의 부제는 남는다
    await page.setViewportSize({ width: 1200, height: 900 });
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "stack");
    for (const id of Object.keys(NAMES)) {
      await expect(heading(id), id).toHaveCount(1);
      await expect(panel(page, id).locator(":scope > .ws-panel-name"), id).toBeVisible();
      if (TITLED.includes(id)) {
        await expect(firstSec(id).locator(".tx-sec-t"), id).toHaveText(NAMES[id]);
        await expect(firstSec(id).locator(".tx-sec-t"), id).toBeHidden();
        await expect(firstSec(id).locator(".tx-sec-sub"), id).toBeVisible();
      }
    }
    // 짝: 판 이름과 다른 절 제목은 쌓기에서도 보인다(설정의 '데이터' · 결과 판의 첫 절 · 같은 판의 둘째 절부터)
    await expect(panel(page, "setup").getByRole("heading", { name: "데이터", exact: true })).toBeVisible();
    await expect(panel(page, "verdict").getByRole("heading", { name: "관문 일곱", exact: true })).toBeVisible();
    await expect(panel(page, "result").locator(".tx-sec-t").first()).toBeVisible();
    await expect(panel(page, "result").locator(".tx-sec-t").first()).not.toHaveText(NAMES.result);
    // 넓히면 탭 — 절 제목이 다시 보인다
    await page.setViewportSize(WIDE);
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "tabs");
    await tab(page, "daytype").click();
    await expect(firstSec("daytype").locator(".tx-sec-t")).toBeVisible();
    await expect(heading("daytype")).toHaveCount(1);
  });

  test("세 열: 1440 에서는 비활성 + 까닭 ↔ 1920 에서는 고른다 · 저장된 세 열을 1440 에서 열면 합쳐 보이고 저장 꼴 그대로 · 그동안 끌어 놓기는 쉰다", async ({ page }) => {
    await open(page);
    await page.locator(".ws-open").click();
    const three = item(page, /^세 열/);
    await expect(three).toHaveAttribute("aria-disabled", "true");
    await expect(page.locator(".ws-menu")).toContainText("창이 좁아 고를 수 없습니다");
    await three.click({ force: true });                                             // 눌러도 아무 일 없음(aria-disabled 는 Playwright 가 '사용 불가'로 본다 — 힘으로 누른다)
    await expect(three).toBeVisible();                                              // 메뉴는 닫히지 않는다
    await expect(page.locator(".itd")).not.toHaveAttribute("data-ws", /.*/);
    await page.keyboard.press("Escape");
    await page.setViewportSize(HUGE);
    await page.locator(".ws-open").click();
    await expect(item(page, /^세 열/)).not.toHaveAttribute("aria-disabled", "true");
    await item(page, /^세 열/).click();
    await expect(page.locator(".ws-head")).toHaveCount(3);
    const saved3 = await stored(page);
    await page.setViewportSize(WIDE);
    await expect(page.locator(".ws-head")).toHaveCount(2);
    await expect(page.locator(".ws-note")).toContainText("창이 좁아 셋째 열을 둘째 열의 탭으로 합쳐 보입니다.");
    expect(await ids(page, "1:0")).toEqual(["result", "verdict", "bars", "daytype", "regime"]);
    expect(await stored(page)).toEqual(saved3);
    // 합쳐 보이는 동안 끌어 놓기는 쉰다
    const t = (await tab(page, "bars").boundingBox())!;
    await page.mouse.move(t.x + 10, t.y + 10);
    await page.mouse.down();
    await page.mouse.move(t.x - 300, t.y + 300, { steps: 6 });
    await expect(page.locator(".ws-drop")).toHaveCount(0);
    await page.mouse.up();
    expect(await stored(page)).toEqual(saved3);
    // 합친 칸에서 고른 탭은 그리기에만(저장 꼴 그대로)
    await tab(page, "daytype").click();
    await expect(tab(page, "daytype")).toHaveAttribute("aria-selected", "true");
    expect(await stored(page)).toEqual(saved3);
    await page.setViewportSize(HUGE);
    await expect(page.locator(".ws-head")).toHaveCount(3);
    await expect(page.locator(".ws-note")).toHaveCount(0);
  });

  test("기본 배치로 끄면 G5 두 칸 · 실행 결과 · 판정은 남고 POST 0 · 다시 켜면 마지막 배치", async ({ page }) => {
    await open(page, HUGE);
    await wsOn(page);
    await tab(page, "verdict").click();
    await panelMenu(page, "1:0", "새 열(오른쪽 끝)");
    const posts = countPosts(page);
    await setSynth(page);
    await run(page);
    await tab(page, "verdict").click();
    await judge(page);
    expect(posts.length).toBe(2);
    const kept = await stored(page);                                                // 실행이 결과 판을 앞으로 낸 것도 배치(앞 탭)다 — 끄기 직전의 꼴
    expect((kept as { cols: unknown[] }).cols).toHaveLength(3);
    await page.locator(".ws-open").click();
    await radio(page, "기본 배치").click();
    await expect(page.locator(".itd")).toHaveAttribute("data-split", "");
    await expect(page.locator(".itd")).not.toHaveAttribute("data-ws", /.*/);
    await expect(page.locator(".ws")).toHaveCount(0);
    await expect(page.locator(".itd-out .itd-result")).toBeVisible();
    await expect(page.locator(".itd-out .itd-verdict")).toBeVisible();
    expect(await page.evaluate((k) => localStorage.getItem(k), K.on)).toBeNull();
    await page.locator(".ws-open").click();
    await radio(page, "판 배치").click();
    await expect(page.locator(".ws-head")).toHaveCount(3);
    expect(await stored(page)).toEqual(kept);
    expect(posts.length).toBe(2);
  });

  test("구분선: 열 폭(키 · 끌기 · 최소 폭) · 칸 높이(↑ ↓ Home End) · 이 칸만 크게 ↔ Escape", async ({ page }) => {
    await open(page);
    await wsOn(page);
    const bar = page.getByRole("separator", { name: "첫째 열 폭" });
    await expect(bar).toHaveAttribute("aria-valuenow", "480");
    await expect(bar).toHaveAttribute("aria-valuemin", "440");
    const work = await page.locator(".ws-grid").evaluate((el) => el.clientWidth);
    await expect(bar).toHaveAttribute("aria-valuemax", String(work - 16 - 640));
    await bar.focus();
    await page.keyboard.press("ArrowRight");
    await expect(bar).toHaveAttribute("aria-valuenow", "496");
    await page.keyboard.press("Home");
    await expect(bar).toHaveAttribute("aria-valuenow", "440");
    expect(Math.round((await panel(page, "setup").boundingBox())!.width)).toBe(440);
    expect(((await stored(page)) as { cols: { w: number | null }[] }).cols[0].w).toBe(440);
    const b = (await bar.boundingBox())!;
    await page.mouse.move(b.x + b.width / 2, b.y + 200);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2 + 100, b.y + 200, { steps: 5 });
    await page.mouse.up();
    await expect(bar).toHaveAttribute("aria-valuenow", "540");
    // 칸 높이: 하루 유형을 둘째 열 아래 칸으로
    await tab(page, "daytype").click();
    await panelMenu(page, "1:0", "이 열 아래에 새 칸");
    const row = page.getByRole("separator", { name: "둘째 열 아래 칸 높이" });
    await expect(row).toHaveAttribute("aria-orientation", "horizontal");
    await expect(row).toHaveAttribute("aria-valuenow", "50");
    await row.focus();
    await page.keyboard.press("ArrowUp");
    await expect(row).toHaveAttribute("aria-valuenow", "55");
    await page.keyboard.press("Home");
    await expect(row).toHaveAttribute("aria-valuenow", "20");
    await page.keyboard.press("End");
    await expect(row).toHaveAttribute("aria-valuenow", "80");
    expect(((await stored(page)) as { cols: { rows: { h?: number }[] }[] }).cols[1].rows[1].h).toBe(0.8);
    // 이 칸만 크게 ↔ Escape
    await panelMenu(page, "1:1", "이 칸만 크게", true);
    await expect(head(page, "0:0")).toBeHidden();
    await expect(head(page, "1:0")).toBeHidden();
    await expect(panel(page, "daytype")).toBeVisible();
    const z = (await panel(page, "daytype").boundingBox())!;
    expect(z.width).toBeGreaterThan(work - 4);
    await expect(live(page)).toContainText("둘째 열 아래 칸만 크게 보입니다. Escape로 되돌립니다.");
    await page.keyboard.press("Escape");
    await expect(head(page, "0:0")).toBeVisible();
    await expect(live(page)).toContainText("배치로 되돌렸습니다.");
  });

  test("이 칸만 크게: 판 위에 그 사실과 '배치로 되돌리기' 단추 → 누르면 배치로 · 초점은 그 칸의 앞 탭 · 저장한 배치 불변 ↔ 크게 보지 않으면 글 · 단추 없음", async ({ page }) => {
    await open(page);
    await wsOn(page);
    await tab(page, "bars").click();
    await expect(page.locator(".ws-zoom-note, .ws-unzoom")).toHaveCount(0);
    const before = await stored(page);
    await panelMenu(page, "1:0", "이 칸만 크게", true);
    const note = page.locator(".ws-zoom-note");
    await expect(note).toContainText("둘째 열만 크게 보입니다. Escape로 되돌립니다.");
    await expect(head(page, "0:0")).toBeHidden();
    await note.locator(".ws-unzoom").click();                                      // Escape 를 모르는 포인터 사용자의 길
    await expect(page.locator(".ws-zoom-note, .ws-unzoom")).toHaveCount(0);
    await expect(head(page, "0:0")).toBeVisible();
    await expect(tab(page, "bars")).toBeFocused();                                 // 단추가 사라지므로 초점은 크게 보던 칸의 앞 탭
    await expect(live(page)).toContainText("배치로 되돌렸습니다.");
    expect(await stored(page)).toEqual(before);                                    // 크게 보기는 배치에 남지 않는다
  });

  test("저장 실패: 이 브라우저에 배치를 남기지 못하면 판 위에 그렇게 적고 이번 화면에서만 쓴다 · 이름 붙인 배치는 저장했다고 말하지 않는다", async ({ page }) => {
    // 배치 · 이름 붙인 배치 열쇠만 쓰기를 막는다(켬 열쇠와 로그인은 그대로) — 브라우저가 저장을 거절한 경우(용량 · 사생활 보호 모드)
    await page.addInitScript(() => {
      const orig = Storage.prototype.setItem;
      Storage.prototype.setItem = function (this: Storage, k: string, v: string) {
        if (k === "ws.intraday" || k === "ws.intraday.saved") throw new DOMException("막힌 저장", "QuotaExceededError");
        return orig.call(this, k, v);
      };
    });
    await open(page);
    await wsOn(page);
    await expect(page.locator(".ws-note")).toHaveCount(0);                         // 켬은 남았고 배치는 아직 쓰지 않았다
    await tab(page, "verdict").click();
    await expect(page.locator(".ws-note")).toHaveText(["이 브라우저에 배치를 남기지 못했습니다. 이번 화면에서만 씁니다."]);
    await expect(tab(page, "verdict")).toHaveAttribute("aria-selected", "true");   // 이번 화면에서는 쓴다
    expect(await stored(page)).toBeNull();                                         // 남지 않았다
    await page.locator(".ws-open").click();
    await item(page, "배치 관리").click();
    const sheet = page.locator(".tx-sheet[data-sheet=\"ws\"]");
    await sheet.locator(".ws-name").fill("관제");
    await sheet.locator(".ws-save").click();
    await expect(sheet.locator(".ws-sheet-msg")).toHaveText("이 브라우저에 저장하지 못했습니다. 이름 붙인 배치는 바뀌지 않았습니다.");
    await expect(sheet.locator(".ws-sheet-msg")).toHaveAttribute("data-tone", "err");
    await expect(sheet.locator(".ws-saved-name")).toHaveCount(0);
  });

  test("합성 알림은 판 밖 위 · 결과 판 머리의 출처 칩 · 다크 대비 · 문체 · 390 × 844 넘침 0", async ({ page }) => {
    await page.addInitScript(() => { try { localStorage.setItem("alpha_theme", "dark"); } catch { /* */ } });
    await open(page);
    await wsOn(page);
    await expect(page.locator("html")).toHaveClass(/dark/);
    await setSynth(page);
    await run(page);
    const banner = page.locator(".itd-banner");
    await expect(banner).toBeVisible();
    expect(await banner.evaluate((el) => el.closest(".ws") === null)).toBe(true);
    const bb = (await banner.boundingBox())!, wb = (await page.locator(".ws").boundingBox())!;
    expect(bb.y + bb.height).toBeLessThanOrEqual(wb.y + 0.5);
    await expect(panel(page, "result").locator(".tx-chip", { hasText: "합성 분봉" })).toBeVisible();
    const c = await page.evaluate<AuditResult>(contrastAudit(".ws"));
    expect(c.checked).toBeGreaterThan(20);
    expect(c.low).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".ws"))) as VoiceResult;
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    await page.setViewportSize(PHONE);
    await expect(page.locator(".itd")).toHaveAttribute("data-ws", "stack");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  });
});
