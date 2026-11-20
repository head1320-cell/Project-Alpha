// 초점 표시 확인(읽기 전용) — 정한 요소를 Tab 으로 찾아가 ① 초점 전후의 겉모습이 달라지는가 ② 고리가 늦게 뜨는가 ③ 다른 것에 가리는가를 본다.
// 쓰임: node scripts/ux-measure/focusprobe.mjs [--delay] [<경로> <선택자>]...
//   인자가 없으면 2026-11-20 감사가 '고리 없음 · 가림'으로 잡았던 자리(아래 CASES)를 본다. 결과는 표준 출력의 한 줄씩이다.
//   --delay: Tab 직후와 300ms 뒤의 outline 을 견준다(전환이 고리를 늦추는지 — `transition: all` 의 흔적).
import { context, launch, login, open } from "./lib.mjs";

const args = process.argv.slice(2);
const DELAY = args.includes("--delay");
const rest = args.filter((a) => a !== "--delay");
if (rest.length % 2) {
  console.error("쓰임: node scripts/ux-measure/focusprobe.mjs [--delay] [<경로> <선택자>]...");
  process.exit(2);
}
const CASES = rest.length
  ? Array.from({ length: rest.length / 2 }, (_, i) => [rest[2 * i], rest[2 * i + 1]])
  : DELAY
    ? [["/backtest", ".tbt-mode"], ["/macro", ".mc-tab"], ["/my-account/journal", ".tj-file-input"]]
    : [["/derivatives", ".input"], ["/admin/data", ".dsx-input"], ["/backtest/intraday", ".tj-input"], ["/backtest", ".tbt-mode"], ["/macro", ".mc-tab"],
       ["/backtest", ".kit-toggle"], ["/backtest", ".bs-numbox"], ["/backtest/intraday", ".tx-btn"], ["/my-account/journal", ".tj-file-input"], ["/risk-tools", "a, button"]];
const MAX_TABS = 90;

// 브라우저 안에서 도는 조각 — 요소의 겉모습(자신과 부모: 고리를 부모가 대신 그리는 꼴이 있다).
const SNAP = (el) => {
  const cs = getComputedStyle(el);
  const p = el.parentElement ? getComputedStyle(el.parentElement) : null;
  const r = el.getBoundingClientRect();
  return {
    outline: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}`, shadow: cs.boxShadow.slice(0, 60), border: `${cs.borderTopWidth} ${cs.borderTopColor}`, bg: cs.backgroundColor,
    pShadow: p ? p.boxShadow.slice(0, 60) : "", pOutline: p ? `${p.outlineStyle} ${p.outlineWidth}` : "",
    box: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
  };
};

/** 본문(셸의 머리 줄 · 메뉴 밖)에서 선택자에 맞는 요소에 Tab 으로 닿는다. 닿은 걸음 수(못 닿으면 0). ★셸 안의 요소(머리 줄의 찾기 칸 등)는 이 도구로 보지 못한다.★ */
async function tabTo(page, sel) {
  for (let i = 1; i <= MAX_TABS; i++) {
    await page.keyboard.press("Tab");
    const hit = await page.evaluate((s) => {
      const el = document.activeElement;
      return !!el && el.matches(s) && !el.closest(".terminal-header, .terminal-sidebar");
    }, sel);
    if (hit) return i;
  }
  return 0;
}

const browser = await launch();
const token = await login(browser);
for (const [route, sel] of CASES) {
  const ctx = await context(browser, { token });
  const page = await ctx.newPage();
  await open(page, route);
  const steps = await tabTo(page, sel);
  if (!steps) {
    console.log(route, sel, `| ${MAX_TABS}걸음 안에 닿지 못함`);
    await ctx.close();
    continue;
  }
  if (DELAY) {
    const read = () => page.evaluate(() => {
      const el = document.activeElement;
      const cs = getComputedStyle(el);
      const lab = el.closest("label, .tj-drop") || el.parentElement;
      const ls = getComputedStyle(lab);
      return { outline: `${cs.outlineStyle} ${cs.outlineWidth}`, transition: `${cs.transitionProperty} ${cs.transitionDuration}`,
        wrap: (lab.className || lab.tagName).toString().slice(0, 30), wrapOutline: `${ls.outlineStyle} ${ls.outlineWidth}`, wrapShadow: ls.boxShadow.slice(0, 50), wrapBorder: ls.borderTopColor };
    });
    const t0 = await read();
    await page.waitForTimeout(300);
    const t1 = await read();
    console.log(route, sel, `(${steps}걸음) | 직후`, t0.outline, "| 300ms 뒤", t1.outline, "| transition", t0.transition, "| 감싼 것", t1.wrap, t1.wrapOutline, t1.wrapShadow, t1.wrapBorder);
  } else {
    const found = await page.evaluate((SN) => {
      const snap = eval("(" + SN + ")");
      const el = document.activeElement;
      const focused = snap(el);
      const r = el.getBoundingClientRect();
      const c = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      const cover = c && !(el.contains(c) || c.contains(el)) ? (c.className || c.tagName).toString().slice(0, 40) : null;
      el.blur();
      return { tag: el.tagName.toLowerCase(), cls: el.className.toString().slice(0, 40), name: (el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 20), focused, blurred: snap(el), cover };
    }, SNAP.toString());
    const diff = ["outline", "shadow", "border", "bg", "pShadow", "pOutline"].filter((k) => found.focused[k] !== found.blurred[k]).map((k) => `${k}: ${found.blurred[k]} → ${found.focused[k]}`);
    console.log(route, sel, `| ${found.tag}.${found.cls} '${found.name}' (${steps}걸음) | 바뀐 것: ${diff.length ? diff.join(" ; ") : "★없음★"} | 가림: ${found.cover ?? "없음"} | 상자 ${found.focused.box}`);
  }
  await ctx.close();
}
await browser.close();
