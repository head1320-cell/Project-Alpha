import { test, expect } from "./fixtures";
import {
  NO_AS_OF, PROVENANCE_HEADER, astCsvText, computedAtText, condCsvText, provenanceCells, resultTimes, sourceText, type RunRequest,
} from "../src/widgets/screener/screenerCsv";
import type { FilterConditionNode, FilterGroupNode } from "../src/shared/model/domain";

/**
 * 종목 찾기 내보내기의 출처 열 — 순수 규칙(브라우저 없이) · U1-e · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`
 *  · 데이터 출처: 서버 게이트의 네 상태(합성 · 합성 아님 · 확인 실패 · 확인 전) — 모르면 N/A + 사유(합성이라고도 아니라고도 하지 않는다)
 *  · 계산 시각: 응답의 글자를 바꾸지 않는다(시간대를 붙이거나 옮기지 않는다) · 없으면 N/A + 사유
 *  · 조건식: 보낸 꼴 그대로 — 이름(식별자) · 연산자 · 값 · ★값이 없으면 N/A(0 이 아니다)★ · 모르는 연산자와 모르는 꼴은 그 사실과 원문
 *  · 묶음: and · or · 안쪽 묶음은 괄호 · 아무 조건도 없으면 '조건 없음'
 */

const LABELS: Record<string, string> = { per: "PER", roe: "ROE", market_cap_억: "시가총액", rsi_14: "RSI(14)" };
const label = (id: string) => LABELS[id] ?? id;
const f = (field: string, op: FilterConditionNode["op"], value: number | null | undefined): FilterConditionNode => ({ kind: "field", field, op, value });
const and = (conditions: FilterConditionNode[], groups: FilterGroupNode[] = []): FilterGroupNode => ({ logic: "AND", conditions, groups });
const or = (conditions: FilterConditionNode[], groups: FilterGroupNode[] = []): FilterGroupNode => ({ logic: "OR", conditions, groups });

test("데이터 출처 — 서버 게이트의 네 상태 · 확인 실패는 게이트 값보다 앞선다 · 모르면 N/A + 사유", () => {
  expect(sourceText({ error: false, mockAllowed: true })).toBe("합성 시세");
  expect(sourceText({ error: false, mockAllowed: false })).toBe("합성 아님 · 등급 미상");
  expect(sourceText({ error: true, mockAllowed: true }), "읽지 못한 값은 앞서 읽은 값이 아니다").toBe("N/A(출처 확인 실패)");
  expect(sourceText({ error: false, mockAllowed: undefined })).toBe("N/A(출처 확인 전)");
  expect(sourceText({ error: false, mockAllowed: null })).toBe("N/A(출처 확인 전)");
});

test("계산 시각 — 응답의 글자 그대로(시간대를 붙이거나 옮기지 않는다) · 없으면 N/A + 사유", () => {
  expect(computedAtText("2026-11-21T06:50:12.123456")).toBe("2026-11-21T06:50:12.123456");
  expect(computedAtText("2026-11-21T06:50:12+09:00")).toBe("2026-11-21T06:50:12+09:00");
  for (const v of ["", "  ", null, undefined, 0, 1732171812]) expect(computedAtText(v), String(v)).toBe("N/A(응답에 계산 시각이 없습니다)");
  expect(NO_AS_OF).toMatch(/^N\/A\(.+\)$/);
});

test("조건 하나 — 이름(식별자) · 연산자 · 값 / 이름이 식별자와 같으면 한 번만", () => {
  expect(condCsvText(f("per", "lte", 12.5), label)).toBe("PER(per) ≤ 12.5");
  expect(condCsvText(f("roe", "gte", 10), label)).toBe("ROE(roe) ≥ 10");
  expect(condCsvText(f("pbr", "lt", 1), label), "카탈로그에 이름이 없으면 식별자만").toBe("pbr < 1");
  expect(condCsvText(f("per", "gt", 3), label)).toBe("PER(per) > 3");
  expect(condCsvText(f("per", "eq", 3), label)).toBe("PER(per) = 3");
  expect(condCsvText({ kind: "field", field: "per", op: "between", value: 3, value2: 12 }, label)).toBe("PER(per) 3 ~ 12");
  expect(condCsvText({ field: "per", op: "lt", value: 9 }, label), "꼴이 적히지 않은 조건은 필드다").toBe("PER(per) < 9");
});

test("★값이 없으면 N/A — 0 이 아니다★ ↔ 값 0 은 0(짝) · 연산자가 없거나 모르면 그 사실을 적는다", () => {
  expect(condCsvText(f("per", "lte", null), label)).toBe("PER(per) ≤ N/A");
  expect(condCsvText(f("per", "lte", undefined), label)).toBe("PER(per) ≤ N/A");
  expect(condCsvText(f("per", "lte", Number.NaN), label)).toBe("PER(per) ≤ N/A");
  expect(condCsvText(f("per", "lte", 0), label)).toBe("PER(per) ≤ 0");
  expect(condCsvText({ kind: "field", field: "per", value: 5 }, label), "연산자를 짐작하지 않는다").toBe("PER(per) [연산자 없음] 5");
  expect(condCsvText({ kind: "field", field: "per", op: "zz" as FilterConditionNode["op"], value: 5 }, label)).toBe("PER(per) [연산자 zz] 5");
  expect(condCsvText({ kind: "field", field: "per", op: "between", value: 3, value2: null }, label)).toBe("PER(per) 3 ~ N/A");
});

test("순위 조건 · 기술 지표(지표 식별자) · 이 화면이 짓지 않는 꼴은 꼴의 이름과 원문", () => {
  expect(condCsvText({ kind: "field", field: "roe", rank_mode: "top_pct", rank_value: 10 }, label)).toBe("ROE(roe) 상위 10%");
  expect(condCsvText({ kind: "field", field: "roe", rank_mode: "bottom_pct", rank_value: 20 }, label)).toBe("ROE(roe) 하위 20%");
  expect(condCsvText({ kind: "field", field: "roe", rank_mode: "top_n", rank_value: 30 }, label)).toBe("ROE(roe) 상위 30종목");
  expect(condCsvText({ kind: "field", field: "roe", rank_mode: "top_pct", rank_value: null }, label)).toBe("ROE(roe) 상위 N/A%");
  expect(condCsvText({ kind: "technical", field: "rsi_14", indicator: "rsi_14", op: "lt", value: 30 }, label)).toBe("RSI(14)(rsi_14) < 30");
  const ev: FilterConditionNode = { kind: "event", field: "", event_type: "dividend", within_days: 30 };
  const t = condCsvText(ev, label);
  expect(t.startsWith("[event] "), t).toBe(true);
  expect(JSON.parse(t.slice("[event] ".length)), "원문을 그대로 싣는다").toEqual(ev);
});

test("묶음 — and · or · 안쪽 묶음은 괄호(하나뿐이면 괄호 없이) · 아무 조건도 없으면 '조건 없음'", () => {
  expect(astCsvText(and([]), label)).toBe("조건 없음");
  expect(astCsvText(and([f("per", "lte", 12.5)]), label)).toBe("PER(per) ≤ 12.5");
  expect(astCsvText(and([f("per", "lte", 12.5), f("roe", "gte", 10)]), label)).toBe("PER(per) ≤ 12.5 and ROE(roe) ≥ 10");
  expect(astCsvText(or([f("per", "lte", 12.5), f("roe", "gte", 10)]), label)).toBe("PER(per) ≤ 12.5 or ROE(roe) ≥ 10");
  const mcap = f("market_cap_억", "gte", 2000);
  expect(astCsvText(and([mcap], [or([f("per", "lte", 12.5), f("roe", "gte", 10)])]), label))
    .toBe("시가총액(market_cap_억) ≥ 2000 and (PER(per) ≤ 12.5 or ROE(roe) ≥ 10)");
  expect(astCsvText(and([mcap], [and([f("per", "lte", 12.5)])]), label), "하나뿐인 안쪽 묶음").toBe("시가총액(market_cap_억) ≥ 2000 and PER(per) ≤ 12.5");
  expect(astCsvText(and([mcap], [and([])]), label)).toBe("시가총액(market_cap_억) ≥ 2000 and (조건 없음)");
});

test("줄마다 붙는 출처 칸 — 머리의 차례 그대로 다섯 · 일부만 평가 · 유동성 게이트 켬 ↔ 끔(짝)", () => {
  const req: RunRequest = { universe: "kosdaq150", universeLabel: "코스닥 150", ast: and([f("per", "lte", 12.5)]), gateOn: false };
  const cells = provenanceCells({ source: { error: false, mockAllowed: true }, timestamp: "2026-11-21T06:50:12", capped: false, req, label });
  expect(cells.length).toBe(PROVENANCE_HEADER.length);
  expect(cells).toEqual(["합성 시세", NO_AS_OF, "2026-11-21T06:50:12", "코스닥 150(kosdaq150)", "PER(per) ≤ 12.5 · 유동성 게이트 끔"]);
  const on = provenanceCells({ source: { error: false, mockAllowed: false }, timestamp: null, capped: true, req: { ...req, gateOn: true }, label });
  expect(on).toEqual(["합성 아님 · 등급 미상", NO_AS_OF, "N/A(응답에 계산 시각이 없습니다)", "코스닥 150(kosdaq150) · 일부만 평가(서버의 평가 상한)", "PER(per) ≤ 12.5 · 유동성 게이트 켬"]);
  expect(PROVENANCE_HEADER).toEqual(["데이터 출처", "자료 기준 시각", "계산 시각(서버 · 시간대 표기 없음)", "유니버스", "조건식"]);
});

// U2-d — 화면의 출처 표지는 CSV 의 '계산 시각' 칸과 같은 판단 · 같은 사유(구현 뒤에 더했다 — 빨강은 변이로 본다).
test("화면의 출처 표지(U2-d): 계산 시각은 응답 글자 그대로 + 시계 표기 · 없으면 CSV 와 같은 사유의 N/A · 자료 기준 시각은 N/A + 사유(짝)", () => {
  expect(resultTimes("2026-11-21T09:30:05.1")).toEqual([
    { label: "계산 시각", value: "2026-11-21T09:30:05.1(서버 시계 · 시간대 표기 없음)" },
    { label: "자료 기준 시각", unknown: "응답에 없습니다" },
  ]);
  expect(computedAtText("2026-11-21T09:30:05.1"), "짝 — CSV 의 칸은 같은 글자").toBe("2026-11-21T09:30:05.1");
  for (const bad of [undefined, null, "", "   ", 0, 1_763_700_000]) {
    expect(resultTimes(bad)[0], `화면 ${String(bad)}`).toEqual({ label: "계산 시각", unknown: "응답에 계산 시각이 없습니다" });
    expect(computedAtText(bad), `CSV ${String(bad)} — 같은 사유`).toBe("N/A(응답에 계산 시각이 없습니다)");
  }
});
