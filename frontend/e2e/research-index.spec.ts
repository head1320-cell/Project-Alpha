import { test, expect } from "@playwright/test";
import { trackErrors, uniq } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// 연구 색인 (00 OVERVIEW) — UI/UX 현대화 P4
// ─────────────────────────────────────────────────────────────────────────────
// 세 가지 데이터 상태를 **만들어서** 검사한다. 콜드 스타트만 보면 "런 0건" 경로밖에
// 못 보고, 목록이 실제로 그려지는지는 영영 검사되지 않는다(P3 에서 같은 함정을 겪었다).
//
// ★가장 중요한 단언★
// 런이 없을 때 화면이 "0" 이라고 적지 않는 것. 0 은 측정 결과이고 없음은 측정 이전이다.
// 리서치 도구에서 이 둘을 같은 글자로 적으면 없는 근거를 있는 것처럼 보이게 만든다.
// ═══════════════════════════════════════════════════════════════════════════════

const RUNS_URL = "**/api/v1/research-runs?**";

const mkRun = (i: number) => ({
  run_id: `rr_17000000${String(i).padStart(2, "0")}_a1b2c3d4`,
  created_at: 1_700_000_000 + i * 3600,
  kind: "allocation",
  name: `테스트 런 ${i}`,
  code_version: "dev",
  parent_run_id: null,
  note: null,
  snapshot: { coverage: { source: i % 2 === 0 ? "mock" : "real" } },
});

const stubRuns = (page: import("@playwright/test").Page, n: number) =>
  page.route(RUNS_URL, (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ runs: Array.from({ length: n }, (_, i) => mkRun(i + 1)) }),
  }));

test("색인: 런 0건이면 '없음'이라고 적고, 0 이라고 적지 않는다", async ({ page }) => {
  const sink = trackErrors(page);
  await stubRuns(page, 0);
  await page.goto("/allocation/overview", { waitUntil: "networkidle" });

  const idx = page.locator(".as-ri");
  await expect(idx).toBeVisible();

  // 빈 상태는 사실을 말한다 — 지어낸 0 이 아니다.
  await expect(idx.locator(".tstate-empty")).toContainText("아직 기록된 런이 없습니다");
  await expect(idx.locator(".as-ri-run")).toHaveCount(0);

  // ★"0건"·"0개" 같은 표기가 최근 런 영역에 나오면 안 된다★
  const sec = await idx.locator(".as-ri-sec").first().innerText();
  expect(sec, "없음을 0 으로 적지 않는다").not.toMatch(/\b0\s*(건|개|runs?)\b/i);

  expect(uniq(sink.pageErrors), "page errors").toEqual([]);
});

test("색인: 런 1건이 신원과 함께 그려진다", async ({ page }) => {
  await stubRuns(page, 1);
  await page.goto("/allocation/overview", { waitUntil: "networkidle" });

  const rows = page.locator(".as-ri-run");
  await expect(rows).toHaveCount(1);
  await expect(rows.first().locator(".as-ri-run-id")).toContainText("rr_");
  await expect(rows.first().locator(".as-ri-run-nm")).toContainText("테스트 런 1");
  // 합성 데이터 런은 그 사실을 행에 적는다.
  await expect(rows.first().locator(".as-ri-run-mock")).toHaveCount(0); // i=1 → real
});

test("색인: 런 50건에서도 무너지지 않고 합성 표기가 유지된다", async ({ page }) => {
  await stubRuns(page, 50);
  await page.goto("/allocation/overview", { waitUntil: "networkidle" });

  await expect(page.locator(".as-ri-run")).toHaveCount(50);
  // 짝수 인덱스는 mock — 절반이 합성 표기를 달고 있어야 한다.
  expect(await page.locator(".as-ri-run-mock").count(), "합성 표기").toBe(25);
});

test("색인: 조회 실패는 '런 없음'이 아니라 '조회 불가'로 구별된다", async ({ page }) => {
  // ★이게 이 스펙의 핵심 구분이다★ DB 가 죽어서 못 읽은 것과 런이 없는 것은 다른 사실이다.
  // 둘을 같은 빈 상태로 그리면 사용자는 자기 연구 기록이 사라졌다고 오해한다.
  await page.route(RUNS_URL, (r) => r.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
  await page.goto("/allocation/overview", { waitUntil: "networkidle" });

  const un = page.locator(".as-ri .tstate-unavail");
  await expect(un).toBeVisible();
  await expect(un).toContainText("런이 없다는 뜻은 아닙니다");
  await expect(page.locator(".as-ri .tstate-empty")).toHaveCount(0);
});

test("색인: 신원 → 맥락 → 할 일 하나 순서로 놓이고, 스터디는 브라우저 로컬로 표시된다", async ({ page }) => {
  await stubRuns(page, 2);
  await page.goto("/allocation/overview", { waitUntil: "networkidle" });
  const idx = page.locator(".as-ri");

  // ① 신원 ② 맥락 ③ 할 일 — DOM 순서가 곧 위계다.
  const order = await idx.evaluate((el) =>
    [...el.children].map((c) => c.className.split(" ")[0]));
  expect(order.slice(0, 3)).toEqual(["as-ri-id", "as-ri-ctx", "as-ri-next"]);

  // 주 CTA 는 정확히 하나 — 셸의 정책과 같은 소스를 쓴다.
  await expect(idx.locator(".as-ri-next-b")).toHaveCount(1);
  await expect(idx.locator(".as-ri-next-why")).toBeVisible();

  // 스터디가 서버에 있는 것처럼 보이면 안 된다.
  await expect(idx.getByText("브라우저 로컬")).toBeVisible();
  const badge = idx.locator(".tev-caution", { hasText: "브라우저 로컬" });
  await expect(badge.locator(".tev-r")).toContainText("이 브라우저에만");
});
