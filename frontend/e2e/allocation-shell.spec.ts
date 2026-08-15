import { test, expect } from "@playwright/test";
import {
  buildAnalyzeRequest, diffAgainstSignature, freshnessOf, signatureOf,
  type SignatureInputs,
} from "../src/widgets/allocation/analyzeSignature";

// ═══════════════════════════════════════════════════════════════════════════════
// Allocation Studio 셸 — 서명·신선도·스티키·가독 (A1)
// ─────────────────────────────────────────────────────────────────────────────
// research-shell.spec.ts 와 같은 두 층 구조를 따른다: 정책은 브라우저 없이 순수 함수로
// 전수 검사하고, 화면은 그 정책이 실제로 보이는지만 본다.
// ═══════════════════════════════════════════════════════════════════════════════

const BASE: SignatureInputs = {
  tickers: ["005930", "000660"],
  weights: { "005930": 60, "000660": 40 },
  mesId: null,
  views: [],
  model: "bl",
  delta: 2.5,
  tau: 0.05,
  constraints: null,
};
const VIEW = { assets: ["005930"], direction: 1 as const, magnitude_pct: 8, confidence: 70 };

test.describe("분석 서명 (순수 함수)", () => {
  test("★λ 는 유효한 뷰가 있을 때만 서명에 들어간다★", () => {
    // 근거는 엔진 실측이다 — tests/test_allocation_delta_sensitivity.py.
    // delta 가 닿는 경로는 `pi = delta * S @ w_mkt` 한 줄뿐이고 `if views:` 안에 있다.
    const noViews = (d: number) => signatureOf(buildAnalyzeRequest({ ...BASE, delta: d }));
    expect(noViews(1.0), "뷰가 없으면 λ 를 바꿔도 서명이 같아야 한다").toBe(noViews(7.0));

    const withViews = (d: number) =>
      signatureOf(buildAnalyzeRequest({ ...BASE, views: [VIEW], delta: d }));
    expect(withViews(1.0), "뷰가 있으면 λ 가 서명을 바꿔야 한다").not.toBe(withViews(7.0));
  });

  test("크기 0 뷰는 유효한 뷰가 아니다 — 엔진의 build_user_views 와 같은 판정", () => {
    // 여기가 엔진과 어긋나면 "뷰가 있다고 보고 λ 를 넣었는데 엔진은 뷰를 버린" 상태가 되어
    // 영원히 재계산 필요로 남는다.
    const zero = [{ ...VIEW, magnitude_pct: 0 }];
    const a = signatureOf(buildAnalyzeRequest({ ...BASE, views: zero, delta: 1.0 }));
    const b = signatureOf(buildAnalyzeRequest({ ...BASE, views: zero, delta: 7.0 }));
    expect(a, "크기 0 뷰만 있으면 λ 는 서명에 들어가지 않는다").toBe(b);
    expect(JSON.parse(a).views, "크기 0 뷰는 요청에서도 빠진다").toEqual([]);
  });

  test("★요청과 서명이 어긋날 수 없다★ constraints 의 null/undefined 왕복", () => {
    // 예전 결함: 판정용 리터럴은 `constraints`(null), 요청 리터럴은 `constraints ?? undefined`
    // 였다. 같은 상태인데 두 문자열이 달랐다. 이제 서명은 요청에서 파생되므로 이 왕복이 닫힌다.
    const req = buildAnalyzeRequest(BASE);
    expect(req.constraints, "null 은 undefined 로 정규화된다").toBeUndefined();
    expect(freshnessOf(true, signatureOf(req), req).kind, "같은 입력이면 fresh").toBe("fresh");
  });

  test("over 오버라이드가 서명에 반영된다", () => {
    // 예전 판정 리터럴은 runAnalyze 가 받는 over 를 무시했다 — 엔진을 바꿔 실행한 직후에도
    // 서명이 옛 모델로 계산돼 잠깐 낡은 것처럼 보였다.
    const sent = buildAnalyzeRequest(BASE, { model: "min_var" });
    expect(sent.model).toBe("min_var");
    expect(signatureOf(sent)).not.toBe(signatureOf(buildAnalyzeRequest(BASE)));
  });
});

test.describe("결과 신선도 (순수 함수)", () => {
  test("★missing 과 superseded 는 다른 상태다★", () => {
    const req = buildAnalyzeRequest(BASE);
    // 결과가 없다 = 화면에 숫자가 없다. "낡았다"가 아니라 "아직 없다"이다.
    expect(freshnessOf(false, signatureOf(req), req).kind).toBe("missing");
    // 결과는 있는데 입력이 그 뒤에 바뀌었다 = 화면에 숫자가 있고, 낡았다.
    const moved = buildAnalyzeRequest({ ...BASE, tau: 0.1 });
    expect(freshnessOf(true, signatureOf(req), moved).kind).toBe("superseded");
    expect(freshnessOf(true, signatureOf(req), req).kind).toBe("fresh");
  });

  test("무엇이 바뀌었는지 이름을 댄다 — 못 대면 null 을 준다", () => {
    const prev = signatureOf(buildAnalyzeRequest(BASE));
    const changed = diffAgainstSignature(
      prev, buildAnalyzeRequest({ ...BASE, tau: 0.1, model: "mvo" }));
    expect(changed).toEqual(["model", "tau"]);

    // 비중만 바뀐 경우
    expect(diffAgainstSignature(prev, buildAnalyzeRequest({
      ...BASE, weights: { "005930": 70, "000660": 30 } }))).toEqual(["holdings"]);

    // ★모르는 것을 아는 척하지 않는다★ 파싱 불가한 이전 서명이면 빈 배열이 아니라 null.
    // 빈 배열이면 "아무것도 안 바뀌었다"로 읽혀서 배너가 거짓말을 하게 된다.
    expect(diffAgainstSignature("not-json", buildAnalyzeRequest(BASE))).toBeNull();
  });
});

test.describe("셸 화면", () => {
  test("★스테퍼가 스크롤에 붙어 있다★", async ({ page }) => {
    // ★스크롤 여유가 큰 라우트를 골라야 한다★ 처음에는 /allocation/construct 로 짰는데,
    // 그 화면은 스크롤 가능 범위가 121px 뿐이고 그 값이 스티키 이동거리와 **정확히 같았다**.
    // 그러면 "고정됐다" 와 "스크롤 끝에 닿았다" 가 구분되지 않아 테스트가 아무것도 증명하지
    // 못한다. timing 은 여유가 730px 라 고정점을 확실히 지나친다.
    await page.goto("/allocation/timing", { waitUntil: "networkidle" });
    const wiz = page.locator(".aas-wiz");
    await expect(wiz).toBeVisible();

    // 스크롤 컨테이너는 window 가 아니라 .terminal-main 이다(globals.css:799 overflow-y:auto).
    // 창을 스크롤해도 안 움직이므로, 실제 스크롤포트를 움직여야 검사가 성립한다.
    //
    // ★"스크롤 전 위치와 같은가" 로 재면 안 된다★ 스티키 요소는 고정점에 닿을 때까지는
    // 같이 올라가고 거기서 멈춘다. 이 화면에서는 252 → 131 로 올라간 뒤 고정된다.
    // 그래서 검사할 성질은 "안 움직인다"가 아니라 **"더 스크롤해도 더는 안 움직인다"** 이다.
    const tops = await page.evaluate(async () => {
      const sc = document.querySelector(".terminal-main") as HTMLElement | null;
      if (!sc) return null;
      const top = () => document.querySelector(".aas-wiz")!.getBoundingClientRect().top;
      const out: { scrollTop: number; top: number }[] = [];
      for (const t of [300, 600]) {
        sc.scrollTop = t;
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        out.push({ scrollTop: sc.scrollTop, top: top() });
      }
      return out;
    });
    expect(tops, ".terminal-main 이 스크롤포트여야 한다").not.toBeNull();
    // 두 지점 모두 실제로 그만큼 스크롤됐어야 비교가 성립한다(끝에 닿아 클램프되면 무의미).
    expect(tops![0].scrollTop, "첫 지점까지 실제로 스크롤돼야 한다").toBe(300);
    expect(tops![1].scrollTop, "두 번째 지점까지 실제로 스크롤돼야 한다").toBe(600);

    for (const s of tops!) {
      expect(s.top, `스크롤 ${s.scrollTop}px 에서 스테퍼가 뷰포트 밖으로 나갔다`).toBeGreaterThanOrEqual(0);
    }
    expect(Math.abs(tops![1].top - tops![0].top), "고정점을 지난 뒤에는 더 움직이지 않는다").toBeLessThan(2);
  });

  test("스테퍼 글자가 11px 하한을 지킨다", async ({ page }) => {
    // 브리프는 고밀도를 요구하지만 8px 라벨은 조밀한 게 아니라 안 읽히는 것이다.
    // 밀도는 여백·배치에서 얻고, 글자는 읽히는 선을 지킨다.
    await page.goto("/allocation/construct", { waitUntil: "networkidle" });
    await expect(page.locator(".aas-wiz")).toBeVisible();

    for (const sel of [".aas-wiz-lab", ".aas-wiz-sub", ".aas-wiz-booklab"]) {
      const nodes = page.locator(sel);
      // 셀렉터가 0개면 조용히 통과한다 — 이 세션에서 반복해 겪은 실패 모양이다.
      expect(await nodes.count(), `${sel} 가 렌더돼야 검사가 성립한다`).toBeGreaterThan(0);
      const sizes = await nodes.evaluateAll((els) =>
        els.map((e) => parseFloat(getComputedStyle(e).fontSize)));
      for (const px of sizes) expect(px, `${sel} 하한 11px`).toBeGreaterThanOrEqual(11);
    }
  });

  test("★신선도 배너가 사유를 적고, 숫자를 흐리지 않는다★", async ({ page }) => {
    // 콜드 스타트 = 자산 없음 → 계산한 적 없음(missing).
    await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
    const banner = page.locator(".aas-fresh");
    await expect(banner).toBeVisible();
    await expect(banner, "역할이 status 여야 스크린리더가 읽는다").toHaveAttribute("role", "status");
    await expect(banner.locator(".aas-fresh-r"), "사유는 호버 없이 보인다").toContainText(/\S/);

    // ★브리프의 opacity-50 을 쓰지 않았다는 것을 계산으로 고정한다★
    // 결과 패널을 흐리면 그 안의 숫자가 AA 아래로 떨어지고, 그래도 여전히 읽히는 틀린 숫자다.
    //
    // ★비활성 컨트롤은 제외한다★ 첫 판은 .aas-content 의 모든 자손을 훑어서
    // `button.as-run[disabled]`(opacity 0.45)에 걸렸다. 비활성 버튼을 흐리는 것은 규약이고
    // (Material 의 disabled 는 0.38~0.5) 그건 데이터가 아니라 컨트롤이다.
    // 주장하려는 것은 "**결과 데이터**를 흐려서 낡음을 표현하지 않는다" 이므로 거기에 맞춘다.
    const dimmed = await page.locator(".aas-content").evaluate((el) => {
      const bad: string[] = [];
      for (const n of [el, ...el.querySelectorAll("*")] as Element[]) {
        if (n.closest("[disabled]") || (n as HTMLButtonElement).disabled) continue;
        const o = parseFloat(getComputedStyle(n).opacity);
        if (o <= 0.6) bad.push(`${n.tagName}.${(n.getAttribute("class") || "").slice(0, 30)}=${o}`);
      }
      return bad;
    });
    expect(dimmed, "결과 데이터를 opacity 로 흐려서 낡음을 표현하지 않는다").toEqual([]);
  });
});

/** WCAG 대비 감사 — S1b-2(backtest.spec.ts)와 같은 계산기. 브라우저 안에서 도는 문자열. */
const CONTRAST = (root: string) => `(() => {
  const lum=(r,g,b)=>{const f=(v)=>{v/=255;return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4);};return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b);};
  const parse=(s)=>{const m=s.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)/);return m?{r:+m[1],g:+m[2],b:+m[3],a:m[4]===undefined?1:+m[4]}:null;};
  const effBg=(el)=>{let n=el;while(n){const c=parse(getComputedStyle(n).backgroundColor);if(c&&c.a>0.5)return c;n=n.parentElement;}return {r:255,g:255,b:255,a:1};};
  const ratio=(a,b)=>{const l1=lum(a.r,a.g,a.b),l2=lum(b.r,b.g,b.b);return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);};
  const el0=document.querySelector("${root}"); if(!el0) return {checked:0,low:["NO ${root}"]};
  const low=[]; let checked=0;
  for(const el of [el0,...el0.querySelectorAll("*")]){
    const cs=getComputedStyle(el); if(cs.display==="none"||cs.visibility==="hidden") continue;
    if(!Array.from(el.childNodes).some(n=>n.nodeType===3&&n.textContent.trim())) continue;
    const fg=parse(cs.color); if(!fg) continue; checked++;
    const r=ratio(fg,effBg(el)); const px=parseFloat(cs.fontSize); const bold=parseInt(cs.fontWeight,10)>=700;
    const need=px>=24||(px>=18.66&&bold)?3:4.5;
    if(r<need) low.push(el.tagName+"."+(el.getAttribute("class")||"").split(" ").slice(0,2).join(".")+" "+r.toFixed(2)+":1 (need "+need+") "+px+"px :: "+(el.textContent||"").trim().slice(0,18));
  }
  return {checked,low:[...new Set(low)]};
})()`;
interface AuditResult { checked: number; low: string[] }

test("★A1: 스테퍼와 배너가 다크에서 AA 를 넘는다★", async ({ page }) => {
  // ★이 테스트가 실제로 잡은 것★
  // `.aas-wiz` 배경만 var(--card) 로 올리고 자식 `.aas-wiz-step` 의 `background:#fff` 를
  // 그대로 두었더니, 다크에서 글자색만 뒤집혀 `.aas-wiz-lab` 이 1.04:1 이 됐다 — 흰 글자가
  // 흰 배경 위에 있었다. 육안으로는 "좀 흐리네" 로 지나가고, 기존 테스트는 전부 초록이었다.
  //
  // 범위를 다크 전체가 아니라 **이번에 손댄 두 표면**으로 좁힌 것은 의도적이다. AAS 는
  // 아직 다크로 변환되지 않았고(§47 이 그 범위를 명시한다), 검증하지 않은 것을 검증했다고
  // 말하지 않기 위해서다.
  await page.goto("/allocation/optimize", { waitUntil: "networkidle" });
  await expect(page.locator(".aas-wiz")).toBeVisible();
  await expect(page.locator(".aas-fresh")).toBeVisible();

  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await page.waitForTimeout(250);

  const wiz = await page.evaluate<AuditResult>(CONTRAST(".aas-wiz"));
  expect(wiz.checked, "스테퍼에서 검사한 텍스트 노드 수").toBeGreaterThan(20);
  expect(wiz.low, "다크 스테퍼: AA 미달").toEqual([]);

  const fresh = await page.evaluate<AuditResult>(CONTRAST(".aas-fresh"));
  expect(fresh.checked, "배너에서 검사한 텍스트 노드 수").toBeGreaterThan(0);
  expect(fresh.low, "다크 배너: AA 미달").toEqual([]);
});
