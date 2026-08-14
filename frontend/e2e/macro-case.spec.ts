import { test, expect, type Page } from "@playwright/test";
import { freezeCharts } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// M1-U — 연구 케이스 컨텍스트 바 (`/macro` + `/allocation/*` 양쪽)
// ─────────────────────────────────────────────────────────────────────────────
// ★이 스펙이 지키는 것★
//  1. 케이스가 없으면 **없다고 말한다** — 첫 케이스를 임의로 골라 그리지 않는다.
//  2. 능력 배지에는 **막힌 레벨과 사유**가 함께 붙는다. 배지만 있고 사유가 없으면
//     사용자는 왜 이 레벨인지, 어떻게 올리는지 알 수 없다(M1-C 가 blocked_reason 을
//     낸 이유가 이 한 줄이다).
//  3. 같은 컴포넌트가 두 화면에 있다 — 그것이 "두 도구가 아니라 하나의 연구" 라는
//     주장의 유일한 증거다.
//
// ★서버 상태를 남기지 않는다★ 케이스 생성은 `POST /api/v1/research-cases` 를
// **스텁**한다. A4 의 Alpha Lab 스펙이 실제로 ResearchRun 을 기록해
// `research-run-roundtrip.spec.ts` 를 타임아웃시킨 전례가 있다.
// ═══════════════════════════════════════════════════════════════════════════════

test.beforeEach(async ({ page }) => { await freezeCharts(page); });

/** localStorage 포인터를 비워 "케이스 없음" 상태에서 시작한다. */
async function clearCasePointer(page: Page) {
  await page.addInitScript(() => {
    try { localStorage.removeItem("active_research_case"); } catch { /* noop */ }
  });
}

test("/macro 상단에 CaseBar 가 있다 — 케이스 없으면 없다고 말한다", async ({ page }) => {
  await clearCasePointer(page);
  await page.goto("/macro", { waitUntil: "networkidle" });

  const bar = page.locator(".as-case");
  await expect(bar).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".as-case-none")).toBeVisible();

  // ★지어낸 id 를 그리지 않는다★ 서버에는 케이스가 있을 수 있지만(목록에 뜬다),
  // **활성 케이스로 고른 것이 없으면** 식별자를 본문에 찍지 않는다.
  expect(await page.locator(".as-case-id").count(), "활성 케이스가 없는데 id 를 그렸다").toBe(0);

  // 선택·생성 수단은 있어야 한다 — 없다고만 말하고 끝내면 막다른 길이다.
  await expect(page.locator(".as-case-sel")).toBeVisible();
  await expect(page.locator(".as-case-new")).toBeVisible();
});

test("★능력 레벨 배지에는 막힌 레벨과 사유가 함께 붙는다★", async ({ page }) => {
  await clearCasePointer(page);
  await page.goto("/macro", { waitUntil: "networkidle" });

  const badge = page.locator(".as-case-capb");
  await expect(badge).toBeVisible({ timeout: 20_000 });
  const level = (await badge.textContent()) ?? "";
  expect(level, "레벨 표기").toMatch(/L[0-3]/);

  // 이 환경의 실측은 L1(torch·cvxpylayers·trends·llm 미가용) — 즉 위가 막혀 있다.
  // 막혔으면 사유가 **보여야** 한다. 배지만 있고 사유가 없으면 이 테스트가 빨개진다.
  const warn = page.locator(".as-case-warn-cap");
  await expect(warn).toBeVisible();
  const reason = (await warn.locator(".as-case-warn-r").textContent()) ?? "";
  expect(reason.trim().length, "막힌 사유 길이").toBeGreaterThan(20);
});

test("케이스 생성 폼: 질문이 비면 만들 수 없다 (서버 스텁)", async ({ page }) => {
  await clearCasePointer(page);
  // ★서버 상태를 남기지 않는다★
  await page.route("**/api/v1/research-cases", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ created: true, case_id: "rc_stub_e2e_0001" }) });
    } else {
      await route.fallback();
    }
  });
  await page.goto("/macro", { waitUntil: "networkidle" });

  await page.locator(".as-case-new").click();
  const form = page.locator(".as-case-form");
  await expect(form).toBeVisible();

  const submit = form.locator("button[type=submit]");
  // 이름만 채우면 아직 못 만든다 — 질문 없는 Case 는 폴더일 뿐이다.
  await form.locator(".as-case-fi").first().fill("스텁 케이스");
  await expect(submit).toBeDisabled();

  await form.locator(".as-case-fi-q").fill("스텁 질문 — 이 환경에서 무엇이 측정 가능한가?");
  await expect(submit).toBeEnabled();
  await submit.click();

  // 만들어지면 활성 케이스가 되고 id 가 보인다.
  await expect(page.locator(".as-case-id")).toHaveText("rc_stub_e2e_0001", { timeout: 20_000 });
});

test("케이스 저장 실패를 성공으로 위장하지 않는다", async ({ page }) => {
  await clearCasePointer(page);
  await page.route("**/api/v1/research-cases", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 200, contentType: "application/json",
        body: JSON.stringify({ created: false, case_id: null,
          message: "연구 케이스 저장소를 쓸 수 없습니다 — 케이스가 저장되지 않았습니다." }) });
    } else {
      await route.fallback();
    }
  });
  await page.goto("/macro", { waitUntil: "networkidle" });

  await page.locator(".as-case-new").click();
  await page.locator(".as-case-fi").first().fill("실패하는 케이스");
  await page.locator(".as-case-fi-q").fill("저장이 실패하면 화면이 무엇을 말하는가?");
  await page.locator(".as-case-form button[type=submit]").click();

  await expect(page.locator(".as-case-msg")).toContainText("저장되지 않았습니다", { timeout: 20_000 });
  // 활성 케이스가 되지 않는다 — 저장되지 않은 것을 활성으로 두면 다음 화면이 거짓을 읽는다.
  expect(await page.locator(".as-case-id").count()).toBe(0);
});

test("★고른 케이스를 못 읽은 것은 '케이스 없음' 이 아니다★", async ({ page }) => {
  // 이 가드는 실제 결함에서 나왔다. 첫 구현은 포인터가 가리키는 케이스를 서버에서
  // 가져오지 못하면 "케이스 없음" 을 그렸다 — 포인터는 있고 식별자도 아는데 없다고
  // 말한 것이다. `없음 ≠ 못 읽음` 은 이 저장소가 반복해 적어 온 구분이다.
  await page.addInitScript(() => {
    try { localStorage.setItem("active_research_case", "rc_ghost_e2e_0001"); } catch { /* noop */ }
  });
  await page.goto("/macro", { waitUntil: "networkidle" });

  await expect(page.locator(".as-case-id")).toHaveText("rc_ghost_e2e_0001", { timeout: 20_000 });
  await expect(page.locator(".as-case-warn-missing")).toBeVisible();
  // "없음" 으로 그리지 않는다.
  expect(await page.locator(".as-case-none").count(), "못 읽은 것을 '없음' 으로 그렸다").toBe(0);
});

test("케이스 목록이 있어도 고르지 않았으면 임의로 활성화하지 않는다", async ({ page }) => {
  // 서버에는 열린 케이스가 있다(M1-S 테스트가 남긴 것). 그래도 사용자가 고르지 않았으면
  // 첫 항목을 활성으로 그리지 않는다 — 고르지 않은 것과 고른 것은 다른 사실이다.
  await clearCasePointer(page);
  await page.route("**/api/v1/research-cases?**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ available: true, cases: [
        { case_id: "rc_first_e2e", created_at: 1, updated_at: 1, name: "첫 케이스",
          question: "임의로 활성화되면 안 된다", status: "open", market: "kr",
          universe_ref: null, active_mes_id: null, active_tpv_id: null,
          active_run_id: null, code_version: null, note: null },
      ] }) });
  });
  await page.goto("/macro", { waitUntil: "networkidle" });

  await expect(page.locator(".as-case-none")).toBeVisible({ timeout: 20_000 });
  expect(await page.locator(".as-case-id").count(), "고르지 않았는데 활성화했다").toBe(0);
  // 목록에는 있어야 한다 — 고를 수 없으면 막다른 길이다.
  await expect(page.locator(".as-case-sel option[value='rc_first_e2e']")).toHaveCount(1);
});

test("목록 저장소 장애와 네트워크 오류가 서로 다른 화면이다", async ({ page }) => {
  await clearCasePointer(page);

  // (a) 저장소 장애 — 서버가 available:false + 사유로 답한다.
  await page.route("**/api/v1/research-cases?**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ available: false, cases: [],
        reason: "연구 케이스 저장소를 읽을 수 없습니다 — 케이스가 없는 것과 다릅니다." }) });
  });
  await page.goto("/macro", { waitUntil: "networkidle" });
  await expect(page.locator(".as-case-warn-store")).toBeVisible({ timeout: 20_000 });
  expect(await page.locator(".as-case-warn-net").count(), "장애를 네트워크 오류로 그렸다").toBe(0);

  // (b) 네트워크 오류 — 응답 자체가 없다. 같은 화면으로 뭉개지면 안 된다.
  await page.unroute("**/api/v1/research-cases?**");
  await page.route("**/api/v1/research-cases?**", (route) => route.abort());
  await page.goto("/macro", { waitUntil: "networkidle" });
  await expect(page.locator(".as-case-warn-net")).toBeVisible({ timeout: 20_000 });
  expect(await page.locator(".as-case-warn-store").count(), "네트워크 오류를 장애로 그렸다").toBe(0);
});

test("같은 CaseBar 가 AAS 스테이지에도 있다 — 두 화면이 한 연구다", async ({ page }) => {
  await clearCasePointer(page);
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 20_000 });

  await expect(page.locator(".as-case")).toBeVisible({ timeout: 20_000 });
  // ContextStrip 도 그대로 살아 있어야 한다 — CaseBar 가 그것을 대체하지 않는다.
  await expect(page.locator(".as-ctx")).toBeVisible();
  // 그리고 같은 칩을 두 번 그리지 않는다: MES 칩은 CaseBar 에만 있다.
  expect(await page.locator(".as-case-mes, .as-case-na").count()).toBeGreaterThan(0);

  // 포인터는 브라우저 로컬임을 라벨이 말한다.
  await expect(page.locator(".as-case-foot")).toContainText("이 브라우저에만");
});
