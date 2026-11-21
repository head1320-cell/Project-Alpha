import { test, expect } from "./fixtures";
import { clockText } from "../src/shared/lib/krFormat";
import { freshnessText, provChips } from "../src/shared/ui/provenance/provenance";

/**
 * 출처 표지 · 갱신 시각의 순수 규칙(브라우저 없이) — U2-a · 설계 문서 §5.1 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u2-provenance.md`
 *  · 축의 차례는 늘 같다: 출처 → 시각들 → 시점 정합 → 덧붙임(넣은 차례와 무관 · 축을 섞지 않는다)
 *  · 합성은 practice(어떤 밀도에서도 숨기지 않는 꼴) · 응답이 말한 출처는 plain · 모르면 'N/A(사유)'(unknown)
 *  · ★사유가 빈 '모름' 과 값이 빈 시각은 그리지 않고 실패한다★(사유 없는 N/A 를 만들 수 없다)
 *  · 시각: 값이 있으면 '이름 값'(plain) · 없으면 '이름 N/A(사유)'(unknown) · 근거의 종류는 ev(source · asof · pit)
 *  · 갱신 시각: 'N초마다 다시 읽습니다 · 마지막 수신 hh:mm:ss' · 받기 전은 N/A + 사유 · 주기가 없으면 앞 절 없이
 *  · 이 기기 시각(24시 · 두 자리) — 받은 적이 없으면(0 · 음수 · 유한하지 않은 값) null
 */

const AT = new Date(2026, 10, 21, 9, 5, 3).getTime(); // 이 기기의 09:05:03(시간대와 무관하게 만든 값)

test("시각: 24시 두 자리 · 받은 적이 없으면 null(짝: 받은 때는 글자)", () => {
  expect(clockText(AT)).toBe("09:05:03");
  expect(clockText(new Date(2026, 10, 21, 23, 59, 59).getTime())).toBe("23:59:59");
  expect(clockText(new Date(2026, 10, 21, 0, 0, 0).getTime())).toBe("00:00:00");
  for (const v of [0, -1, Number.NaN, Number.POSITIVE_INFINITY, null, undefined]) expect(clockText(v), String(v)).toBeNull();
});

test("갱신 시각: 주기 + 마지막 수신 · 받기 전은 N/A + 사유 · 주기가 없으면 앞 절 없이", () => {
  expect(freshnessText({ updatedAt: AT, intervalMs: 5000 })).toBe("5초마다 다시 읽습니다 · 마지막 수신 09:05:03");
  expect(freshnessText({ updatedAt: AT, intervalMs: 10_000 })).toBe("10초마다 다시 읽습니다 · 마지막 수신 09:05:03");
  expect(freshnessText({ updatedAt: AT, intervalMs: 1500 })).toBe("1.5초마다 다시 읽습니다 · 마지막 수신 09:05:03");
  expect(freshnessText({ updatedAt: 0, intervalMs: 5000 })).toBe("5초마다 다시 읽습니다 · 마지막 수신 N/A(아직 받은 값이 없습니다)");
  expect(freshnessText({ updatedAt: AT })).toBe("마지막 수신 09:05:03");
  for (const iv of [0, -1000, Number.NaN, null]) {
    expect(freshnessText({ updatedAt: AT, intervalMs: iv }), `주기 ${iv}`).toBe("마지막 수신 09:05:03");
  }
});

test("출처 표지: 축의 차례는 늘 출처 → 시각들 → 시점 정합 → 덧붙임(넣은 차례와 무관)", () => {
  const chips = provChips({
    notes: [{ label: "일부만 평가(서버의 평가 상한)" }],
    pit: { label: "시점 정합: 확인 안 됨", tone: "unknown" },
    times: [{ label: "계산 시각", value: "2026-11-21 09:05:03" }, { label: "자료 기준 시각", unknown: "응답에 없습니다" }],
    source: { kind: "synthetic", label: "합성 데이터" },
  });
  expect(chips.map((c) => c.label)).toEqual([
    "합성 데이터", "계산 시각 2026-11-21 09:05:03", "자료 기준 시각 N/A(응답에 없습니다)", "시점 정합: 확인 안 됨", "일부만 평가(서버의 평가 상한)",
  ]);
  expect(chips.map((c) => c.ev ?? null)).toEqual(["source", "asof", "asof", "pit", null]);
  // 덧붙임의 기본은 중립(plain) — 출처 표지는 중립 색조이고 파랑은 하락 · 링크에만 남는다(ADR 007 §5.3 · §5.4).
  expect(chips.map((c) => c.tone)).toEqual(["practice", "plain", "unknown", "unknown", "plain"]);
  // 짝: 부르는 쪽이 '가정'이라 적으면 그 꼴 그대로다(기본값이 모든 덧붙임을 덮지 않는다).
  expect(provChips({ notes: [{ label: "수수료 가정 0.015%", tone: "assumed" }] })).toEqual([{ label: "수수료 가정 0.015%", tone: "assumed" }]);
});

test("출처: 합성은 practice · 응답이 말한 출처는 plain · 모르면 'N/A(사유)'(짝: 셋의 꼴이 서로 다르다)", () => {
  const [syn] = provChips({ source: { kind: "synthetic", label: "합성 시세" } });
  const [known] = provChips({ source: { kind: "known", label: "실제 분봉" } });
  const [unk] = provChips({ source: { kind: "unknown", reason: "응답에 계열별 출처가 없습니다" } });
  const [unkNamed] = provChips({ source: { kind: "unknown", label: "분봉 출처", reason: "등급이 없습니다" } });
  expect(syn).toEqual({ label: "합성 시세", tone: "practice", ev: "source" });
  expect(known).toEqual({ label: "실제 분봉", tone: "plain", ev: "source" });
  expect(unk).toEqual({ label: "출처 N/A(응답에 계열별 출처가 없습니다)", tone: "unknown", ev: "source" });
  expect(unkNamed.label).toBe("분봉 출처 N/A(등급이 없습니다)");
  expect(new Set([syn.tone, known.tone, unk.tone]).size).toBe(3);
});

test("★사유가 빈 '모름' · 값이 빈 시각은 그리지 않고 실패한다★(짝: 사유 · 값이 있으면 칩이 선다)", () => {
  for (const blank of ["", "   "]) {
    expect(() => provChips({ source: { kind: "unknown", reason: blank } }), `출처 사유 '${blank}'`).toThrow();
    expect(() => provChips({ times: [{ label: "자료 기준 시각", unknown: blank }] }), `시각 사유 '${blank}'`).toThrow();
    expect(() => provChips({ times: [{ label: "계산 시각", value: blank }] }), `시각 값 '${blank}'`).toThrow();
  }
  expect(provChips({ source: { kind: "unknown", reason: "x" } })).toHaveLength(1);
  expect(provChips({ times: [{ label: "자료 기준 시각", unknown: "x" }] })).toHaveLength(1);
  expect(provChips({ times: [{ label: "계산 시각", value: "x" }] })).toHaveLength(1);
});

test("빈 입력은 칩 0 · 없는 축은 칸을 만들지 않는다(짝: 축 하나면 칩 하나)", () => {
  expect(provChips({})).toEqual([]);
  expect(provChips({ source: null, times: [], pit: null, notes: [] })).toEqual([]);
  expect(provChips({ pit: { label: "시점 정합: 확인", tone: "ok" } })).toEqual([{ label: "시점 정합: 확인", tone: "ok", ev: "pit" }]);
});
