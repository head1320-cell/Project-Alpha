import { test, expect } from "@playwright/test";

// ═══════════════════════════════════════════════════════════════════════════════
// 저널 재현 사슬 (UI/UX 현대화 P9)
// ─────────────────────────────────────────────────────────────────────────────
// 저널 항목이 저장하는 것은 `run_id` 뿐이다 — 스냅샷·룰셋 버전·팩 해시는 **런 쪽**에 있다.
// 그래서 사슬은 run_id 를 축으로 이어진다: 결정 → 런 → 데이터 출처 → 코드 버전.
//
// ★사슬이 끊긴 항목이 이 스펙의 핵심★
// run_id 가 없는 저널 항목은 "조금 부족한 기록" 이 아니라 **나중에 검증할 수 없는 결정**이다.
// 예전에는 흐린 각주로 " · 런 미연결" 이라고만 적혀 있었다. 지금은 사유가 붙은 경고다.
//
// 세 갈래를 전부 stub 으로 만든다 — 콜드 스타트에는 서버 저널이 비어 있어서, 만들지 않으면
// 이 스펙 전체가 0회 루프로 통과한다(P3 에서 겪은 실패 양식).
// ═══════════════════════════════════════════════════════════════════════════════

const JOURNAL_URL = "**/api/v1/allocation/journal";
const RUNS_URL = "**/api/v1/research-runs?**";

const LINKED = "rr_1700000001_aaaabbbb";
const ORPHAN = "rr_1700000099_deadbeef";   // 저널은 참조하지만 런 목록에는 없다

const entry = (id: string, runId: string | null, title: string) => ({
  entry_id: id, run_id: runId, title, created_at: 1_700_000_500,
  record: { thesis: "테제", counter_arguments: "반론", decision: "결정", next_experiment: "다음" },
  attribution: null, review: null,
});

async function stub(page: import("@playwright/test").Page) {
  await page.route(JOURNAL_URL, (r) => {
    if (r.request().method() !== "GET") return r.continue();
    return r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ entries: [
        entry("je_1", LINKED, "런이 연결된 결정"),
        entry("je_2", null, "런이 없는 결정"),
        entry("je_3", ORPHAN, "런을 찾을 수 없는 결정"),
      ] }),
    });
  });
  await page.route(RUNS_URL, (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ runs: [{
      run_id: LINKED, created_at: 1_700_000_000, kind: "allocation", name: "연결된 런",
      code_version: "abc1234", parent_run_id: null, note: null,
      snapshot: { coverage: { source: "mock" } },
    }] }),
  }));
}

test("저널: 런이 연결된 결정은 데이터 출처와 코드 버전까지 이어진다", async ({ page }) => {
  await stub(page);
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });

  const row = page.locator(".as-jr-entry", { hasText: "런이 연결된 결정" });
  await expect(row).toBeVisible();
  const chain = row.locator(".as-dj-chain");
  await expect(chain).toBeVisible();
  await expect(chain).toContainText(LINKED);
  // 합성 데이터로 계산된 런임을 사슬에서 바로 읽을 수 있어야 한다.
  await expect(chain).toContainText("합성(mock)");
  await expect(chain).toContainText("abc1234");
});

test("★저널: 런이 없는 결정은 각주가 아니라 경고다★", async ({ page }) => {
  await stub(page);
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });

  const row = page.locator(".as-jr-entry", { hasText: "런이 없는 결정" });
  const warn = row.locator(".tev-caution");
  await expect(warn).toBeVisible();
  await expect(warn).toContainText("재현 좌표 없음");
  // 사유가 보이는 텍스트여야 한다 — 왜 문제인지 말하지 않으면 경고가 아니라 장식이다.
  await expect(warn.locator(".tev-r")).toContainText("재현·귀인이 성립하지 않습니다");
});

test("저널: 참조한 런을 목록에서 못 찾으면 지어내지 않고 그 사실을 적는다", async ({ page }) => {
  await stub(page);
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });

  const row = page.locator(".as-jr-entry", { hasText: "런을 찾을 수 없는 결정" });
  await expect(row.locator(".tev-caution")).toContainText("런 조회 불가");
  // run_id 자체는 여전히 보여 준다 — 사용자가 직접 찾아갈 수 있는 유일한 좌표다.
  await expect(row.locator(".as-dj-chain")).toContainText(ORPHAN);
});

test("저널: 목록 응답에 없는 값(룰셋 버전·팩 해시)을 채워 넣지 않는다", async ({ page }) => {
  await stub(page);
  await page.goto("/allocation/journal", { waitUntil: "networkidle" });

  const chain = page.locator(".as-jr-entry", { hasText: "런이 연결된 결정" }).locator(".as-dj-chain");
  // 목록 응답(research_runs.py::list_runs)은 inputs 를 빼고 온다 — 여기에 버전·해시는 없다.
  // 그러니 화면도 그것을 아는 척하지 않고, 어디서 볼 수 있는지만 말해야 한다.
  await expect(chain.locator(".as-dj-more")).toContainText("이 런을 열면");
  await expect(chain).not.toContainText("v1");
});
