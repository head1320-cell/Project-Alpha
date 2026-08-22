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

  // ① 신원 ② 할 일 — DOM 순서가 곧 위계다.
  // 맥락(유니버스·스냅샷·룰셋·팩)은 여기서 빠졌다: ContextStrip 이 layout 에서 바로 위에
  // 이미 렌더한다. 중복은 12 kB 였고(233→245, ADR 001 한도 초과) 같은 사실을 두 번
  // 적으면 어긋나는 순간 어느 쪽이 맞는지 알 수 없다.
  const order = await idx.evaluate((el) =>
    [...el.children].map((c) => c.className.split(" ")[0]));
  expect(order.slice(0, 2)).toEqual(["as-ri-id", "as-ri-next"]);
  // 맥락은 색인이 아니라 스트립이 책임진다 — 같은 페이지에 살아 있어야 한다.
  await expect(page.locator(".as-ctx .as-ctx-rules")).toBeVisible();

  // 주 CTA 는 정확히 하나 — 셸의 정책과 같은 소스를 쓴다.
  await expect(idx.locator(".as-ri-next-b")).toHaveCount(1);
  await expect(idx.locator(".as-ri-next-why")).toBeVisible();

  // 스터디가 서버에 있는 것처럼 보이면 안 된다.
  await expect(idx.getByText("브라우저 로컬")).toBeVisible();
  const badge = idx.locator(".tev-caution", { hasText: "브라우저 로컬" });
  await expect(badge.locator(".tev-r")).toContainText("이 브라우저에만");
});

// ═══════════════════════════════════════════════════════════════════════════════
// D6 — 런을 여는 durable URL
// ─────────────────────────────────────────────────────────────────────────────
// 승인 전까지 색인의 런 행은 클릭 불가였다. 서버는 `GET /research-runs/{id}` 로 단건을
// 주고 `reopenRun()` 도 있는데 **주소가 없어서** 링크할 데가 없었기 때문이다.
// 없는 기능을 있는 것처럼 보이게 하지 않으려고 링크를 달지 않았고, 이제 주소가 생겼다.
//
// ★durable 의 뜻★ 새로고침해도, 주소를 복사해 다시 열어도 같은 런을 가리켜야 한다.
// 그렇지 않으면 그냥 클릭 핸들러이지 URL 이 아니다.
// ═══════════════════════════════════════════════════════════════════════════════

test("D6: 색인의 런 행이 그 런을 여는 주소로 링크된다", async ({ page }) => {
  await stubRuns(page, 3);
  await page.goto("/allocation/overview", { waitUntil: "networkidle" });

  const link = page.locator(".as-ri-run .as-ri-run-id").first();
  const href = await link.getAttribute("href");
  expect(href, "런 행은 주소를 가져야 한다").toMatch(/\/allocation\/journal\?run=rr_/);
});

test("D6: 지목된 런이 저널에서 표시되고 새로고침을 견딘다", async ({ page }) => {
  await stubRuns(page, 3);
  const target = mkRun(2);
  await page.goto(`/allocation/journal?run=${target.run_id}`, { waitUntil: "networkidle" });

  // 표시된 행이 **그 런** 인지 확인한다.
  // 패널은 `r.name || r.run_id` 를 그리므로 이름이 있는 런은 raw id 를 보여 주지 않는다
  // (처음엔 id 로 단언했다가 여기서 걸렸다 — 기능이 아니라 단언이 틀렸다).
  const focused = page.locator(".as-rr-item.focused");
  await expect(focused, "지목된 행은 정확히 하나").toHaveCount(1);
  await expect(focused, "지목된 행이 대상 런이어야 한다").toContainText(target.name);

  // ★durable★ 새로고침해도 주소가 같은 런을 가리킨다.
  await page.reload({ waitUntil: "networkidle" });
  expect(page.url(), "주소가 같은 런을 계속 가리킨다").toContain(`run=${target.run_id}`);
});

test("D6: 링크가 가리키는 런이 목록에 없으면 조용히 넘어가지 않는다", async ({ page }) => {
  // 최근 목록에 없는 id — 사용자가 오래된 주소를 열었을 때다.
  await page.route("**/api/v1/research-runs?**", (r) => r.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ runs: [] }),
  }));
  await page.goto("/allocation/journal?run=rr_1600000000_00000000", { waitUntil: "networkidle" });

  // 아무 표시가 없으면 사용자는 링크가 고장났는지 자기가 잘못 눌렀는지 알 수 없다.
  await expect(page.locator(".as-rr-focus-missing")).toBeVisible();
  await expect(page.locator(".as-rr-focus-missing")).toContainText("최근 30건 목록에");
});
