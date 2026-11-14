// 문체 감사 도우미(`helpers.ts::voiceAudit`)가 ★공허하지 않은지★ (ADR 005 · 2026-11-11)
// ============================================================================================================
// 화면 문체를 해요체에서 개조식 + 합니다체로 옮기는 동안, 모듈 스펙들은 이 도우미 하나로 "보이는 글자"를 감사한다.
// 감사가 아무것도 못 잡으면 전부 초록이 된다 — 그래서 도우미 자체를 고정한다: 잡아야 할 것은 잡고(해요체 · em-dash · 풀어 쓴 영어 · 툴팁),
// 잡지 말아야 할 것은 안 잡는다(합니다체 · 명사형 · 통용 약어 · 수요/주요 같은 명사 · 서버가 준 글 · 식별자 · 안 보이는 글자).
// 서버가 필요 없다 — 글자를 직접 심는다.
import { test, expect } from "./fixtures";
import { voiceAudit, type VoiceResult } from "./helpers";

const page1 = (body: string) => `<!doctype html><meta charset="utf-8"><body><main class="v">${body}</main></body>`;

test("잡는다 — 해요체(여러 꼴) · em-dash · 풀어 쓴 영어 · 개발자 낱말 · 툴팁", async ({ page }) => {
  await page.setContent(page1(`
    <p>가치 범위를 불러오지 못했어요</p><p>계산하는 중이에요.</p><p>값을 넣어 주세요</p><p>지금 열려 있어요</p>
    <p>몰라요</p><p>그렇죠</p><p>바꿔요</p><p>실제 돈으로 주문해요</p>
    <p>벤치마크 없음 — 비교 지수 미사용</p>
    <h2>Valuation</h2><span>mock</span><b>Football Field</b>
    <i title="숨은 설명">가</i><svg width="10" height="10"><title>그림 설명</title><rect width="10" height="10"/></svg>`));
  const r = await page.evaluate<VoiceResult>(voiceAudit(".v"));
  expect(r.haeyo.length, `해요체 ${JSON.stringify(r.haeyo)}`).toBe(8);
  expect(r.dash).toEqual(["벤치마크 없음 — 비교 지수 미사용"]);
  expect(r.banned.sort()).toEqual(["Football Field", "Valuation", "mock"]);
  expect(r.titles).toBe(2);
});

test("짝 — 안 잡는다: 합니다체 · 명사형 · 통용 약어 · 요로 끝나는 명사 · 서버 글 · 식별자 · 입력 칸 · 안 보이는 글자", async ({ page }) => {
  await page.setContent(page1(`
    <p>무위험수익률 3.5%, 베타 1.0 가정으로 산출했습니다.</p><p>값을 입력하십시오.</p>
    <p>조회 실패</p><p>계산 중</p><p>N/A</p><p>괴리율 +74.8% (고평가)</p>
    <p>PER 12.3배 · ROE 15% · MDD −21% · CAGR 8% · Altman Z-Score 2.4 · Beneish M-Score −2.1 · DCF · WACC</p>
    <p>수요 충격</p><p>주요 낙폭 구간</p><p>필요 자본</p><p>개요</p><p>해요체 금지</p>
    <p data-server>서버가 준 글은 아직 해요체일 수 있어요 — Valuation</p>
    <code>mock_allowed</code><span data-mono>ANTHROPIC_API_KEY</span>
    <input value="불러오지 못했어요"><textarea>적어 주세요</textarea>
    <p style="display:none">안 보여요</p><p style="visibility:hidden">숨겼어요</p>`));
  const r = await page.evaluate<VoiceResult>(voiceAudit(".v"));
  expect(r.checked, "감사한 글이 있어야 이 짝이 뜻이 있다").toBeGreaterThan(10);
  expect(r.haeyo).toEqual([]);
  expect(r.dash).toEqual([]);
  expect(r.banned).toEqual([]);
  expect(r.titles).toBe(0);
});

test("화면마다 금지 낱말을 더할 수 있다 · 뿌리가 없으면 통과가 아니라 사유가 나온다", async ({ page }) => {
  await page.setContent(page1(`<p>Goldilocks 국면</p><p>골디락스 국면</p>`));
  expect((await page.evaluate<VoiceResult>(voiceAudit(".v"))).banned).toEqual([]);
  expect((await page.evaluate<VoiceResult>(voiceAudit(".v", "Goldilocks|GOLDILOCKS"))).banned).toEqual(["Goldilocks 국면"]);
  const none = await page.evaluate<VoiceResult>(voiceAudit(".no-such-root"));
  expect(none.checked).toBe(0);
  expect(none.haeyo, "뿌리가 없는데 빈 배열이면 감사가 공허하게 통과한다").toEqual(["NO .no-such-root"]);
});
