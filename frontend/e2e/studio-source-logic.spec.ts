import { test, expect } from "./fixtures";
import { studioSource, studioUsesSeries } from "../src/widgets/macro/studioSource";
import type { StudioDescriptor, StudioResult } from "../src/entities/macro/studios";

/**
 * 스튜디오 계산의 데이터 출처 — 순수 규칙(브라우저 없이) · U2-b · 계획 `docs/superpowers/plans/2026-11-21-uiux-u2-provenance.md`
 * 화면에서 거는 것은 `e2e/macro-studios.spec.ts` 의 U2-b 절(먼저 써서 빨강을 봤다). 이 스펙은 그 뒤에 결정표를 못 박으려고 더했다
 * — 빨강은 변이로 본다.
 *  · 계열을 쓰는가: 서버의 입력 계열이 먼저(있으면 그것만 본다) · 스튜디오 정보가 없으면 계산 응답의 기간(span) —
 *    미가용 · 기간 없음 · 응답 없음은 아니다
 *  · 게이트: 참 → '합성 데이터'(키가 있어도 — 받지 못한 계열은 합성으로 채워진다) / 거짓 → 'N/A(응답에 계열별 출처가 없습니다)'
 *    (키가 있어도 실데이터라 적지 않는다) / 받는 중 → null / 받지 못하고 실패 → 'N/A(합성 여부를 확인하지 못했습니다)' /
 *    받은 값이 있으면 다시 묻다 실패해도 받은 값(합성 표시를 거두지 않는다)
 */

const desc = (inputs: string[]): StudioDescriptor => ({
  id: "x", label: "X", question: "q", inputs,
  frontier: { name: "f", summary: "s", requires: [], available: false, reason: "r" },
  substitute: { name: "s", summary: "s", requires: [] },
});
const SPAN = { first: "2021-11", last: "2026-10", n: 60, requested: 60, truncated: false };
const ran = (span: typeof SPAN | null): StudioResult => ({ available: true, engine: "pca", outputs: {}, note: null, span });
const unavailable: StudioResult = { available: false, engine: null, reason: "표본이 모자랍니다" };
const GATE = { mock_allowed: true, real_mode: false, bok_configured: false, fred_configured: false };
const SYN = { kind: "synthetic", label: "합성 데이터" };
const OFF = { kind: "unknown", reason: "응답에 계열별 출처가 없습니다" };
const FAILED = { kind: "unknown", reason: "합성 여부를 확인하지 못했습니다" };

test("계열을 쓰는가: 서버의 입력 계열이 먼저 — 있으면 참 · 비면 거짓(계산 응답이 기간을 말해도)", () => {
  expect(studioUsesSeries(desc(["KR_LEADING_CYCLE"]), undefined)).toBe(true);
  expect(studioUsesSeries(desc(["KR_LEADING_CYCLE"]), unavailable)).toBe(true);
  expect(studioUsesSeries(desc([]), undefined)).toBe(false);
  expect(studioUsesSeries(desc([]), ran(SPAN))).toBe(false);
});

test("스튜디오 정보가 없으면 계산 응답의 기간이 증거(짝: 기간 없음 · 미가용 · 응답 없음은 거짓)", () => {
  expect(studioUsesSeries(null, ran(SPAN))).toBe(true);
  expect(studioUsesSeries(null, ran(null))).toBe(false);
  expect(studioUsesSeries(null, unavailable)).toBe(false);
  expect(studioUsesSeries(null, undefined)).toBe(false);
  expect(studioUsesSeries(null, null)).toBe(false);
});

test("게이트 참 → 합성 데이터 · 거짓 → N/A(응답에 계열별 출처가 없습니다) — 키가 있든 없든(짝)", () => {
  expect(studioSource({ data: GATE, isError: false })).toEqual(SYN);
  expect(studioSource({ data: { ...GATE, bok_configured: true, fred_configured: true }, isError: false })).toEqual(SYN);
  expect(studioSource({ data: { ...GATE, mock_allowed: false, real_mode: true }, isError: false })).toEqual(OFF);
  expect(studioSource({ data: { ...GATE, mock_allowed: false, real_mode: true, bok_configured: true, fred_configured: true }, isError: false })).toEqual(OFF);
});

test("받는 중이면 null · 받지 못하고 실패하면 N/A(합성 여부를 확인하지 못했습니다) · 받은 값은 다시 묻다 실패해도 그대로", () => {
  expect(studioSource({ data: undefined, isError: false })).toBeNull();
  expect(studioSource({ data: undefined, isError: true })).toEqual(FAILED);
  expect(studioSource({ data: GATE, isError: true })).toEqual(SYN);
  expect(studioSource({ data: { ...GATE, mock_allowed: false }, isError: true })).toEqual(OFF);
});
