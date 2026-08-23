import { expect, test, type Page } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// R0-S — 연구 기록의 상태는 넷이다: 로딩 · 기록 없음 · 저장소 장애 · 네트워크 오류
// ─────────────────────────────────────────────────────────────────────────────
// 실측된 결함은 세 층이 겹친 것이었다:
//   `research_runs.py:154`  `except: return []`     저장소 장애 = 빈 목록
//   `research_routes.py:53` `{"runs": […]}`          가용성 정보 없음
//   `ResearchRunsPanel.tsx:98` `.catch(() => null)`  네트워크 오류 = null → "런 없음"
// 연구 기록이 **사라진 것처럼** 보이는 것은 이 플랫폼에서 가장 겁나는 화면이다.
//
// ★1·2 는 반드시 짝으로 읽어야 한다★ "장애를 빈 목록으로 말하지 않는다" 를 만족시키려고
// 빈 상태 자체를 없애면 안 된다 — 기록이 없다는 것도 사용자가 알아야 하는 사실이다.
// ═══════════════════════════════════════════════════════════════════════════════

const RUNS_API = "**/api/backend/api/v1/research-runs**";

async function seedPortfolio(page: Page) {
  await page.addInitScript(() => {
    const KEY = "alpha_alloc_wip";
    if (sessionStorage.getItem(KEY)) return;
    sessionStorage.setItem(KEY, JSON.stringify({
      holdings: [{ code: "005930", name: "삼성전자", weight: 60 },
                 { code: "000660", name: "SK하이닉스", weight: 40 }],
      views: [], model: "bl",
    }));
  });
}

/** 09 JOURNAL 에 RESEARCH RUNS 패널이 있다. */
async function openJournal(page: Page) {
  await page.goto("/allocation/journal", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".as-card").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(2_000);
}

// ── 1. ★저장소 장애를 "런 없음"으로 말하지 않는다★ ───────────────────────────
test("★저장소 장애는 '기록된 런 없음'이 아니다★", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);
  // 서버가 스스로 "저장소를 못 읽었다" 고 답하는 상황(R0-S 가 만든 응답 모양).
  await page.route(RUNS_API, (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          status: 200, contentType: "application/json",
          body: JSON.stringify({ available: false, runs: [],
                                 reason: "연구 기록 저장소를 읽을 수 없습니다 — 기록이 없는 것과 다릅니다." }),
        })
      : route.continue());
  await openJournal(page);

  const down = page.locator(".as-rr-storage-down");
  await expect(down, "저장소 장애를 화면이 말하지 않는다").toBeVisible({ timeout: 20_000 });
  await expect(down).toContainText("저장소");
  await expect(down, "장애인데 '없다'로 읽히는 문장을 쓰고 있다").toContainText("기록이 없는 것이 아닙니다");
  // ★핵심★ 빈 상태 문구가 함께 뜨면 사용자는 기록이 사라졌다고 읽는다.
  await expect(page.locator(".as-rr-empty"),
    "저장소 장애인데 '기록된 런 없음' 을 함께 그렸다").toHaveCount(0);
});

// ── 2. 빈 목록은 여전히 빈 목록이다 (1번의 짝) ──────────────────────────────
test("기록이 없으면 '기록된 런 없음' 이라고 말한다", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);
  await page.route(RUNS_API, (route) =>
    route.request().method() === "GET"
      ? route.fulfill({ status: 200, contentType: "application/json",
                        body: JSON.stringify({ available: true, runs: [] }) })
      : route.continue());
  await openJournal(page);

  await expect(page.locator(".as-rr-empty"),
    "기록이 없는데 그 사실을 말하지 않는다").toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-rr-storage-down")).toHaveCount(0);
  await expect(page.locator(".as-rr-network-down")).toHaveCount(0);
});

// ── 3. 네트워크 오류는 저장소 장애와도, 빈 목록과도 다른 화면이다 ───────────
test("★응답을 못 받으면 네트워크 오류라고 말한다 (런 없음이 아니라)★", async ({ page }) => {
  test.setTimeout(120_000);
  await seedPortfolio(page);
  await page.route(RUNS_API, (route) =>
    route.request().method() === "GET" ? route.abort("failed") : route.continue());
  await openJournal(page);
  await page.waitForTimeout(3_000);   // react-query 재시도 1회

  await expect(page.locator(".as-rr-network-down"),
    "응답을 못 받았는데 화면이 그 사실을 말하지 않는다").toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-rr-empty"),
    "네트워크 오류인데 '기록된 런 없음' 으로 그렸다").toHaveCount(0);
});

// ── 4. 세 문장이 서로 다르다 (같은 문구를 돌려쓰면 구분이 아니다) ───────────
test("세 상태의 문구가 서로 다르다", async ({ page }) => {
  test.setTimeout(180_000);
  const texts: string[] = [];

  for (const [body, sel] of [
    [JSON.stringify({ available: false, runs: [], reason: "저장소 장애 사유" }), ".as-rr-storage-down"],
    [JSON.stringify({ available: true, runs: [] }), ".as-rr-empty"],
  ] as const) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await seedPortfolio(page);
    await page.route(RUNS_API, (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ status: 200, contentType: "application/json", body })
        : route.continue());
    await openJournal(page);
    texts.push((await page.locator(sel).innerText()).trim());
  }

  expect(texts.length, "두 상태를 모두 잡지 못했다").toBe(2);
  expect(texts[0], "저장소 장애와 빈 목록이 같은 문장이다 — 구분이 아니다").not.toBe(texts[1]);
});
