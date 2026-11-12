import { test, expect, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * 카드 본문 활용 (2026-11-12 · 설계 `docs/superpowers/specs/2026-11-12-canvas-card-body-design.md`)
 * 거는 것(짝으로 항상-표시·항상-침묵을 배제):
 *  ① 그림 없는 종류의 결과 자리(가까이) = ★서버 `explain.facts` 앞 줄 그대로★ — 응답을 바꾸면 글이 바뀐다(화면이 지어내지 않는다) ·
 *     그림이 있는 노드에는 없다(짝) · 사실 줄이 없으면 자리도 없다(짝)
 *  ② 계산 전에는 안내만 — 사실 줄 자리는 없다 · ★보통 확대(기본으로 열리는 화면)에서도 사실 줄·작은 그림이 보인다★ — '보기 → 카드에 결과 표시'를 끄면
 *     예전처럼 가까이에서만(짝)
 *  ③ 멀리(< 0.55): 설정 요약 한 줄 + 작은 그림(계산된 노드 전부) + 증거 칩 · 끄면 예전처럼 이름·값만(짝) ·
 *     끈 채로도 '그림 고정'한 노드는 그림이 보인다 · 켬/끔은 이 브라우저에 남는다
 *  ④ 상자는 그대로 — 켜든 끄든 카드 높이가 같고(자리 고정), 세 확대 모두 내용이 상자 밖으로 넘치지 않는다 · 멀리 글자는 화면 11px 아래로 안 줄어든다
 *  ⑤ 라이트/다크 AA · 문서(작업 중 저장)는 바이트 그대로(보기 설정은 문서가 아니다)
 */

type Trust = { state: string; text: string; kind?: string };
type NodeRes = { status: string; glance?: { kind: string } | null;
                 explain?: { facts?: string[]; trust?: Trust[]; headline?: { value: number | null } | null } };
type RunBody = { nodes: Record<string, NodeRes> };

const node = (page: Page, id: string) => page.locator(`.pg-node[data-node-id="${id}"]`);
const canvas = (page: Page) => page.locator(".pg-canvas");
const FACTS_MAX = 3;                       // 카드가 보이는 사실 줄 수(넘으면 자세히 탭)

async function openCanvas(page: Page) {
  await page.goto("/allocation", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await page.locator(".react-flow__controls-fitview").click();
}
async function run(page: Page): Promise<RunBody> {
  const resp = page.waitForResponse((r) => r.url().includes("/allocation/graph/run"), { timeout: 120_000 });
  await page.locator(".pg-run").click();
  const body = (await (await resp).json()) as RunBody;
  await expect(page.locator(".pg-summary:not(.pg-summary--err):not(.pg-summary--stale)")).toContainText("완료", { timeout: 30_000 });
  return body;
}
async function patchRun(page: Page, fn: (body: RunBody) => void) {
  await page.unroute("**/api/v1/allocation/graph/run**");
  await page.route("**/api/v1/allocation/graph/run**", async (route) => {
    const res = await route.fetch();
    const body = (await res.json()) as RunBody;
    fn(body);
    await route.fulfill({ response: res, json: body });
  });
}
async function zoomTo(page: Page, level: "far" | "mid" | "near") {
  for (let i = 0; i < 14; i++) {
    const z = await canvas(page).getAttribute("data-zoom");
    if (z === level) return;
    const wantIn = level === "near" || (level === "mid" && z === "far");
    await page.locator(wantIn ? ".react-flow__controls-zoomin" : ".react-flow__controls-zoomout").click();
    await page.waitForTimeout(120);
  }
  await expect(canvas(page)).toHaveAttribute("data-zoom", level);
}
async function toggleResults(page: Page) {
  await page.locator(".pg-view-open").click();
  await page.locator('.pg-view-menu [data-view="card-results"]').click();
}
/** 그림이 없는데 계산은 된 노드 하나 · 그림이 있는 노드 하나 — 종류 이름을 박지 않고 응답에서 고른다(공허하지 않게 둘 다 있어야 한다). */
function pick(body: RunBody) {
  const ok = Object.entries(body.nodes).filter(([, r]) => r.status === "ok");
  const plain = ok.find(([, r]) => !r.glance && (r.explain?.facts?.length ?? 0) > 0)?.[0];
  const drawn = ok.find(([, r]) => !!r.glance)?.[0];
  expect([!!plain, !!drawn], "그림 없는 노드와 있는 노드가 둘 다 있다").toEqual([true, true]);
  return { plain: plain!, drawn: drawn! };
}
const heights = (page: Page) => page.evaluate(() => Object.fromEntries(
  Array.from(document.querySelectorAll<HTMLElement>(".pg-node")).map((el) => [el.dataset.nodeId, el.offsetHeight])));
const overflowing = (page: Page) => page.evaluate(() =>
  Array.from(document.querySelectorAll<HTMLElement>(".pg-node")).filter((el) => {
    const box = el.getBoundingClientRect();
    return Array.from(el.querySelectorAll<HTMLElement>(".pg-node-far, .pg-node-far *, .pg-node-slot, .pg-node-facts, .pg-node-glance")).some((c) => {
      const r = c.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && (r.bottom > box.bottom + 1 || r.right > box.right + 1 || r.left < box.left - 1 || r.top < box.top - 1);
    });
  }).map((el) => el.dataset.nodeId));

test("① 그림 없는 종류의 결과 자리 = 서버 사실 줄 그대로 · 그림 있는 노드엔 없다(짝) · 응답을 바꾸면 글이 바뀐다", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const { plain, drawn } = pick(body);
  await zoomTo(page, "near");
  const facts = body.nodes[plain].explain!.facts!;
  await expect(node(page, plain).locator(".pg-node-facts li")).toHaveText(facts.slice(0, FACTS_MAX));
  await expect(node(page, plain).locator(".pg-node-slot-empty"), "계산된 카드에 '계산하면…' 안내가 남지 않는다").toHaveCount(0);
  await expect(node(page, drawn).locator(".pg-node-facts"), "그림이 있는 노드는 그림만").toHaveCount(0);
  await expect(node(page, drawn).locator(".pg-node-glance")).toBeVisible();

  // 짝 — 서버 문장을 바꾸면 카드가 따라 바뀐다 · 사실 줄이 없으면 자리도 없다.
  const SAID = "서버가 보낸 문장 하나입니다.";
  await patchRun(page, (b) => { b.nodes[plain].explain!.facts = [SAID]; });
  await run(page);
  await expect(node(page, plain).locator(".pg-node-facts li")).toHaveText([SAID]);
  await patchRun(page, (b) => { b.nodes[plain].explain!.facts = []; });
  await run(page);
  await expect(node(page, plain).locator(".pg-node-facts")).toHaveCount(0);
});

test("② 계산 전에는 안내만 · 보통 확대(기본 화면)에서도 사실 줄·작은 그림 — 끄면 가까이에서만(짝)", async ({ page }) => {
  await openCanvas(page);
  await zoomTo(page, "near");
  await expect(page.locator(".pg-node-facts")).toHaveCount(0);
  await expect(page.locator(".pg-node-slot-empty").first()).toBeVisible();
  const body = await run(page);
  const { plain, drawn } = pick(body);
  await zoomTo(page, "near");
  await expect(node(page, plain).locator(".pg-node-facts")).toBeVisible();
  // 보통 확대 — 처음 열리는 화면. 결과 자리가 비지 않는다.
  await zoomTo(page, "mid");
  await expect(canvas(page)).toHaveAttribute("data-card-results", "1");
  await expect(node(page, plain).locator(".pg-node-facts")).toBeVisible();
  await expect(node(page, drawn).locator(".pg-node-glance")).toBeVisible();
  // 짝 — 끄면 예전 보통 확대(그림·사실 줄 없음). 가까이에서는 꺼도 보인다(원래 그랬다).
  await toggleResults(page);
  await expect(canvas(page)).toHaveAttribute("data-card-results", "0");
  await expect(node(page, plain).locator(".pg-node-facts")).toBeHidden();
  await expect(node(page, drawn).locator(".pg-node-glance")).toBeHidden();
  await zoomTo(page, "near");
  await expect(node(page, plain).locator(".pg-node-facts")).toBeVisible();
  await expect(node(page, drawn).locator(".pg-node-glance")).toBeVisible();
});

test("③ 멀리: 설정 요약 · 작은 그림 · 증거 칩 — 끄면 이름·값만(짝) · 고정한 노드는 꺼도 보인다 · 켬/끔은 브라우저에 남는다", async ({ page }) => {
  await openCanvas(page);
  const body = await run(page);
  const { drawn } = pick(body);
  await zoomTo(page, "mid");
  // 노드마다 — 설정 요약(이름과 다를 때만 요약이다) · 근거 칩 글. 먼 보기는 이것과 같은 사실을 보여야 한다.
  const mid = await page.evaluate(() => Object.fromEntries(Array.from(document.querySelectorAll<HTMLElement>(".pg-node")).map((el) => [el.dataset.nodeId!, {
    plain: (el.querySelector(".pg-node-plain")?.textContent ?? "").trim(), t: (el.querySelector(".pg-node-t")?.textContent ?? "").trim(),
    chips: Array.from(el.querySelectorAll(".pg-node-ev .pg-tag")).map((c) => c.textContent ?? "") }])));
  const withSum = Object.entries(mid).filter(([, m]) => m.t && m.t !== m.plain).map(([id]) => id);
  const withChips = Object.entries(mid).filter(([, m]) => m.chips.length > 0).map(([id]) => id);
  expect([withSum.length > 0, withChips.length > 0], "요약 있는 노드 · 칩 있는 노드가 있다(공허하지 않게)").toEqual([true, true]);

  await zoomTo(page, "far");
  await expect(canvas(page)).toHaveAttribute("data-card-results", "1");
  const d = node(page, drawn);
  await expect(d.locator(".pg-node-glance")).toBeVisible();
  for (const [id, m] of Object.entries(mid)) {
    const sum = node(page, id).locator(".pg-node-far-sum");
    if (m.t && m.t !== m.plain) { await expect(sum, id).toBeVisible(); await expect(sum, id).toHaveText(m.t); }
    else await expect(sum, `${id} — 요약이 없으면 줄도 없다(이름을 두 번 적지 않는다)`).toHaveCount(0);
    // 칩 — 같은 사실 · 같은 순서(짧은 이름으로 적되 원문은 data-full 에).
    const far = await node(page, id).locator(".pg-node-far-ev .pg-far-chip").evaluateAll((els) => els.map((e) => [e.getAttribute("data-full"), (e.textContent ?? "").trim().length > 0]));
    expect(far, `${id} 먼 보기 칩`).toEqual(m.chips.map((c) => [c, true]));
  }
  await expect(node(page, withChips[0]).locator(".pg-node-far-ev")).toBeVisible();
  const s0 = node(page, withSum[0]);

  // 짝 — 끄면 예전 먼 보기(이름 + 값 하나).
  await toggleResults(page);
  await expect(canvas(page)).toHaveAttribute("data-card-results", "0");
  await expect(d.locator(".pg-node-far-name")).toBeVisible();
  await expect(d.locator(".pg-node-far-v")).toBeVisible();
  await expect(s0.locator(".pg-node-far-sum")).toBeHidden();
  await expect(d.locator(".pg-node-glance")).toBeHidden();
  await expect(node(page, withChips[0]).locator(".pg-node-far-ev")).toBeHidden();

  // 끈 채로도 '그림 고정'은 그대로 동작한다.
  await zoomTo(page, "mid");
  await d.click();
  await page.locator(".pg-pin").click();
  await zoomTo(page, "far");
  await expect(d.locator(".pg-node-glance")).toBeVisible();

  // 이 브라우저에 남는다 — 다시 열어도 끈 채.
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.locator(".pg-node").first()).toBeVisible({ timeout: 30_000 });
  await expect(canvas(page)).toHaveAttribute("data-card-results", "0");
  await page.locator(".pg-view-open").click();
  await expect(page.locator('.pg-view-menu [data-view="card-results"]')).toHaveAttribute("aria-checked", "false");
});

test("④ 상자는 그대로 — 켜든 끄든 카드 높이가 같다 · 세 확대 모두 안 넘친다 · 멀리 글자는 화면 11px 이상", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  const at: Record<string, Record<string, number>> = {};
  for (const level of ["near", "mid", "far"] as const) {
    await zoomTo(page, level);
    await page.waitForTimeout(200);
    expect(await overflowing(page), `${level} — 상자 밖으로 넘친 카드`).toEqual([]);
    at[level] = await heights(page) as Record<string, number>;
  }
  expect(at.far, "멀리 = 보통(같은 상자)").toEqual(at.mid);
  expect(at.near, "가까이 = 보통(같은 상자)").toEqual(at.mid);
  // 멀리 — 새로 보이는 글자도 화면 11px 바닥을 지킨다.
  const px = await page.evaluate(() => {
    const z = Number(getComputedStyle(document.querySelector(".pg-canvas")!).getPropertyValue("--pg-z"));
    return Array.from(document.querySelectorAll<HTMLElement>(".pg-node-far-sum, .pg-node-far-ev .pg-far-chip"))
      .filter((el) => el.getBoundingClientRect().height > 0).map((el) => parseFloat(getComputedStyle(el).fontSize) * z);
  });
  expect(px.length, "잰 글자가 있다").toBeGreaterThan(0);
  expect(Math.min(...px)).toBeGreaterThanOrEqual(10.9);
  // 끄면 — 높이는 그대로(자리 고정).
  await toggleResults(page);
  expect(await heights(page), "끈 뒤에도 같은 상자").toEqual(at.far);
  expect(await overflowing(page)).toEqual([]);
});

test("⑤ 보기 설정은 문서가 아니다 — 켜고 꺼도 작업 중 문서는 바이트 그대로", async ({ page }) => {
  await openCanvas(page);
  await run(page);
  const wip = () => page.evaluate(() => sessionStorage.getItem("alpha_pg_wip"));
  const before = await wip();
  expect(before, "작업 중 문서가 있다").toBeTruthy();
  await toggleResults(page);
  await toggleResults(page);
  await toggleResults(page);
  expect(await wip()).toBe(before);
});

for (const theme of ["light", "dark"] as const) {
  test(`⑤ 대비 AA (${theme}) — 사실 줄(가까이) · 먼 보기의 요약·칩`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await openCanvas(page);
    if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
    const body = await run(page);
    const { plain, drawn } = pick(body);
    await zoomTo(page, "near");
    await expect(node(page, plain).locator(".pg-node-facts")).toBeVisible();
    let r = await page.evaluate<AuditResult>(contrastAudit(`.pg-node[data-node-id="${plain}"] .pg-node-facts`));
    expect(r.low, `사실 줄 ${JSON.stringify(r.low)}`).toEqual([]);
    await zoomTo(page, "far");
    await expect(page.locator(".pg-node-far-ev").first()).toBeVisible();
    await expect(page.locator(".pg-node-far-sum").first()).toBeVisible();
    r = await page.evaluate<AuditResult>(contrastAudit(".pg-canvas .react-flow__nodes"));
    expect(r.low, `먼 보기 ${JSON.stringify(r.low)}`).toEqual([]);
    void drawn;
  });
}
