import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════════════════════════
// 분봉 결과 › '시장 국면별로 나눠 보기' › '하루 유형 비율' (K2b · 2026-11-17 · 구현 계획 §7.3)
// 분봉: `seed_day_types.py`(학습 — 005380 · 035420 · 2026-05-04 ~ 05-19 · 5분 · 유형 넷) + `seed_day_type_rules.py`(판정 날 넷).
//  · 번호(끝값 오름차순): 1 = 내림 · 2 = V · 3 = 역V · 4 = 오름.
//  · 판정 날: 07-01 역V · 07-02 오름 · 07-03 내림 · 07-06 V — 날마다 두 종목이 같은 경로 · 봉 여덟(창 다섯 + 뒤 셋).
//  → 이 시행(07-01 ~ 07-06 · 두 종목)의 표본 8 · 모두 유형을 정함 · 유형마다 2(25.0%) · 학습 날과 겹친 날 0 — 합계 열의 손 계산.
// 국면은 E2E 서버(mock 게이트)의 합성 지수 걸음이다 — 그래서 여기서 거는 것은 장치다:
//  · 모형은 비어서 시작(도구가 고르지 않는다) · 국면 수 · 모형이 비면 묻지 않는다 · 물을 때는 방금 실행의 시행 열쇠 · 폼의 지수 · 국면 수 · 고른 모형
//  · 표의 모든 칸 · 요약 줄 · 뺀 표본 · 국면 미상 사유 · 모형 사실 줄 · 한계 문장 = 서버 값(칸마다 다른 심은 답으로도)
//  · 등급 넷 가운데 하나라도 합성이면 맨 위 알림 ↔ 모두 실데이터면 없다 · 표본 등급 미상은 서버 사유
//  · 세지 않은 까닭 · 거절은 서버 사유(재시도 없음) · 실패는 재시도 · 모형이 없을 때 · 목록을 못 읽을 때
//  · 국면 수를 바꾸면 앞의 답을 지운다 · 라이트/다크 AA · 문체 · 390px(표는 칸 글자를 쪼개지 않고 옆으로 넘긴다)
// ════════════════════════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const ROOT = path.join(__dirname, "..", "..");
const BARS = "/tmp/e2e_minute_bars";                 // playwright.config.ts 의 서버가 읽는 자리와 같아야 한다
const HERE = "/backtest/intraday";
const TRAIN = { tickers: ["005380", "035420"], from: "2026-05-04", to: "2026-05-19", minutes: 5, k: 4 };
const JUDGE = { tickers: "005380, 035420", from: "2026-07-01", to: "2026-07-06" };
const NO_MODELS = "학습한 하루 유형 모형이 없습니다. 백테스트 › 분봉 규칙의 ‘하루 유형’에서 먼저 학습합니다.";
const IS_RDT = (u: string) => /\/intraday\/trials\/[^/]+\/regime-day-types$/.test(new URL(u).pathname);
const IS_SIM = (u: string) => new URL(u).pathname.endsWith("/intraday/simulate");
const IS_LIST = (u: string) => /\/intraday\/day-types$/.test(new URL(u).pathname);
const MINUS = "−";
const n = (v: number) => v.toLocaleString("ko-KR");
/** 화면의 퍼센트 서식(`krFormat.pct`)과 같은 규칙 — 소수 한 자리 · 빼기는 U+2212. */
const pct = (p: number) => {
  const v = p * 100;
  return `${Number(Math.abs(v).toFixed(1)) === 0 ? "" : v < 0 ? MINUS : ""}${Math.abs(v).toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
};

type Cell = { type: number; n: number; in_sample: number; share: number | null };
type Group = { samples: number; classified: number; in_sample: number; types: Cell[]; excluded: Record<string, number> };
type Table = { k: number; types_k: number; states: (Group & { state: number })[];
  unknown: Group & { reasons: { reason: string; days: number; samples: number }[] }; total: Group };

test.beforeAll(() => {
  for (const script of ["seed_day_types.py", "seed_day_type_rules.py"]) {
    execFileSync(process.env.E2E_PYTHON ?? "python3", [path.join("frontend", "e2e", "fixtures", "intraday", script)],
      { cwd: ROOT, env: { ...process.env, KIS_USE_MOCK: "1", MINUTE_BARS_DIR: BARS }, stdio: "pipe" });
  }
});

async function login(page: Page): Promise<string> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
  return token;
}

/** 학습 문으로 모형 하나를 짓는다(같은 입력은 같은 열쇠 — 몇 번 불러도 같은 모형). */
async function trainModel(page: Page, token: string): Promise<string> {
  const r = await page.request.post(`${API}/intraday/day-types`, { data: TRAIN, headers: { Authorization: `Bearer ${token}` } });
  expect(r.ok(), await r.text()).toBe(true);
  return (await r.json()).model.key as string;
}

const field = (page: Page, key: string) => page.locator(`.itd-field[data-key="${key}"] .tj-input`);

/** 판정 날 넷을 시가 범위 돌파 1분으로 돌린다 — 규칙은 무엇이든 된다(표는 규칙이 아니라 시행의 종목 · 기간을 센다). */
async function runJudge(page: Page): Promise<{ key: string; model: string }> {
  const token = await login(page);
  const model = await trainModel(page, token);
  await page.goto(HERE, { waitUntil: "domcontentloaded" });
  await expect(page.locator(".itd-tickers")).toBeVisible();
  await page.locator(".itd-tickers").fill(JUDGE.tickers);
  await page.locator(".itd-from").fill(JUDGE.from);
  await page.locator(".itd-to").fill(JUDGE.to);
  await field(page, "minutes").fill("1");
  await field(page, "unknown_market").selectOption("KOSPI");
  await field(page, "unknown_instrument").selectOption("stock");
  const got = page.waitForResponse((r) => IS_SIM(r.url()) && r.request().method() === "POST", { timeout: 60_000 });
  await page.locator(".itd-run").click();
  const js = await (await got).json();
  await expect(page.locator(".itd-result")).toBeVisible({ timeout: 30_000 });
  const key = js.trial?.trial_key as string | null;
  expect(key, "전제 — 실행이 시행으로 남았다").toBeTruthy();
  return { key: key as string, model };
}

async function count(page: Page, k: string, model: string, index?: string) {
  if (index) await page.locator(".itd-rs-index").selectOption(index);
  await page.locator(".itd-rs-k").selectOption(k);
  await page.locator(".itd-rdt-model").selectOption(model);
  const sent = page.waitForRequest((r) => IS_RDT(r.url()));
  const got = page.waitForResponse((r) => IS_RDT(r.url()), { timeout: 60_000 });
  await page.locator(".itd-rdt-run").click();
  const url = new URL((await sent).url());
  const res = await got;
  return { url, status: res.status(), js: await res.json() };
}

/** 응답을 고쳐 심는다 — 서버의 답을 받아 `change` 를 거친 몸으로 바꾼다(그리기 계약만 본다 · 서버의 셈은 pytest). */
async function plant(page: Page, change: (js: Record<string, unknown>) => void) {
  await page.route((u) => IS_RDT(u.toString()), async (route) => {
    const r = await route.fetch();
    const js = await r.json();
    change(js);
    await route.fulfill({ response: r, json: js });
  });
}

const cellText = (c: Cell) => [c.share === null ? "N/A" : pct(c.share), `${n(c.n)}개${c.in_sample ? ` · 표본 안 ${n(c.in_sample)}` : ""}`].join(" ");
const column = (t: Table) => [...t.states.map((s) => ({ key: String(s.state), g: s as Group })),
  ...(t.unknown.samples > 0 ? [{ key: "unknown", g: t.unknown as Group }] : []), { key: "total", g: t.total }];

test("모형은 비어서 시작하고 국면 수 · 모형이 비면 묻지 않는다 — 고르면 방금 실행의 시행 열쇠 · 폼 · 고른 모형으로 묻는다", async ({ page }) => {
  const asked: string[] = [];
  page.on("request", (r) => { if (IS_RDT(r.url())) asked.push(r.url()); });
  const { key, model } = await runJudge(page);
  await expect(page.locator(".itd-rdt-model")).toHaveValue("");
  await expect(page.locator(".itd-rdt-run")).toBeDisabled();
  await expect(page.locator(".itd-rdt-problems li")).toHaveText(["국면 수를 고르십시오.", "하루 유형 모형을 고르십시오."]);
  await page.locator(".itd-rs-k").selectOption("2");
  await expect(page.locator(".itd-rdt-problems li")).toHaveText(["하루 유형 모형을 고르십시오."]);
  await expect(page.locator(".itd-rdt-run")).toBeDisabled();
  expect(asked).toEqual([]);
  const { url } = await count(page, "2", model, "KOSDAQ");
  expect(url.pathname).toBe(`${API}/intraday/trials/${key}/regime-day-types`);
  expect(Object.fromEntries(url.searchParams)).toEqual({ index: "KOSDAQ", k: "2", model });
  const res = page.locator(".itd-rdt-result");
  await expect(res).toHaveAttribute("data-model", model);
  await expect(res).toHaveAttribute("data-index", "KOSDAQ");
  // 고른 모형의 이름(열쇠 · 학습 기간 · 유형 수 · 분 수)이 칸에 다 보인다 — 스크린샷 검수에서 180px 칸에 잘린 것을 찾았다
  const fit = await page.locator(".itd-rdt-model").evaluate((el) => {
    const s = el as HTMLSelectElement;
    const label = s.options[s.selectedIndex]?.text ?? "";
    const cs = getComputedStyle(s);
    const probe = document.createElement("span");
    Object.assign(probe.style, { font: cs.font, whiteSpace: "pre", position: "absolute", visibility: "hidden" });
    probe.textContent = label;
    document.body.appendChild(probe);
    const need = probe.getBoundingClientRect().width + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + 24;   // 24 = 펼침 화살표
    probe.remove();
    return { need: Math.ceil(need), have: s.clientWidth, label };
  });
  expect(fit.label, "전제 — 모형의 이름이 다 적혔다").toContain("유형 4개 · 5분");
  expect(fit.have, `모형 이름이 칸에 다 보인다: ${fit.label}`).toBeGreaterThanOrEqual(fit.need);
  await expect(page.locator(".itd-rdt-problems")).toHaveCount(0);
  // 국면 수를 바꾸면 앞의 답을 지운다(다른 물음의 답을 남기지 않는다) — 고른 모형은 그대로
  await page.locator(".itd-rs-k").selectOption("3");
  await expect(res).toHaveCount(0);
  await expect(page.locator(".itd-rdt-model")).toHaveValue(model);
});

test("표 · 요약 줄 · 모형 사실 줄 · 한계 문장 = 서버 값 — 합계 열은 손 계산(표본 8 · 유형마다 2 · 25.0% · 표본 안 0)", async ({ page }) => {
  const { model } = await runJudge(page);
  // 잰 값(E2E 서버의 합성 지수): 코스피 · 국면 3개면 판정 날 넷의 표본이 국면 2(6개) · 국면 3(2개)로 갈리고 국면 1 은 0개다.
  // 국면 2개면 여덟 모두 국면 2 라 나눔이 공허하다(아래 전제가 잡는다 — K2a 에서 같은 실수를 했다).
  const { js } = await count(page, "3", model, "KOSPI");
  const t = js.table as Table;
  expect(t, "전제 — 셌다").not.toBeNull();
  expect(t.states.filter((s) => s.samples > 0).length, "전제 — 둘 이상의 국면에 표본이 있다(나눔이 공허하지 않다)").toBeGreaterThan(1);
  // 손 계산 — 판정 날 넷 × 두 종목, 날마다 두 종목이 같은 유형(07-01 역V = 3 · 07-02 오름 = 4 · 07-03 내림 = 1 · 07-06 V = 2)
  expect([t.total.samples, t.total.classified, t.total.in_sample]).toEqual([8, 8, 0]);
  expect(t.total.types.map((c) => [c.n, c.share, c.in_sample])).toEqual([[2, 0.25, 0], [2, 0.25, 0], [2, 0.25, 0], [2, 0.25, 0]]);
  const cols = column(t);
  await expect(page.locator(".itd-rdt-table thead th")).toHaveText(["유형", ...cols.map((c) => (
    c.key === "unknown" ? "국면 미상" : c.key === "total" ? "합계" : `국면 ${c.key}`))]);
  for (const ty of [1, 2, 3, 4]) {
    await expect(page.locator(`.itd-rdt-table tbody tr[data-type="${ty}"] > *`))
      .toHaveText([`유형 ${ty}`, ...cols.map((c) => cellText(c.g.types[ty - 1]))]);
  }
  await expect(page.locator('.itd-rdt-table tbody tr[data-type="1"] > *').last()).toHaveText("25.0% 2개");   // 합계 열 = 손 계산
  for (const [row, label, pick] of [["samples", "표본", (g: Group) => g.samples], ["classified", "유형을 정한 표본", (g: Group) => g.classified],
    ["in_sample", "표본 안 분류", (g: Group) => g.in_sample]] as const) {
    await expect(page.locator(`.itd-rdt-table tfoot tr[data-row="${row}"] > *`)).toHaveText([label, ...cols.map((c) => `${n(pick(c.g))}개`)]);
  }
  // 국면 색은 번호의 표지 — 국면마다 다른 색(순위가 아니다 · K2a 와 같은 밝기 단계)
  const chips = page.locator(".itd-rdt-table thead .itd-rs-chip:not(.itd-rs-chip--unknown)");
  const colors = await chips.evaluateAll((els) => els.map((e) => getComputedStyle(e).backgroundColor));
  expect(new Set(colors).size, "국면마다 다른 색").toBe(t.states.length);
  await expect(page.locator(".itd-rdt-facts li")).toHaveText(js.model.facts as string[]);
  await expect(page.locator(".itd-rdt-notes li")).toHaveText(js.notes as string[]);
  await expect(page.locator(".itd-rdt-excluded")).toHaveCount(0);                // 짝 — 뺀 표본이 없으면 그 목록이 없다
  await expect(page.locator(".itd-rdt-cap")).toContainText("관측이며 결정에 쓰지 않습니다");
});

test("칸마다 서버 값 그대로 — 칸끼리 값이 다른 심은 답(비율 없음 · 표본 안 · 국면 미상 열 · 뺀 표본 · 미상 사유)", async ({ page }) => {
  const { model } = await runJudge(page);
  const why = "심은 사유: 적합 창이 덜 찼습니다.";
  const cell = (type: number, cnt: number, inside: number, share: number | null): Cell => ({ type, n: cnt, in_sample: inside, share });
  const planted: Table = {
    k: 2, types_k: 4,
    states: [
      { state: 1, samples: 5, classified: 4, in_sample: 3, excluded: { short_window: 1 },
        types: [cell(1, 1, 1, 0.25), cell(2, 0, 0, 0), cell(3, 3, 2, 0.75), cell(4, 0, 0, 0)] },
      { state: 2, samples: 2, classified: 0, in_sample: 0, excluded: { bad_price: 2 },
        types: [cell(1, 0, 0, null), cell(2, 0, 0, null), cell(3, 0, 0, null), cell(4, 0, 0, null)] },
    ],
    unknown: { samples: 3, classified: 3, in_sample: 0, excluded: {}, reasons: [{ reason: why, days: 2, samples: 3 }],
      types: [cell(1, 0, 0, 0), cell(2, 2, 0, 2 / 3), cell(3, 0, 0, 0), cell(4, 1, 0, 1 / 3)] },
    total: { samples: 10, classified: 7, in_sample: 3, excluded: { bad_price: 2, short_window: 1 },
      types: [cell(1, 1, 1, 1 / 7), cell(2, 2, 0, 2 / 7), cell(3, 3, 2, 3 / 7), cell(4, 1, 0, 1 / 7)] },
  };
  const messages = { bad_price: "심은 문장: 첫 봉 시가나 창 안의 종가가 0 이하입니다.", short_window: "심은 문장: 창이 덜 찼습니다." };
  await plant(page, (js) => { js.k = 2; js.empty = null; js.table = planted; js.excluded_messages = messages; });
  await count(page, "2", model);
  const row = (ty: number) => page.locator(`.itd-rdt-table tbody tr[data-type="${ty}"] > *`);
  await expect(page.locator(".itd-rdt-table thead th")).toHaveText(["유형", "국면 1", "국면 2", "국면 미상", "합계"]);
  await expect(row(1)).toHaveText(["유형 1", "25.0% 1개 · 표본 안 1", "N/A 0개", "0.0% 0개", "14.3% 1개 · 표본 안 1"]);
  await expect(row(2)).toHaveText(["유형 2", "0.0% 0개", "N/A 0개", "66.7% 2개", "28.6% 2개"]);
  await expect(row(3)).toHaveText(["유형 3", "75.0% 3개 · 표본 안 2", "N/A 0개", "0.0% 0개", "42.9% 3개 · 표본 안 2"]);
  await expect(row(4)).toHaveText(["유형 4", "0.0% 0개", "N/A 0개", "33.3% 1개", "14.3% 1개"]);
  await expect(page.locator('.itd-rdt-table tfoot tr[data-row="samples"] > *')).toHaveText(["표본", "5개", "2개", "3개", "10개"]);
  await expect(page.locator('.itd-rdt-table tfoot tr[data-row="classified"] > *')).toHaveText(["유형을 정한 표본", "4개", "0개", "3개", "7개"]);
  await expect(page.locator('.itd-rdt-table tfoot tr[data-row="in_sample"] > *')).toHaveText(["표본 안 분류", "3개", "0개", "0개", "3개"]);
  await expect(page.locator(".itd-rdt-excluded li")).toHaveText([`뺀 표본 2개 ${messages.bad_price}`, `뺀 표본 1개 ${messages.short_window}`]);
  await expect(page.locator(".itd-rdt-unknown li")).toHaveText([`국면 미상 2일 · 표본 3개 ${why}`]);
});

test("등급 — 넷 가운데 하나라도 합성이면 맨 위 알림 · 모두 실데이터면 없다 · 표본 등급 미상은 서버 사유", async ({ page }) => {
  const { model } = await runJudge(page);
  const { js } = await count(page, "2", model);
  // 잰 값(E2E 서버): 심은 분봉은 실데이터 표시라 시행 · 모형 · 표본 등급 E3 · 국면은 합성 지수라 E0 — 국면 쪽만 합성이어도 알린다
  expect([js.trial_grade, js.model.grade, js.samples_grade, js.regime_grade], "전제 — 등급이 갈린다").toEqual(["E3", "E3", "E3", "E0"]);
  await expect(page.locator(".itd-rdt-synth")).toHaveCount(1);
  await expect(page.locator(".itd-rdt-head")).toContainText("시행 등급 E3 · 국면 등급 E0 · 모형 등급 E3 · 표본 등급 E3");
  await plant(page, (x) => { x.regime_grade = "E3"; x.coverage = { ok: true, reason: null }; });
  await count(page, "3", model);
  await expect(page.locator(".itd-rdt-head")).toContainText("시행 등급 E3 · 국면 등급 E3 · 모형 등급 E3 · 표본 등급 E3");
  await expect(page.locator(".itd-rdt-synth")).toHaveCount(0);                   // 짝 — 모두 실데이터면 알림이 없다
  await page.unroute((u) => IS_RDT(u.toString()));
  const why = "심은 사유: 쓰인 분봉이 없습니다.";
  const regimeWhy = "심은 사유: 일봉의 출처 표시가 없어 등급을 매기지 않았습니다.";
  await plant(page, (x) => {
    x.regime_grade = null; x.regime_grade_reason = regimeWhy; x.samples_grade = null; x.samples_grade_reason = why;
    x.coverage = { ok: true, reason: null };
  });
  await count(page, "2", model);
  await expect(page.locator(".itd-rdt-head")).toContainText("시행 등급 E3 · 국면 등급 미상 · 모형 등급 E3 · 표본 등급 미상");
  await expect(page.locator(".itd-rdt-samples-grade [data-server]")).toHaveText(why);
  await expect(page.locator(".itd-rdt-grade [data-server]")).toHaveText(regimeWhy);
  await expect(page.locator(".itd-rdt-synth")).toHaveCount(0);                   // 미상은 합성이 아니다(알림으로 바꾸지 않는다)
  await page.unroute((u) => IS_RDT(u.toString()));
  await plant(page, (x) => { x.regime_grade = "E3"; (x.model as Record<string, unknown>).grade = "E0"; x.coverage = { ok: true, reason: null }; });
  await count(page, "3", model);
  await expect(page.locator(".itd-rdt-synth")).toHaveCount(1);                   // 모형만 합성이어도 알린다
});

test("세지 않은 까닭은 서버 사유 그대로 · 거절도 서버 사유(재시도 없음) · 실패는 재시도", async ({ page }) => {
  const { model } = await runJudge(page);
  const message = "심은 사유: 하루 유형 모형의 기록이 그 모형의 유형 수와 맞지 않습니다.";
  await plant(page, (js) => { js.table = null; js.empty = { reason: "model_unreadable", message }; });
  await count(page, "2", model);
  await expect(page.locator('.itd-rdt-empty[data-empty="model_unreadable"] [data-server]')).toHaveText(message);
  await expect(page.locator(".itd-rdt-table")).toHaveCount(0);
  await page.unroute((u) => IS_RDT(u.toString()));

  const refusal = "심은 거절: 그 하루 유형 모형을 찾지 못했습니다.";
  await page.route((u) => IS_RDT(u.toString()), (route) => route.fulfill({ status: 404, json: { detail: { code: "model_not_found", reason: refusal } } }));
  await page.locator(".itd-rs-k").selectOption("3");
  await page.locator(".itd-rdt-run").click();
  await expect(page.locator(".itd-rdt .tx-notice [data-server]")).toHaveText(refusal);
  await expect(page.locator(".itd-rdt .tx-notice")).toContainText("요청 거절");
  await expect(page.locator(".itd-rdt").getByRole("button", { name: "재시도" })).toHaveCount(0);   // 거절은 다시 물어도 같다
  await page.unroute((u) => IS_RDT(u.toString()));

  let fail = true;
  await page.route((u) => IS_RDT(u.toString()), async (route) => {
    if (fail) { fail = false; await route.fulfill({ status: 500, json: { detail: "서버 오류" } }); } else await route.continue();
  });
  await page.locator(".itd-rs-k").selectOption("2");
  await page.locator(".itd-rdt-run").click();
  const retry = page.locator(".itd-rdt").getByRole("button", { name: "재시도" });
  await expect(retry).toBeVisible();
  await retry.click();
  await expect(page.locator(".itd-rdt-result")).toBeVisible({ timeout: 60_000 });
});

test("모형이 없으면 안내 · 목록을 못 읽으면 서버 사유 · 운영에서 숨긴 합성 모형은 그 수의 사유", async ({ page }) => {
  await runJudge(page);
  const hidden = "심은 사유: 운영에서는 합성 분봉으로 학습한 모형을 보이지 않습니다.";
  await page.route((u) => IS_LIST(u.toString()) , (route) => route.fulfill({ json: {
    available: true, reason: null, models: [], hidden_synthetic: 2, hidden_reason: hidden, gate: { mock: false },
    limits: { tickers: 30, ticker_days: 2000, range_days: 366, bytes: 1, minutes: [5, 120], k: [4, 16], min_samples_per_type: 5 } } }));
  await page.locator(".itd-rdt-model").focus();                                   // 칸에 들어갈 때마다 다시 읽는다
  await expect(page.locator(".itd-rdt-no-models")).toHaveText(NO_MODELS);
  await expect(page.locator(".itd-rdt-list-note")).toHaveText(hidden);
  await expect(page.locator(".itd-rdt-model option")).toHaveText(["고르십시오"]);
  await page.unroute((u) => IS_LIST(u.toString()));
  const down = "심은 사유: 하루 유형 모형 저장소를 읽거나 쓰지 못했습니다(모형이 없는 것과 다릅니다).";
  await page.route((u) => IS_LIST(u.toString()), (route) => route.fulfill({ json: {
    available: false, reason: down, models: [], hidden_synthetic: null, hidden_reason: null, gate: { mock: true },
    limits: { tickers: 30, ticker_days: 2000, range_days: 366, bytes: 1, minutes: [5, 120], k: [4, 16], min_samples_per_type: 5 } } }));
  await page.locator(".itd-rs-k").focus();
  await page.locator(".itd-rdt-model").focus();
  await expect(page.locator(".itd-rdt-list-note")).toHaveText(down);
  await expect(page.locator(".itd-rdt-no-models")).toHaveCount(0);                // 못 읽은 것은 '없다'가 아니다
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 390px 에서 하루 유형 비율이 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    const { model } = await runJudge(page);
    await count(page, "3", model);
    const a = (await page.evaluate(contrastAudit(".itd-rdt"))) as AuditResult;
    expect(a.checked).toBeGreaterThan(20);
    expect(a.low, theme).toEqual([]);
    const v = (await page.evaluate(voiceAudit(".itd-rdt"))) as VoiceResult;
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    const rowH = () => page.locator(".itd-rdt-table tbody tr").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().height)));
    const wide = await rowH();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".itd-rdt-result")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    expect(await rowH(), "좁은 폭에서 표의 칸 글자가 줄을 바꿨다").toEqual(wide);
    const scroll = page.locator(".itd-rdt-scroll");
    expect(await scroll.evaluate((e) => e.scrollWidth > e.clientWidth)).toBe(true);    // 좁은 폭에서는 표가 옆으로 넘는다
    await scroll.focus();
    await page.keyboard.press("ArrowRight");
    await expect.poll(() => scroll.evaluate((e) => e.scrollLeft)).toBeGreaterThan(0);
  });
}
