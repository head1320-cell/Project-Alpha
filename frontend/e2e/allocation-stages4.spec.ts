import { test, expect, type Page } from "@playwright/test";
import { contrastAudit, type AuditResult } from "./helpers";

// ═══════════════════════════════════════════════════════════════════════════════
// A8 — 0M 국면 분석의 설명가능성 · 시간맥락 · 전환위험
// ─────────────────────────────────────────────────────────────────────────────
// A7 은 세 도구의 **결론**을 나란히 놓았다. A8 은 그 결론을 쓸 수 있게 만드는 셋을
// 붙였다: 왜 이 국면인지(정확 Shapley) · 어디로 갈 위험인지(Dirichlet 사후 전이) ·
// 역사적으로 어디쯤인지(월별 리본).
//
// ★이 스펙이 지키는 핵심은 "숫자가 맞나" 가 아니라 "없는 것을 주장하지 않나" 다★
// 매크로 시계열은 실측 60개월뿐이고 분류 가능한 달은 그보다 적다. 화면이 "10년" 을
// 말하거나, 관측 1개짜리 행을 확신처럼 보여 주거나, 미가용 사유를 탭 뒤에 숨기면
// 그 순간 이 패널은 신뢰할 수 없게 된다.
//
// 루프 앞에 개수를 먼저 단언한다 — A4~A7 에서 다섯 번, 대상이 0개라 조용히 통과하는
// "가드 모양의 무가드" 를 만들었다.
// ═══════════════════════════════════════════════════════════════════════════════

async function gotoMacro(page: Page) {
  await page.goto("/allocation", { waitUntil: "networkidle" });
  await page.locator(".aas-goal").first().click();
  await page.waitForURL(/\/allocation\/construct/, { timeout: 15_000 });
  await page.goto("/allocation/macro", { waitUntil: "networkidle" });
  await expect(page.locator(".as-rge")).toBeVisible({ timeout: 20_000 });
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. ★리본은 상시 보이고, 자기 구간을 스스로 밝힌다★
// ─────────────────────────────────────────────────────────────────────────────
test("★리본이 항상 보이고 관측 구간을 명시한다 (없는 역사를 주장하지 않는다)★", async ({ page }) => {
  await gotoMacro(page);

  const ribbon = page.locator(".as-rgr");
  await expect(ribbon, "리본이 없다").toBeVisible({ timeout: 20_000 });

  const cells = page.locator(".as-rgr-cell");
  const n = await cells.count();
  expect(n, "리본 셀 수 (0 이면 이 테스트는 아무것도 지키지 않는다)").toBeGreaterThan(0);

  // 구간 문자열 — `관측 N개월 (YYYYMM ~ YYYYMM)`.
  const span = page.locator(".as-rgr-span");
  await expect(span).toBeVisible();
  const spanText = ((await span.textContent()) || "").trim();
  const m = spanText.match(/관측\s+(\d+)\s*개월/);
  expect(m, `구간 문자열에서 개월 수를 읽을 수 없다: "${spanText}"`).not.toBeNull();

  // ★셀 개수와 주장하는 개월 수가 같아야 한다★ 둘이 다르면 화면이 실제로 그린 것과
  // 다른 기간을 말하고 있다는 뜻이다.
  expect(Number(m![1]), "리본이 주장하는 개월 수와 실제 셀 수가 다르다").toBe(n);

  // ★"10년" 을 주장하지 않는다★ 이 저장소의 실측은 60개월이고, 분류 가능한 달은
  // 그보다 적다. 데이터가 실제로 120개월 이상일 때만 그렇게 쓸 수 있다.
  const claimed = Number(m![1]);
  const body = ((await ribbon.textContent()) || "");
  if (claimed < 120) {
    expect(body, "120개월 미만인데 '10년' 을 주장한다").not.toMatch(/10\s*년/);
  }
});

test("리본이 현재 국면의 연속 개월과 역사 점유율을 말한다", async ({ page }) => {
  await gotoMacro(page);
  await expect(page.locator(".as-rgr-run")).toContainText("연속");
  await expect(page.locator(".as-rgr-share")).toContainText("역사 점유율");

  // 범례는 색만으로 의미를 전달하지 않는다 — 이름이 함께 있어야 한다.
  const lg = page.locator(".as-rgr-lg");
  await expect(lg).toHaveCount(4);
  await expect(lg.first()).toContainText(/골디락스|리플레이션|스태그플레이션|디스인플레이션/);
});

// ─────────────────────────────────────────────────────────────────────────────
// 2. ★세그먼트 탭 — 그리고 사유는 탭 뒤에 숨지 않는다★
// ─────────────────────────────────────────────────────────────────────────────
test("세 탭이 전환되고 aria-selected 가 하나만 참이다", async ({ page }) => {
  await gotoMacro(page);

  const tabs = page.locator(".as-rge-tab");
  await expect(tabs).toHaveCount(3);
  await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "true");

  await tabs.nth(1).click();
  await expect(tabs.nth(1)).toHaveAttribute("aria-selected", "true");
  await expect(tabs.nth(0)).toHaveAttribute("aria-selected", "false");
  await expect(page.locator("#as-rge-p-shift")).toBeVisible({ timeout: 20_000 });

  await tabs.nth(2).click();
  await expect(page.locator("#as-rge-p-why")).toBeVisible({ timeout: 20_000 });
  await expect(tabs.nth(2)).toHaveAttribute("aria-selected", "true");
});

test("★미가용 사유는 탭을 바꾸지 않고 보인다★", async ({ page }) => {
  // 상태전환 도구를 미가용으로 만든다 — 그 사유가 '확률 비교' 탭 안이 아니라
  // 탭 **바깥** 요약줄에 나와야 한다. 탭을 바꿔야만 보이는 경고는 없는 경고다.
  await page.route(/\/api\/v1\/macro\/regime-ensemble/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    body.tools.markov = { available: false, reason: "테스트용 미수렴 사유" };
    body.agreement = { unanimous: null, picks: {}, note: "테스트" };
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await gotoMacro(page);

  const na = page.locator(".as-rge-na");
  await expect(na, "미가용 요약줄이 없다").toBeVisible({ timeout: 20_000 });
  await expect(na).toContainText("테스트용 미수렴 사유");

  // 요약줄이 탭 패널 **밖**에 있어야 한다 — 안에 있으면 탭을 바꾸면 사라진다.
  const insidePanel = await na.evaluate((el) => !!el.closest(".as-rge-panel"));
  expect(insidePanel, "미가용 사유가 탭 패널 안에 있다 — 탭을 바꾸면 사라진다").toBe(false);

  // 실제로 다른 탭으로 가도 여전히 보이는지 확인한다.
  await page.locator(".as-rge-tab").nth(2).click();
  await expect(page.locator("#as-rge-p-why")).toBeVisible({ timeout: 20_000 });
  await expect(na, "탭을 바꿨더니 미가용 사유가 사라졌다").toBeVisible();
});

// ─────────────────────────────────────────────────────────────────────────────
// 3. ★전이행렬 — 점추정 하나로 확신을 흉내내지 않는다★
// ─────────────────────────────────────────────────────────────────────────────
test("★전이행렬의 모든 칸이 값과 신용구간을 함께 보여 준다★", async ({ page }) => {
  await gotoMacro(page);
  await page.locator(".as-rge-tab").nth(1).click();
  await expect(page.locator(".as-rgt")).toBeVisible({ timeout: 25_000 });

  // 4×4 = 확률 칸 16개.
  const cis = page.locator(".as-rgt-ci");
  const n = await cis.count();
  expect(n, "신용구간 칸 수").toBe(16);

  // 구간이 `a–b` 형태이고 하한 ≤ 상한인지 — 빈 칸이나 뒤집힌 구간이 없어야 한다.
  const bad = await cis.evaluateAll((els) =>
    els.map((el) => (el.textContent || "").trim())
      .filter((t) => {
        const m = t.match(/^(\d+)%–(\d+)%$/);
        return !m || Number(m[1]) > Number(m[2]);
      }));
  expect(bad, "형식이 깨졌거나 하한>상한인 신용구간").toEqual([]);

  // 접근성: 표의 헤더에 scope 가 있어야 한다.
  const noScope = await page.locator(".as-rgt-tbl th").evaluateAll(
    (els) => els.filter((el) => !el.getAttribute("scope")).length);
  expect(noScope, "scope 없는 th").toBe(0);
});

test("★관측이 부족한 행은 색이 아니라 글자로 그 사실을 말한다★", async ({ page }) => {
  // 한 행의 관측을 1개로 만든다 — 수축이 일어나고, 그 사실이 텍스트로 나와야 한다.
  await page.route(/\/api\/v1\/macro\/regime-explain/, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    const tr = body.transitions;
    if (tr?.available && tr.rows?.length) {
      tr.rows[1] = {
        ...tr.rows[1], n: 1, counts: [1, 0, 0, 0], shrunk: true,
        reason: "이 국면에서 출발한 관측이 1개뿐입니다 (최소 5개).",
      };
    }
    await route.fulfill({ response: res, body: JSON.stringify(body) });
  });
  await gotoMacro(page);
  await page.locator(".as-rge-tab").nth(1).click();
  await expect(page.locator(".as-rgt")).toBeVisible({ timeout: 25_000 });

  const shrunk = page.locator(".as-rgt-shrunk");
  await expect(shrunk, "수축된 행인데 사유 텍스트가 없다").toHaveCount(1);
  await expect(shrunk).toContainText("1개뿐");
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. ★워터폴 — 화면이 스스로를 검산한다★
// ─────────────────────────────────────────────────────────────────────────────
test("★워터폴이 25% 에서 출발해 최종 확률에 도달하고 그 검산을 표시한다★", async ({ page }) => {
  await gotoMacro(page);
  await page.locator(".as-rge-tab").nth(2).click();
  await expect(page.locator(".as-rgd")).toBeVisible({ timeout: 25_000 });

  // 기저는 25.0% 다 — 모든 지표가 역사 평균이면 네 국면이 균등하다.
  await expect(page.locator(".as-rgd-anchor").first()).toContainText("25.0%");

  const rows = page.locator(".as-rgd-row");
  const n = await rows.count();
  expect(n, "드라이버 행 수 (0 이면 검사할 것이 없다)").toBeGreaterThan(0);

  // 검산줄 — 실패 상태(.bad)면 안 된다.
  const check = page.locator(".as-rgd-check");
  await expect(check).toBeVisible();
  await expect(check, "효율성 검산이 실패로 표시됐다").not.toHaveClass(/bad/);
  await expect(check).toContainText("Σφ");

  // ★화면의 숫자로 직접 검산한다★ Σφ 가 최종 − 기저와 맞는지 DOM 에서 읽어 확인.
  const phis = await page.locator(".as-rgd-phi").evaluateAll((els) =>
    els.map((el) => parseFloat((el.textContent || "").replace(/[^0-9.+-]/g, ""))));
  expect(phis.length, "φ 값 수").toBe(n);
  const sum = phis.reduce((a, b) => a + b, 0);

  const finalTxt = (await page.locator(".as-rgd-final b").textContent()) || "";
  const finalPct = parseFloat(finalTxt.replace(/[^0-9.]/g, ""));
  expect(sum, `화면의 φ 합(${sum.toFixed(1)}%p)이 최종−기저(${(finalPct - 25).toFixed(1)}%p)와 다르다`)
    .toBeCloseTo(finalPct - 25, 0);
});

test("워터폴이 축 기여와 확률 기여를 **둘 다** 보여 준다", async ({ page }) => {
  await gotoMacro(page);
  await page.locator(".as-rge-tab").nth(2).click();
  await expect(page.locator(".as-rgd")).toBeVisible({ timeout: 25_000 });

  const axc = page.locator(".as-rgd-axc");
  const n = await axc.count();
  expect(n, "축 기여 표시 수").toBeGreaterThan(0);
  await expect(axc.first()).toContainText("축");

  // 부호가 갈릴 수 있다는 사실을 화면이 설명해야 한다 — 한 층만 보면 정반대로 읽힌다.
  await expect(page.locator(".as-rgd-note")).toContainText("부호가 다를 수 있");
});

// ─────────────────────────────────────────────────────────────────────────────
// 5. §56 하한 + 대비
// ─────────────────────────────────────────────────────────────────────────────
const SURFACES: [tab: number, root: string, name: string][] = [
  [0, ".as-rgr", "리본"],
  [1, ".as-rgt", "전이행렬"],
  [2, ".as-rgd", "워터폴"],
];

for (const [tabIdx, root, name] of SURFACES) {
  test(`§56 하한: ${name} — 11px 미만 텍스트 없음`, async ({ page }) => {
    await gotoMacro(page);
    if (tabIdx > 0) await page.locator(".as-rge-tab").nth(tabIdx).click();
    await expect(page.locator(root)).toBeVisible({ timeout: 25_000 });

    const small = await page.locator(`${root} *`).evaluateAll((els) => {
      const out: { cls: string; px: number; text: string }[] = [];
      for (const el of els) {
        const t = (el.textContent || "").trim();
        if (!t) continue;
        const own = Array.from(el.childNodes).some(
          (nd) => nd.nodeType === 3 && (nd.textContent || "").trim());
        if (!own) continue;
        const px = parseFloat(getComputedStyle(el).fontSize);
        if (px < 11) out.push({ cls: String(el.className), px, text: t.slice(0, 24) });
      }
      return out;
    });
    const nodes = await page.locator(`${root} *`).count();
    expect(nodes, "검사한 노드 수 (0 이면 조용히 통과한다)").toBeGreaterThan(3);
    expect(small, "11px 미만 텍스트").toEqual([]);
  });
}

for (const theme of ["light", "dark"] as const) {
  test(`대비: A8 표면 (${theme}) — AA 실패 0 · 밝은 배경 누출 0`, async ({ page }) => {
    await gotoMacro(page);
    if (theme === "dark") {
      await page.evaluate(() => document.documentElement.classList.add("dark"));
    }
    // 세 탭을 모두 거쳐야 세 표면이 다 렌더된 적이 있게 된다. 대비는 현재 보이는
    // 것만 잴 수 있으므로 탭마다 잰다.
    for (const [tabIdx, root, name] of SURFACES) {
      if (tabIdx > 0) await page.locator(".as-rge-tab").nth(tabIdx).click();
      await expect(page.locator(root)).toBeVisible({ timeout: 25_000 });
      const r: AuditResult = await page.evaluate(contrastAudit(root));
      expect(r.checked, `${name}: 검사한 노드 수`).toBeGreaterThan(2);
      expect(r.low, `${theme} ${name}: AA 미달`).toEqual([]);
      if (theme === "dark") expect(r.bright, `${name}: 다크에서 밝은 배경 누출`).toEqual([]);
    }
  });
}
