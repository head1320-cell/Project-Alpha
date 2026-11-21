import { test, expect } from "./fixtures";
import {
  EMPTY, ago, andWith, append, arithmetic, compare, conditional, constant, fromParams, group, heldBefore, indicator, issuesOf, negate,
  regimeCondition, regimeIndicator, removeAt, setAt, sizeOf, timeWindow, toParams, usableIn, type Drafts,
} from "../src/features/intraday-rule-editor/tree";
import type { Grammar, Tree } from "../src/entities/intraday/types";

/**
 * 분봉 규칙 '직접 구성' 편집기의 순수 규칙(브라우저 없이) — 자유 조건식 설계 §6.2 · 구현 계획 f2
 *  · 편집기의 자료는 ★조건 나무 그 자체★다 — 화면만의 다른 모형이 없다. 편집 중의 빈 칸은 `null` · 고르지 않은 연산은 빈 글자.
 *  · ★출발값을 지어 넣지 않는다★ — 지표의 매개변수는 서버의 문법 표가 준 값, 상수 · 연산 · 봉 수 · 시각은 빈 채로 시작한다.
 *  · 빈 칸이 있으면 어느 자리에 몇 곳인지 말한다(보내기 전의 안내 — 판정은 서버가 한다).
 */

const G: Grammar = {
  slots: [{ key: "entry", label: "진입 조건", kind: "bool" }, { key: "entry_stop", label: "미리 건 매수 가격", kind: "number" },
          { key: "exit", label: "청산 조건", kind: "bool" }],
  entry_rule: "진입 조건과 미리 건 매수 가격 가운데 하나는 있어야 합니다.",
  indicators: [
    { name: "close", label: "종가", unit: "price", needs_prev: false, params: [], context: null },
    { name: "vwap", label: "VWAP", unit: "price", needs_prev: false, params: [], context: null },
    { name: "sma", label: "이동평균", unit: "price", needs_prev: false, context: null,
      params: [{ key: "n", label: "기간", type: "int", min: 1, max: 240, default: 20, unit: "봉" }] },
    { name: "bb_lower", label: "볼린저 하단", unit: "price", needs_prev: false, context: null,
      params: [{ key: "n", label: "기간", type: "int", min: 1, max: 240, default: 20, unit: "봉" },
               { key: "k", label: "표준편차 배수", type: "float", min: 0.5, max: 4, default: 2, unit: "배" }] },
    // 모형을 쓰는 지표(T2) — 모형 칸은 출발값이 없다(`type: "model"`) · 번호 칸은 수 칸이다
    { name: "day_type_is", label: "하루 유형", unit: "flag", needs_prev: false, context: "day_types",
      params: [{ key: "model", label: "모형", type: "model", kind: "day_type" },
               { key: "type", label: "유형 번호", type: "int", min: 1, max: 16, default: 1, unit: "번" }] },
  ],
  ops: [{ name: "held_before", label: "직전 봉 동안 계속", symbol: null, gives: "bool", args: ["bool"], variadic: null,
          extra: [{ key: "bars", label: "직전 봉 수", type: "int", min: 1, max: 240, unit: "봉" }] },
        { name: "ago", label: "N봉 전 값", symbol: null, gives: "number", args: ["number"], variadic: null,
          extra: [{ key: "bars", label: "봉 수", type: "int", min: 1, max: 240, unit: "봉" }] }],
  units: {}, limits: { nodes: 64, depth: 12 },
};

const close = () => indicator(G, "close");
const above = (): Tree => ({ op: "gt", args: [close(), indicator(G, "sma")] });
const below = (): Tree => ({ op: "lt", args: [close(), indicator(G, "vwap")] });
const only = (entry: Tree | null, rest: Partial<Drafts> = {}): Drafts => ({ ...EMPTY, entry, ...rest });

test("새 마디 — 지표는 서버가 준 출발값, 상수 · 연산 · 봉 수 · 시각은 빈 채로 시작한다", () => {
  expect(indicator(G, "sma")).toEqual({ ind: "sma", n: 20 });
  expect(indicator(G, "bb_lower")).toEqual({ ind: "bb_lower", n: 20, k: 2 });
  expect(indicator(G, "close")).toEqual({ ind: "close" });
  expect(constant()).toEqual({ const: null });
  expect(compare()).toEqual({ op: "", args: [null, null] });                 // 연산을 미리 골라 두지 않는다
  expect(timeWindow()).toEqual({ op: "time_between", args: [], from: "", to: "" });
  expect(heldBefore(above())).toEqual({ op: "held_before", bars: null, args: [above()] });
  expect(negate(above())).toEqual({ op: "not", args: [above()] });
  expect(arithmetic("mul", close())).toEqual({ op: "mul", args: [close(), null] });   // 앞의 값을 왼쪽 항으로 넘긴다
  expect(conditional(close())).toEqual({ op: "where", args: [null, close()] });
  expect(ago(close())).toEqual({ op: "ago", bars: null, args: [close()] });            // 앞의 값을 감싼다 · 봉 수는 비어서 시작한다(1 로 지어 넣지 않는다)
  expect(ago()).toEqual({ op: "ago", bars: null, args: [null] });
});

test("자리의 뿌리에 더하기 — 빈 자리면 그것이 뿌리 · 조건 하나에 더하면 '모두 충족'으로 묶인다 · 묶음에는 줄이 이어진다", () => {
  expect(append(null, above())).toEqual(above());
  expect(append(above(), below())).toEqual({ op: "and", args: [above(), below()] });
  const three = append(append(above(), below()), compare());
  expect(three).toEqual({ op: "and", args: [above(), below(), { op: "", args: [null, null] }] });   // 다시 묶지 않는다
  const either: Tree = { op: "or", args: [above(), below()] };
  expect(append(either, above())).toEqual({ op: "or", args: [above(), below(), above()] });         // 묶음의 종류를 바꾸지 않는다
  expect(append(negate(either), above())).toEqual({ op: "and", args: [negate(either), above()] });  // 감싼 것은 묶음이 아니다
});

test("고치기와 지우기 — 묶음의 줄은 빠지고, 비교의 변과 감싼 것의 안은 빈 칸이 되고, 뿌리는 빈 자리가 된다 (원본은 그대로)", () => {
  const root = group(above(), below(), compare());
  const frozen = JSON.stringify(root);
  expect(setAt(root, [1, 1], constant())).toEqual(group(above(), { op: "lt", args: [close(), { const: null }] }, compare()));
  expect(setAt(root, [], null)).toBeNull();
  expect(removeAt(root, [1])).toEqual(group(above(), compare()));
  expect(removeAt(root, [0, 1])).toEqual(group({ op: "gt", args: [close(), null] }, below(), compare()));
  expect(removeAt(negate(above()), [0])).toEqual({ op: "not", args: [null] });
  expect(removeAt(root, [])).toBeNull();
  expect(JSON.stringify(root)).toBe(frozen);
});

test("지워서 조건이 하나만 남은 묶음은 풀린다 — 더하면 묶이는 것의 짝 (직접 만든 빈 묶음 · 줄이 둘 이상 남는 묶음은 그대로)", () => {
  expect(removeAt(group(above(), below()), [1])).toEqual(above());                                    // 둘 → 하나: 묶음이 그 조건이 된다
  expect(removeAt(group(above(), below()), [0])).toEqual(below());
  expect(removeAt({ op: "or", args: [above(), below()] }, [0])).toEqual(below());
  expect(removeAt(group(above(), below(), compare()), [0])).toEqual(group(below(), compare()));       // 셋 → 둘: 묶음 그대로
  expect(removeAt(negate(group(above(), below())), [0, 1])).toEqual(negate(above()));                 // 감싼 것 안의 묶음도 같다
  expect(removeAt(group(above(), group(below(), compare())), [1, 0])).toEqual(group(above(), compare()));   // 안쪽 묶음만 풀린다
  expect(removeAt(group(above()), [0])).toEqual(group());                                             // 하나 → 없음: 직접 만든 묶음은 남는다(빈 채로)
  const back = append(removeAt(group(above(), below()), [1]), below());
  expect(back).toEqual(group(above(), below()));                                                      // 지웠다가 다시 더하면 처음 그대로다
});

test("빈 칸 찾기 — 아무것도 없으면 그 사유 하나, 다 채우면 문제없음 (짝)", () => {
  expect(issuesOf(EMPTY, G)).toEqual([G.entry_rule]);
  expect(issuesOf(only(null, { exit: below() }), G)).toEqual([G.entry_rule]);               // 청산만으로는 규칙이 아니다
  expect(issuesOf(only(above()), G)).toEqual([]);
  expect(issuesOf(only(null, { entry_stop: close() }), G)).toEqual([]);                     // 미리 건 매수 가격만 있어도 된다
  expect(issuesOf(only(group(above(), negate(heldBeforeBars(below(), 3)), window("0930", "1450")), { exit: below() }), G)).toEqual([]);
});

const heldBeforeBars = (child: Tree, bars: number | null): Tree => ({ ...heldBefore(child), bars });
const window = (from: string, to: string): Tree => ({ ...timeWindow(), from, to });

test("빈 칸 찾기 — 어느 자리에 몇 곳인지 말한다", () => {
  expect(issuesOf(only(compare()), G)).toEqual(["진입 조건: 비어 있는 칸이 3곳 있습니다."]);           // 왼쪽 값 · 연산 · 오른쪽 값
  expect(issuesOf(only({ op: "gt", args: [close(), constant()] }), G)).toEqual(["진입 조건: 비어 있는 칸이 1곳 있습니다."]);
  expect(issuesOf(only(above(), { exit: negate(null), entry_stop: arithmetic("add", close()) }), G)).toEqual([
    "미리 건 매수 가격: 비어 있는 칸이 1곳 있습니다.", "청산 조건: 비어 있는 칸이 1곳 있습니다."]);
  expect(issuesOf(only(null, { entry_stop: conditional(close()) }), G)).toEqual(["미리 건 매수 가격: 비어 있는 칸이 1곳 있습니다."]);
});

test("빈 칸 찾기 — 묶음의 줄 수 · 매개변수의 범위 · 직전 봉 수 · 시각 창", () => {
  expect(issuesOf(only(group(above())), G)).toEqual(["진입 조건: 묶음에는 조건이 둘 이상 있어야 합니다."]);
  expect(issuesOf(only(group()), G)).toEqual(["진입 조건: 묶음에는 조건이 둘 이상 있어야 합니다."]);
  const far: Tree = { op: "gt", args: [close(), { ind: "sma", n: 500 }] };
  expect(issuesOf(only(far), G)).toEqual(["진입 조건: 이동평균 기간은 1~240봉 범위로 입력하십시오."]);
  expect(issuesOf(only({ op: "gt", args: [close(), { ind: "sma", n: 2.5 }] }), G)).toEqual(["진입 조건: 이동평균 기간은 1~240봉 범위로 입력하십시오."]);
  expect(issuesOf(only({ op: "gt", args: [close(), { ind: "sma", n: null }] }), G)).toEqual(["진입 조건: 이동평균 기간은 1~240봉 범위로 입력하십시오."]);
  expect(issuesOf(only({ op: "lt", args: [close(), { ind: "bb_lower", n: 20, k: 2.5 }] }), G)).toEqual([]);          // 짝 — 소수 배수는 된다
  expect(issuesOf(only({ op: "gt", args: [{ ind: "sma", n: 500 }, { ind: "sma", n: 0 }] }), G)).toEqual(["진입 조건: 이동평균 기간은 1~240봉 범위로 입력하십시오."]);   // 같은 사유는 한 번만
  expect(issuesOf(only({ op: "gt", args: [close(), { ind: "gone" }] }), G)).toEqual(["진입 조건: 비어 있는 칸이 1곳 있습니다."]);      // 문법 표에 없는 지표 = 고르지 않은 칸
  for (const bars of [null, 0, 241, 1.5]) {
    expect(issuesOf(only(heldBeforeBars(above(), bars)), G), String(bars)).toEqual(["진입 조건: 직전 봉 수는 1~240봉 범위로 입력하십시오."]);
  }
  expect(issuesOf(only(heldBeforeBars(above(), 240)), G)).toEqual([]);
  // 'N봉 전 값'의 봉 수 — 범위는 문법 표의 그 연산에서 읽는다(화면에 따로 두지 않는다)
  const back = (bars: number | null, value: Tree | null = close()): Tree => ({ op: "gt", args: [close(), { op: "ago", bars, args: [value] }] });
  for (const bars of [null, 0, 241, 1.5]) {
    expect(issuesOf(only(back(bars)), G), `ago ${bars}`).toEqual(["진입 조건: 봉 수는 1~240봉 범위로 입력하십시오."]);
  }
  expect(issuesOf(only(back(1)), G)).toEqual([]);
  expect(issuesOf(only(back(240)), G)).toEqual([]);
  expect(issuesOf(only(back(3, null)), G)).toEqual(["진입 조건: 비어 있는 칸이 1곳 있습니다."]);                            // 감싼 안쪽의 빈 칸도 센다
  expect(issuesOf(only(back(3, { ind: "sma", n: 500 })), G)).toEqual(["진입 조건: 이동평균 기간은 1~240봉 범위로 입력하십시오."]);
  // 문법 표에 봉 수의 칸이 없으면(열화) 범위를 지어내지 않는다 — 1 이상의 정수인지만 보고 이름표는 연산마다 다르다
  const bare: typeof G = { ...G, ops: G.ops.map((o) => ({ ...o, extra: [] })) };
  for (const bars of [null, 0, 1.5]) {
    expect(issuesOf(only(back(bars)), bare), `bare ago ${bars}`).toEqual(["진입 조건: 봉 수는 1~ 범위로 입력하십시오."]);
    expect(issuesOf(only(heldBeforeBars(above(), bars)), bare), `bare held ${bars}`).toEqual(["진입 조건: 직전 봉 수는 1~ 범위로 입력하십시오."]);
  }
  expect(issuesOf(only(back(241)), bare)).toEqual([]);                                                                  // 상한을 모르면 막지 않는다(판정은 서버가 한다)
  expect(issuesOf(only(heldBeforeBars(above(), 241)), bare)).toEqual([]);
  expect(sizeOf(back(3))).toEqual({ nodes: 4, depth: 3 });                                                              // 감싼 것도 마디다(서버와 같은 법)
  for (const [from, to] of [["", ""], ["0930", ""], ["1500", "0900"], ["2460", "2500"], ["0960", "1000"], ["0900", "0961"], ["2400", "2400"]]) {   // 분은 59 까지 · 시는 23 까지
    expect(issuesOf(only(group(above(), window(from, to))), G), `${from}~${to}`).toEqual(["진입 조건: 시각 창의 시작과 종료를 확인하십시오."]);
  }
  expect(issuesOf(only(group(above(), window("0900", "0900"))), G)).toEqual([]);                                     // 같은 시각은 된다(끝 포함)
});

test("모형을 쓰는 지표(하루 유형) — 모형 칸은 비어서 시작하고 번호 칸은 출발값 · 모형을 고르지 않으면 그 자리가 말한다 · 모양이 맞는 열쇠면 말하지 않는다(짝)", () => {
  const typed = indicator(G, "day_type_is");
  expect(typed).toEqual({ ind: "day_type_is", model: null, type: 1 });                                   // 도구는 모형을 고르지 않는다
  const row = (node: Tree): Drafts => only({ op: "gt", args: [node, { const: 0.5 }] });
  const pick = "진입 조건: 하루 유형 모형을 고르십시오.";
  expect(issuesOf(row(typed), G)).toEqual([pick]);
  for (const bad of ["A".repeat(64), "ab".repeat(31), "ab".repeat(32) + "a", "g".repeat(64), 7]) {         // 대문자 · 짧음 · 긺 · 16진 밖 · 수
    expect(issuesOf(row({ ...typed, model: bad } as Tree), G), String(bad)).toEqual([pick]);
  }
  expect(issuesOf(row({ ...typed, model: "ab".repeat(32) } as Tree), G)).toEqual([]);                       // 짝 — 모양만 본다(내 모형인지 · 학습 기간은 서버가)
  expect(issuesOf(row({ ...typed, model: "ab".repeat(32), type: 17 } as Tree), G)).toEqual(["진입 조건: 하루 유형 유형 번호는 1~16번 범위로 입력하십시오."]);
  expect(issuesOf(row({ ...typed, model: "ab".repeat(32), type: 5 } as Tree), G)).toEqual([]);              // 그 모형의 유형 수는 목록이 모른다 — 칸과 서버가 말한다
  // 같은 자리에 두 번 써도 문장은 한 번 · 다른 자리면 자리마다
  expect(issuesOf(only(group(row(typed).entry as Tree, row(typed).entry as Tree)), G)).toEqual([pick]);
  expect(issuesOf(only(row(typed).entry, { exit: row(typed).entry }), G)).toEqual([pick, "청산 조건: 하루 유형 모형을 고르십시오."]);
  expect(toParams(row({ ...typed, model: "ab".repeat(32), type: 3 } as Tree)).entry)
    .toEqual({ op: "gt", args: [{ ind: "day_type_is", model: "ab".repeat(32), type: 3 }, { const: 0.5 }] });  // 보내는 꼴에 열쇠가 그대로
});

test("마디 수 — 자리 셋을 합쳐 세고 상한을 넘으면 말한다 (짝: 딱 상한이면 된다)", () => {
  const wide = (n: number): Tree => group(...Array.from({ length: n }, (_, i): Tree => ({ op: "gt", args: [close(), { const: i }] })));
  expect(sizeOf(above())).toEqual({ nodes: 3, depth: 2 });
  expect(sizeOf(wide(21))).toEqual({ nodes: 64, depth: 3 });
  expect(sizeOf(null)).toEqual({ nodes: 0, depth: 0 });
  expect(issuesOf(only(wide(20), { exit: below() }), G)).toEqual([]);                                                  // 61 + 3 = 64
  expect(issuesOf(only(wide(20), { exit: group(below(), above()) }), G)).toEqual(["조건의 마디 수가 상한 64개를 넘었습니다(지금 68개)."]);
});

test("서버로 보내는 꼴 — 빈 자리는 싣지 않는다 · 서버가 준 나무를 실으면 그대로 돌아온다", () => {
  expect(toParams(only(above(), { exit: below() }))).toEqual({ entry: above(), exit: below() });
  expect(toParams(only(null, { entry_stop: close() }))).toEqual({ entry_stop: close() });
  const fromServer = { entry: { op: "cross_up", args: [{ ind: "close" }, { const: 10050 }] }, exit: below() };
  expect(fromParams(fromServer)).toEqual({ entry: fromServer.entry, entry_stop: null, exit: fromServer.exit });
  expect(toParams(fromParams(fromServer))).toEqual(fromServer);
  expect(fromParams({ entry: above(), stop: below() } as Record<string, Tree>)).toEqual(only(above()));               // 모르는 자리는 싣지 않는다
});

// ── 국면 조건(K3) — 고르기 칸 · 출발값 없는 수 칸 · 쓸 수 있는 자리 · '모두 충족'으로 잇기 ─────────────────────────────
const REGIME = {
  name: "regime_prob", label: "시장 국면 확률", unit: "prob", needs_prev: false, context: "regimes", slots: ["entry" as const],
  params: [
    { key: "index", label: "지수", type: "pick" as const, default: null,
      choices: [{ value: "KOSPI", label: "코스피" }, { value: "KOSDAQ", label: "코스닥" }] },
    { key: "k", label: "국면 수", type: "int" as const, min: 2, max: 4, default: null, unit: "개" },
    { key: "state", label: "국면 번호", type: "int" as const, min: 1, max: 4, default: null, unit: "번" },
  ],
};
const GR: Grammar = { ...G, indicators: [...G.indicators, REGIME] };
const regimeOk = (): Tree => ({ op: "gt", args: [{ ind: "regime_prob", index: "KOSPI", k: 3, state: 2 }, { const: 0.6 }] });

test("국면 조건 — 지수 · 국면 수 · 국면 번호 · 연산 · 상수는 비어서 시작한다(도구가 고르지 않는다)", () => {
  expect(indicator(GR, "regime_prob")).toEqual({ ind: "regime_prob", index: null, k: null, state: null });
  expect(regimeCondition(GR, "regime_prob")).toEqual({ op: "", args: [{ ind: "regime_prob", index: null, k: null, state: null }, { const: null }] });
  expect(regimeIndicator(GR)?.name).toBe("regime_prob");
  expect(regimeIndicator(G)).toBeNull();                                                       // 짝 — 그 지표가 없는 문법 표에는 단추를 내지 않는다
});

test("국면 조건 — 빈 고르기 칸 · 빈 수 칸은 그 자리가 말하고, 다 고르면 말하지 않는다(짝)", () => {
  const blank: Tree = { op: "gt", args: [indicator(GR, "regime_prob"), { const: 0.6 }] };
  expect(issuesOf(only(blank), GR)).toEqual([
    "진입 조건: 시장 국면 확률 지수를 고르십시오.",
    "진입 조건: 시장 국면 확률 국면 수는 2~4개 범위로 입력하십시오.",
    "진입 조건: 시장 국면 확률 국면 번호는 1~4번 범위로 입력하십시오.",
  ]);
  const bad: Tree = { op: "gt", args: [{ ind: "regime_prob", index: "KOSPI200", k: 3, state: 2 }, { const: 0.6 }] };
  expect(issuesOf(only(bad), GR)).toEqual(["진입 조건: 시장 국면 확률 지수를 고르십시오."]);   // 보기에 없는 값도 고른 것이 아니다
  expect(issuesOf(only(regimeOk()), GR)).toEqual([]);
});

test("국면 조건 — 지표 목록은 쓸 수 있는 자리에서만(진입 조건) · 다른 지표는 어디서나", () => {
  expect(usableIn(REGIME, "entry")).toBe(true);
  expect(usableIn(REGIME, "exit")).toBe(false);
  expect(usableIn(REGIME, "entry_stop")).toBe(false);
  expect(G.indicators.every((i) => usableIn(i, "exit") && usableIn(i, "entry_stop"))).toBe(true);   // 짝 — `slots` 가 없으면 어디나
});

test("국면 조건 — '모두 충족'으로 잇는다: 빈 자리면 그것 · '모두 충족' 뿌리면 그 줄에 · '하나 이상 충족' 뿌리는 그 안이 아니라 함께 묶는다", () => {
  const r = regimeOk();
  expect(andWith(null, r)).toEqual(r);
  expect(andWith(group(above(), below()), r)).toEqual(group(above(), below(), r));
  const either: Tree = { op: "or", args: [above(), below()] };
  expect(andWith(either, r)).toEqual(group(either, r));                                       // 틀의 '하나 이상 충족'을 그대로 두고 전체에 건다
  expect(append(either, r)).toEqual({ op: "or", args: [above(), below(), r] });              // 짝 — 보통의 '조건 추가'는 묶음 안에 더한다
  expect(andWith(above(), r)).toEqual(group(above(), r));
  expect(andWith(negate(above()), r)).toEqual(group(negate(above()), r));
});
