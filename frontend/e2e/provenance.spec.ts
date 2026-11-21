import { test, expect, type Locator, type Page } from "./fixtures";
import { contrastAudit, type AuditResult } from "./helpers";

/**
 * 출처 표지 · 갱신 시각 — 견본(`/dev/ui` 의 '출처 표지 · 갱신 시각' 절)에서 건다 (U2-a · 설계 문서 §5.1 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u2-provenance.md`)
 * ─────────────────────────────────────────────────────────────────
 * 견본의 값은 손으로 적었다(받은 때는 이 기기의 09:30:05 로 고정). 기대값은 그 값에서 손으로 적었다 — 화면에서 긁지 않는다.
 * 거는 것(짝으로 항상-통과를 배제):
 *  · ★합성 칩은 밀도 셋 × 두 테마에서 보인다★ — 감추기(display · visibility · 투명도 · 0 크기 · 글자색 = 바탕색 · 상자 밖 ·
 *    잘라 내기 · 덮기)로 지울 수 없고, 글자는 경고색이다(짝: 중립 칩은 경고색이 아니다)
 *  · 축의 차례(출처 → 시각들 → 시점 정합) — 문서의 차례와 보이는 차례 모두 · 근거의 종류(ev) · 모름은 'N/A(사유)'이고 보인다 · 표지마다 이름이 있다
 *  · 덧붙임은 중립(plain · 파랑이 아니다)
 *  · 칩의 글자 크기는 밀도를 따른다(촘촘 11 · 보통 12 · 넉넉 13 · 속성 없음 13 — 짝: 촘촘 ≠ 넉넉)
 *  · 갱신 시각 줄: 글자 그대로 · ★낭독하지 않는다★(그 줄과 조상에 aria-live · role=status 가 없다)
 *  · 대비 AA(라이트 · 다크 · 다크에 밝은 판 0) · 390 에서 절이 가로로 넘치지 않는다
 */

const box = (page: Page, density: string | null, dark = false) =>
  page.locator(`#provenance .devui-pv-box${density ? `[data-density="${density}"]` : ":not([data-density])"}${dark ? ".dark" : ":not(.dark)"}`);
const COMBOS: [density: string | null, dark: boolean][] = [
  ["compact", false], ["regular", false], ["comfortable", false],
  ["compact", true], ["regular", true], ["comfortable", true], [null, false],
];
const name = (d: string | null, dark: boolean) => `${d ?? "속성 없음"}${dark ? " · 다크" : ""}`;
const badge = (b: Locator, label: string) => b.locator(`ul.tx-chips.tx-prov[aria-label="${label}"]`);

async function open(page: Page) {
  await page.goto("/dev/ui#provenance", { waitUntil: "domcontentloaded" });
  await expect(box(page, "compact").locator(".tx-prov").first()).toBeVisible({ timeout: 20_000 });
}

test("★합성 칩은 밀도 셋 × 두 테마에서 보인다★ — 크기 · 투명도 · 가려짐 · 같은 색 · 상자 밖으로 숨길 수 없다", async ({ page }) => {
  await open(page);
  for (const [d, dark] of COMBOS) {
    const b = box(page, d, dark);
    await expect(b, name(d, dark)).toHaveCount(1);
    const chip = badge(b, "합성 견본의 출처").locator('.tx-chip[data-tone="practice"]');
    await expect(chip, name(d, dark)).toHaveCount(1);
    await expect(chip, name(d, dark)).toBeVisible();
    await expect(chip, name(d, dark)).toHaveText("합성 데이터");
    const m = await chip.evaluate((el) => {
      el.scrollIntoView({ block: "center" });   // 화면 가운데로 — 셸의 머리 줄이 가리지 않는 자리에서 잰다
      const r = el.getBoundingClientRect();
      // 맨 위에 그려지는 것이 이 칩인가 — 잘라 내기(clip-path · 조상의 overflow) · 덮기(겹친 판)로 감춘 것도 잡는다.
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const hostEl = el.closest(".devui-pv-box")!;
      const host = hostEl.getBoundingClientRect();
      let op = 1;
      for (let n: Element | null = el; n; n = n.parentElement) op *= Number(getComputedStyle(n).opacity);
      const cs = getComputedStyle(el);
      // 그 상자의 경고색(--tx-warn)을 rgb 로 푼다 — 합성 표시는 경고색 + 낱말이다(ADR 007 §5.4). 짝: 중립 칩의 글자색은 경고색이 아니다.
      const probe = document.createElement("span");
      probe.style.color = "var(--tx-warn)";
      hostEl.appendChild(probe);
      const warn = getComputedStyle(probe).color;
      probe.remove();
      const plain = hostEl.querySelector('.tx-prov .tx-chip[data-tone="plain"]');
      return { w: r.width, h: r.height, op, vis: cs.visibility, color: cs.color, bg: cs.backgroundColor, warn,
               onTop: !!top && (top === el || el.contains(top)),
               plainColor: plain ? getComputedStyle(plain).color : null,
               inside: r.left >= host.left - 0.5 && r.right <= host.right + 0.5 && r.top >= host.top - 0.5 && r.bottom <= host.bottom + 0.5 };
    });
    expect(m.w, name(d, dark)).toBeGreaterThanOrEqual(40);
    expect(m.h, name(d, dark)).toBeGreaterThanOrEqual(14);
    expect(m.op, name(d, dark)).toBeGreaterThan(0.9);
    expect(m.vis, name(d, dark)).toBe("visible");
    expect(m.color, name(d, dark)).not.toBe(m.bg);
    expect(m.color, `${name(d, dark)} — 합성 칩의 글자는 경고색이다`).toBe(m.warn);
    expect(m.plainColor, `${name(d, dark)} — 짝: 중립 칩은 경고색이 아니다`).not.toBe(m.warn);
    expect(m.inside, `${name(d, dark)} — 칩이 견본 상자 안에 있다`).toBe(true);
    expect(m.onTop, `${name(d, dark)} — 칩의 가운데에 그려지는 것이 칩이다(잘리거나 덮이지 않는다)`).toBe(true);
    // 짝: 합성이 아닌 칩(출처 · 시각 · 시점 정합 · 덧붙임 · 모름)은 모두 중립 글자색(--tx-sub)이다 — 출처 표지는 중립 색조(파랑 · 상태색 없음).
    const neutral = await b.locator('.tx-prov .tx-chip:not([data-tone="practice"])').evaluateAll((els) => {
      const host = els[0].closest(".devui-pv-box")!;
      const probe = document.createElement("span");
      probe.style.color = "var(--tx-sub)";
      host.appendChild(probe);
      const sub = getComputedStyle(probe).color;
      probe.remove();
      return { n: els.length, off: els.filter((e) => getComputedStyle(e).color !== sub).map((e) => e.textContent) };
    });
    expect(neutral.n, name(d, dark)).toBe(9);
    expect(neutral.off, `${name(d, dark)} — 출처 표지의 다른 칩은 중립 글자색이다`).toEqual([]);
  }
});

test("축의 차례 · 근거의 종류 · 모름은 'N/A(사유)' · 응답이 말한 출처는 plain(짝: 셋의 꼴이 서로 다르다)", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const syn = badge(b, "합성 견본의 출처").locator(".tx-chip");
  await expect(syn).toHaveText([
    "합성 데이터", "계산 시각 2026-11-21 09:30:05(서버 시계 · 시간대 표기 없음)", "자료 기준 시각 N/A(응답에 없습니다)", "시점 정합: 확인 안 됨",
  ]);
  expect(await syn.evaluateAll((els) => els.map((e) => e.getAttribute("data-ev")))).toEqual(["source", "asof", "asof", "pit"]);
  expect(await syn.evaluateAll((els) => els.map((e) => e.getAttribute("data-tone")))).toEqual(["practice", "plain", "unknown", "unknown"]);
  const known = badge(b, "실데이터 견본의 출처").locator(".tx-chip");
  await expect(known).toHaveText(["실제 분봉", "관측 끝 2026-11-20"]);
  expect(await known.first().getAttribute("data-tone")).toBe("plain");
  const unk = badge(b, "출처를 모르는 견본").locator(".tx-chip");
  await expect(unk).toHaveText(["출처 N/A(응답에 계열별 출처가 없습니다)"]);
  expect(await unk.first().getAttribute("data-tone")).toBe("unknown");
  const tones = [await syn.first().getAttribute("data-tone"), await known.first().getAttribute("data-tone"), await unk.first().getAttribute("data-tone")];
  expect(new Set(tones).size).toBe(3);
  // ★모름도 보인다★ — 글자 검사(toHaveText)는 숨긴 요소의 글도 읽는다. 칩마다 보이는지 따로 건다(N/A 를 조용히 감추지 못한다).
  for (const c of [...(await syn.all()), ...(await unk.all())]) await expect(c).toBeVisible();
  // 보이는 차례 = 문서의 차례 — 줄을 바꿔도 읽는 차례(위 → 아래 · 같은 줄은 왼 → 오른)로 선다(CSS 로 뒤집지 못한다).
  const rects = await syn.evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return { top: Math.round(r.top), left: Math.round(r.left) }; }));
  for (let i = 1; i < rects.length; i++) {
    const [a, z] = [rects[i - 1], rects[i]];
    expect(z.top > a.top + 2 || (Math.abs(z.top - a.top) <= 2 && z.left > a.left), `칩 ${i} 이 앞 칩 뒤에 선다 ${JSON.stringify([a, z])}`).toBe(true);
  }
  // 덧붙임은 중립(plain · ev 없음) — 파랑(info)이 아니다(ADR 007 §5.4).
  const note = badge(b, "덧붙임이 있는 견본").locator(".tx-chip").last();
  await expect(note).toHaveText("일부만 평가(서버의 평가 상한)");
  expect([await note.getAttribute("data-tone"), await note.getAttribute("data-ev")]).toEqual(["plain", null]);
  // 표지마다 이름이 있다(빈 이름 0 · 견본 일곱 상자 × 표지 다섯).
  const names = await page.locator("#provenance ul.tx-prov").evaluateAll((els) => els.map((e) => e.getAttribute("aria-label") ?? ""));
  expect(names.length).toBe(35);
  expect(names.filter((n) => !n.trim())).toEqual([]);
});

test("칩의 글자 크기는 밀도를 따른다 — 촘촘 11 · 보통 12 · 넉넉 13 · 속성 없음 13(짝: 촘촘 ≠ 넉넉)", async ({ page }) => {
  await open(page);
  const fs = async (d: string | null) =>
    badge(box(page, d), "합성 견본의 출처").locator(".tx-chip").first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  const got = { compact: await fs("compact"), regular: await fs("regular"), comfortable: await fs("comfortable"), bare: await fs(null) };
  expect(got).toEqual({ compact: 11, regular: 12, comfortable: 13, bare: 13 });
  expect(got.compact).not.toBe(got.comfortable);
});

test("갱신 시각 줄: 글자 그대로 · ★낭독하지 않는다★(그 줄 · 출처 표지 · 조상에 aria-live · role=status 0)", async ({ page }) => {
  await open(page);
  const b = box(page, "compact");
  const lines = b.locator(".tx-fresh");
  await expect(lines).toHaveText([
    "5초마다 다시 읽습니다 · 마지막 수신 09:30:05",
    "10초마다 다시 읽습니다 · 마지막 수신 N/A(아직 받은 값이 없습니다)",
    "마지막 수신 09:30:05",
  ]);
  const announcing = await page.locator("#provenance").evaluate((sec) => {
    const hits: string[] = [];
    for (const el of Array.from(sec.querySelectorAll(".tx-fresh, .tx-prov"))) {
      for (let n: Element | null = el; n && n !== document.body; n = n.parentElement) {
        if (n.hasAttribute("aria-live") || n.getAttribute("role") === "status" || n.getAttribute("role") === "alert") hits.push(`${el.className} ← ${n.tagName.toLowerCase()}.${n.className}`);
      }
    }
    return { hits, n: sec.querySelectorAll(".tx-fresh, .tx-prov").length };
  });
  expect(announcing.n, "견본에 줄과 표지가 있다(빈 검사가 아니다)").toBeGreaterThanOrEqual(20);
  expect(announcing.hits).toEqual([]);
});

test("대비 AA — 라이트 · 다크 상자 · 다크에 밝은 판 0", async ({ page }) => {
  await open(page);
  const r = await page.evaluate<AuditResult>(contrastAudit("#provenance"));
  expect(r.checked).toBeGreaterThan(40);
  expect(r.low, JSON.stringify(r.low.slice(0, 6))).toEqual([]);
  for (const d of ["compact", "regular", "comfortable"]) {   // contrastAudit 은 선택자의 첫 요소만 본다 — 다크 상자를 하나씩
    const dark = await page.evaluate<AuditResult>(contrastAudit(`#provenance .devui-pv-box.dark[data-density="${d}"]`));
    expect(dark.checked, d).toBeGreaterThan(8);
    expect(dark.low, `${d} ${JSON.stringify(dark.low.slice(0, 6))}`).toEqual([]);
    expect(dark.bright, `${d} ${JSON.stringify(dark.bright.slice(0, 6))}`).toEqual([]);
  }
});

test("390 — 절이 가로로 넘치지 않고 칩은 상자 안에서 줄을 바꾼다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page);
  const over = await page.locator("#provenance").evaluate((sec) => ({
    sec: sec.scrollWidth - sec.clientWidth,
    boxes: Array.from(sec.querySelectorAll(".devui-pv-box")).map((bx) => bx.scrollWidth - bx.clientWidth),
  }));
  expect(over.sec).toBeLessThanOrEqual(1);
  expect(Math.max(...over.boxes)).toBeLessThanOrEqual(1);
});
