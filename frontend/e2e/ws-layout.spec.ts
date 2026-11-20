import { test, expect } from "./fixtures";
import {
  activate, areaName, checkName, close, colSplit, colWidths, defaultLayout, eul, exportFile, fits, fold, importFile, move, readLayout, readSaved,
  removeNamed, renameNamed, reopen, ro, rowByDrag, rowByKey, saveNamed, strictLayout,
  type Area, type Col, type Layout, type ScreenSpec,
} from "../src/shared/ui/workspace/layout";
import { dropAt, type Geometry } from "../src/shared/ui/workspace/dnd";
import { INTRADAY_WS } from "../src/widgets/intraday/workspaceSpec";

/**
 * 판 배치의 순수 규칙(브라우저 없이) — 설계 §5 · 계획 §9.2
 *  · 배치 꼴 v1: 열 1 ~ 3 · 열마다 칸 1 ~ 2 · 판은 탭과 닫힌 판을 통틀어 정확히 한 번 · 남는 폭 열(w = null) 정확히 하나 · 아래 칸 높이 0.2 ~ 0.8(0.05 걸음).
 *  · 내 저장을 읽을 때는 고쳐 읽고 ★사유를 남긴다★(침묵 폴백 금지) · 가져오기는 사유가 하나라도 있으면 거절한다(엄격).
 *  · 옮기기 · 닫기 · 다시 열기는 같은 함수 — 판 메뉴와 끌어 놓기가 같은 꼴을 낸다. 접기(fold)는 그릴 때만이고 저장 꼴을 바꾸지 않는다.
 */

const area = (tabs: string[], active = tabs[0], h?: number): Area => (h === undefined ? { tabs, active } : { tabs, active, h });
const col = (w: number | null, ...rows: Area[]): Col => ({ w, rows });
const lay = (cols: Col[], closed: string[] = []): Layout => ({ v: 1, screen: "t", cols, closed });

const SPEC: ScreenSpec = {
  screen: "t",
  panels: [
    { id: "a", name: "설정", min: 440, closable: false },
    { id: "b", name: "결과", min: 640, closable: false },
    { id: "c", name: "판정", min: 400, closable: true },
    { id: "d", name: "봉과 체결", min: 400, closable: true },
    { id: "e", name: "하루 유형", min: 320, closable: true },
  ],
  presets: [
    { id: "two", name: "두 열", layout: lay([col(480, area(["a"])), col(null, area(["b", "c", "d", "e"]))]) },
    { id: "three", name: "세 열", layout: lay([col(480, area(["a"])), col(null, area(["b", "c"])), col(480, area(["d", "e"]))]) },
    { id: "top", name: "차트 위", layout: lay([col(480, area(["a"])), col(null, area(["d"]), area(["b", "c", "e"], "b", 0.5))]) },
  ],
  first: "two",
};
const TWO = (): Layout => defaultLayout(SPEC);
const THREE = (): Layout => structuredClone(SPEC.presets[1].layout);
/** 옮긴 뒤의 배치(거절이면 undefined) — 결과 꼴을 좁혀 읽는다. */
const layoutOf = (r: ReturnType<typeof move>): Layout | undefined => (r.ok ? r.layout : undefined);

test.describe("readLayout — 내 저장을 읽기(고쳐 읽고 사유를 남긴다)", () => {
  test("저장이 없으면 처음 배치 · 사유 없음 ↔ 맞는 꼴은 그대로 · 사유 없음(글로도 · 객체로도)", () => {
    for (const raw of [null, undefined]) {
      const r = readLayout(raw, SPEC);
      expect(r).toEqual({ layout: TWO(), notes: [], fallback: false });
    }
    for (const raw of [THREE(), JSON.stringify(THREE())]) {
      const r = readLayout(raw, SPEC);
      expect(r.notes).toEqual([]);
      expect(r.fallback).toBe(false);
      expect(r.layout).toEqual(THREE());
    }
  });

  test("꼴이 무너졌으면 처음 배치 + 사유: JSON 아님 · 객체 아님 · v2 · v 없음 · 다른 화면 · 열 0 · 열 넷 · 칸 셋 · 칸 꼴", () => {
    const bad: [unknown, string][] = [
      ["{oops", "JSON"],
      ["[1,2]", "배치 꼴이 아닙니다"],
      [{ ...THREE(), v: 2 }, "v2"],
      [{ screen: "t", cols: THREE().cols, closed: [] }, "꼴 판(v)이 없습니다"],
      [{ ...THREE(), screen: "my-account" }, "다른 화면(‘my-account’)"],
      [{ ...THREE(), cols: [] }, "받은 수 0"],
      [{ ...THREE(), cols: [...THREE().cols, col(300, area(["e"]))] }, "받은 수 4"],
      [lay([col(480, area(["a"])), col(null, area(["b"]), area(["c"], "c", 0.5), area(["d", "e"], "d", 0.3))]), "칸은 열마다"],
      [lay([col(480, area(["a"])), col(null, { tabs: "b", active: "b" } as unknown as Area)]), "칸의 꼴"],
    ];
    for (const [raw, frag] of bad) {
      const r = readLayout(raw, SPEC);
      expect(r.fallback, frag).toBe(true);
      expect(r.layout, frag).toEqual(TWO());
      expect(r.notes.join(" "), frag).toContain(frag);
    }
  });

  test("모르는 판은 빼고 사유 · 겹친 판은 뒤 자리를 빼고 사유 · 짝: 아는 판만 있으면 사유 없음", () => {
    const r = readLayout(lay([col(480, area(["a", "zz"])), col(null, area(["b", "c", "d", "e", "c"]))]), SPEC);
    expect(r.fallback).toBe(false);
    expect(r.layout).toEqual(TWO());
    expect(r.notes).toEqual(["모르는 판 ‘zz’를 뺐습니다.", "겹친 판 ‘판정’의 뒤 자리를 뺐습니다."]);
  });

  test("닫기 없는 판이 닫혀 있으면 첫 칸에 다시 열고 사유 ↔ 닫기 있는 판이 닫혀 있으면 그대로(사유 없음)", () => {
    const r = readLayout(lay([col(null, area(["b", "c", "d"]))], ["a", "e"]), SPEC);
    expect(r.layout).toEqual(lay([col(null, area(["b", "c", "d", "a"]))], ["e"]));
    expect(r.notes).toEqual(["닫을 수 없는 판 ‘설정’을 첫 칸에 다시 열었습니다."]);
  });

  test("빠진 판: 닫기 있는 판은 닫힌 판으로 · 닫기 없는 판은 첫 칸에 — 둘 다 사유", () => {
    const r = readLayout(lay([col(480, area(["a"])), col(null, area(["c", "d"]))]), SPEC);
    expect(r.layout).toEqual(lay([col(480, area(["a", "b"])), col(null, area(["c", "d"]))], ["e"]));
    expect(r.notes).toEqual(["빠진 판 ‘결과’를 첫 칸에 두었습니다.", "빠진 판 ‘하루 유형’을 닫힌 판으로 두었습니다."]);
  });

  test("판을 빼고 빈 칸 · 빈 열은 접는다 · 앞 탭이 칸에 없으면 첫 탭으로 고치고 사유", () => {
    const r = readLayout(lay([col(480, area(["a"])), col(300, area(["zz"])), col(null, area(["b", "c", "d", "e"], "q"))]), SPEC);
    expect(r.layout).toEqual(TWO());
    expect(r.notes).toEqual(["모르는 판 ‘zz’를 뺐습니다.", "앞 탭이 그 칸에 없어 첫 탭으로 고쳤습니다(셋째 열)."]);
  });

  test("남는 폭 열: 없으면 마지막 열 · 여럿이면 마지막 하나만 남기고 나머지는 최소 폭 · 폭이 수가 아니면 최소 폭 — 모두 사유", () => {
    const none = readLayout(lay([col(480, area(["a"])), col(700, area(["b", "c", "d", "e"]))]), SPEC);
    expect(none.layout.cols.map((c) => c.w)).toEqual([480, null]);
    expect(none.notes).toEqual(["남는 폭 열이 없어 마지막 열을 남는 폭으로 했습니다."]);
    const many = readLayout(lay([col(null, area(["a"])), col(null, area(["b", "c", "d", "e"]))]), SPEC);
    expect(many.layout.cols.map((c) => c.w)).toEqual([440, null]);
    expect(many.notes).toEqual(["남는 폭 열이 여럿이라 마지막 하나만 남겼습니다(첫째 열은 최소 폭)."]);
    for (const w of ["480", -5, 0, Number.NaN, Number.POSITIVE_INFINITY]) {
      const r = readLayout(lay([col(w as unknown as number, area(["a"])), col(null, area(["b", "c", "d", "e"]))]), SPEC);
      expect(r.layout.cols[0].w, String(w)).toBe(440);
      expect(r.notes, String(w)).toEqual(["열 폭이 양의 수가 아니어서 최소 폭으로 고쳤습니다(첫째 열)."]);
    }
  });

  test("아래 칸 높이: 0.2 ~ 0.8 · 0.05 걸음 밖이면 고치고 사유 · 위 칸의 h 는 쓰지 않는다 ↔ 맞는 값은 그대로", () => {
    const at = (h: unknown) => readLayout(lay([col(480, area(["a"])), col(null, area(["b"], "b", 0.3), area(["c", "d", "e"], "c", h as number))]), SPEC);
    expect(at(0.35).notes).toEqual([]);
    expect(at(0.35).layout.cols[1].rows[1].h).toBe(0.35);
    expect(at(0.35).layout.cols[1].rows[0]).toEqual({ tabs: ["b"], active: "b" });
    for (const [h, fixed] of [[0.95, 0.8], [0.1, 0.2], [0.42, 0.4], ["x", 0.5], [undefined, 0.5]] as [unknown, number][]) {
      const r = at(h);
      const shown = h === undefined ? "없음" : String(h);
      expect(r.layout.cols[1].rows[1].h, shown).toBe(fixed);
      expect(r.notes, shown).toEqual([`아래 칸 높이를 고쳤습니다(받은 값 ${shown} · 고친 값 ${fixed} · 0.2 ~ 0.8 · 0.05 걸음).`]);
    }
  });

  test("strictLayout(가져오기): 사유가 하나라도 있으면 거절 · 사유 목록 ↔ 맞는 꼴은 받는다", () => {
    expect(strictLayout(THREE(), SPEC)).toEqual({ ok: true, layout: THREE() });
    const r = strictLayout(lay([col(480, area(["a", "zz"])), col(null, area(["b", "c", "d", "e"]))]), SPEC);
    expect(r).toEqual({ ok: false, reasons: ["모르는 판 ‘zz’를 뺐습니다."] });
    expect(strictLayout({ ...THREE(), v: 2 }, SPEC).ok).toBe(false);
    expect(strictLayout(null, SPEC)).toEqual({ ok: false, reasons: ["배치가 없습니다."] });
  });
});

test.describe("move — 판 메뉴와 끌어 놓기가 부르는 한 함수", () => {
  test("다른 칸의 탭 자리로: 옮긴 판이 앞 탭 · 떠난 칸의 앞 탭은 그대로(옮긴 판이 앞 탭이 아니었으면)", () => {
    const r = move(TWO(), "c", { kind: "tab", col: 0, row: 0, index: 1 }, SPEC);
    expect(r).toEqual({ ok: true, layout: lay([col(480, area(["a", "c"], "c")), col(null, area(["b", "d", "e"], "b"))]), at: { col: 0, row: 0 } });
  });

  test("같은 칸 안의 순서 · 자리는 옮기는 판을 뺀 목록에서 센다 · 자리는 [0, 길이] 로 자른다", () => {
    expect(layoutOf(move(TWO(), "e", { kind: "tab", col: 1, row: 0, index: 0 }, SPEC))?.cols[1].rows[0].tabs).toEqual(["e", "b", "c", "d"]);
    expect(layoutOf(move(TWO(), "b", { kind: "tab", col: 1, row: 0, index: 3 }, SPEC))?.cols[1].rows[0].tabs).toEqual(["c", "d", "e", "b"]);
    expect(layoutOf(move(TWO(), "b", { kind: "tab", col: 1, row: 0, index: 99 }, SPEC))?.cols[1].rows[0].tabs).toEqual(["c", "d", "e", "b"]);
  });

  test("앞 탭을 옮기면 떠난 칸은 그 자리의 이웃이 앞 탭(없으면 앞의 것)", () => {
    const L = lay([col(480, area(["a"])), col(null, area(["b", "c", "d", "e"], "c"))]);
    expect(layoutOf(move(L, "c", { kind: "tab", col: 0, row: 0, index: 1 }, SPEC))?.cols[1].rows[0].active).toBe("d");
    const L2 = lay([col(480, area(["a"])), col(null, area(["b", "c", "d", "e"], "e"))]);
    expect(layoutOf(move(L2, "e", { kind: "tab", col: 0, row: 0, index: 1 }, SPEC))?.cols[1].rows[0].active).toBe("d");
  });

  test("새 열: 넣은 자리에 · 폭은 그 판의 최소 폭 · 넷째 열은 거절 ↔ 마지막 판이 떠나 열이 사라지면 셋째 자리 허용", () => {
    const r = move(TWO(), "d", { kind: "col", index: 2 }, SPEC);
    expect(r).toEqual({ ok: true, layout: lay([col(480, area(["a"])), col(null, area(["b", "c", "e"])), col(400, area(["d"]))]), at: { col: 2, row: 0 } });
    expect(move(THREE(), "c", { kind: "col", index: 3 }, SPEC)).toEqual({ ok: false, reason: "열은 셋까지입니다." });
    const L = lay([col(480, area(["a"])), col(null, area(["b", "c"])), col(480, area(["d"]))], ["e"]);
    expect(move(L, "d", { kind: "col", index: 0 }, SPEC)).toEqual({ ok: true, layout: lay([col(400, area(["d"])), col(480, area(["a"])), col(null, area(["b", "c"]))], ["e"]), at: { col: 0, row: 0 } });
  });

  test("새 열 폭(colNew): 화면이 정하면 새 열은 max(그 판의 최소 폭, colNew) ↔ 정하지 않으면 최소 폭 그대로 · 저장 꼴은 같은 규칙으로 다시 읽힌다", () => {
    const WIDE: ScreenSpec = { ...SPEC, colNew: 480 };
    // 최소 폭(400)이 colNew(480)보다 작으면 480 · 큰 판(결과 640)은 제 최소 폭
    expect(layoutOf(move(TWO(), "d", { kind: "col", index: 2 }, WIDE))?.cols[2]).toEqual(col(480, area(["d"])));
    const r = move(lay([col(480, area(["a"])), col(null, area(["b", "c"])), col(480, area(["d", "e"]))]), "b", { kind: "col", index: 0 }, WIDE);
    expect(r.ok).toBe(false);                                                      // 넷째 열 — 거절은 그대로
    expect(layoutOf(move(lay([col(480, area(["a"])), col(null, area(["c", "d", "e", "b"], "b"))]), "b", { kind: "col", index: 2 }, WIDE))?.cols[2]).toEqual(col(640, area(["b"])));
    // 짝: colNew 가 없으면 최소 폭(400) — 위 '새 열' 시험과 같은 값
    expect(layoutOf(move(TWO(), "d", { kind: "col", index: 2 }, SPEC))?.cols[2]).toEqual(col(400, area(["d"])));
    const back = readLayout(JSON.stringify(layoutOf(move(TWO(), "d", { kind: "col", index: 2 }, WIDE))), WIDE);
    expect(back.notes).toEqual([]);
  });

  test("새 칸(위 · 아래): 칸이 하나인 열만 · 새 칸 높이 0.5 · 셋째 칸 거절 · 그 칸의 판 하나를 제 열에 새 칸으로는 거절", () => {
    expect(layoutOf(move(TWO(), "d", { kind: "row", col: 1, pos: "bottom" }, SPEC))).toEqual(
      lay([col(480, area(["a"])), col(null, area(["b", "c", "e"]), area(["d"], "d", 0.5))]));
    expect(layoutOf(move(TWO(), "d", { kind: "row", col: 1, pos: "top" }, SPEC))).toEqual(
      lay([col(480, area(["a"])), col(null, area(["d"]), area(["b", "c", "e"], "b", 0.5))]));
    const top = structuredClone(SPEC.presets[2].layout);
    expect(move(top, "a", { kind: "row", col: 1, pos: "top" }, SPEC)).toEqual({ ok: false, reason: "칸은 열마다 둘까지입니다." });
    expect(move(TWO(), "a", { kind: "row", col: 0, pos: "bottom" }, SPEC)).toEqual({ ok: false, reason: "그 칸에는 이 판 하나뿐입니다." });
  });

  test("칸이 비면 접히고 남은 칸의 높이는 지운다 · 열이 비면 열이 사라지고 남는 폭 열은 마지막 열로", () => {
    const top = structuredClone(SPEC.presets[2].layout);
    expect(layoutOf(move(top, "d", { kind: "tab", col: 1, row: 1, index: 0 }, SPEC))).toEqual(
      lay([col(480, area(["a"])), col(null, area(["d", "b", "c", "e"], "d"))]));
    const L = lay([col(480, area(["a"])), col(null, area(["b"]))], ["c", "d", "e"]);
    expect(layoutOf(move(L, "b", { kind: "tab", col: 0, row: 0, index: 1 }, SPEC))).toEqual(lay([col(null, area(["a", "b"], "b"))], ["c", "d", "e"]));
  });

  test("거절: 닫힌 판 · 모르는 판 · 없는 칸 · 없는 열 자리 — 배치는 그대로", () => {
    const L = lay([col(480, area(["a"])), col(null, area(["b", "d", "e"]))], ["c"]);
    expect(move(L, "c", { kind: "tab", col: 0, row: 0, index: 0 }, SPEC)).toEqual({ ok: false, reason: "닫힌 판은 옮길 수 없습니다. 먼저 다시 여십시오." });
    expect(move(L, "zz", { kind: "tab", col: 0, row: 0, index: 0 }, SPEC)).toEqual({ ok: false, reason: "모르는 판입니다." });
    expect(move(L, "d", { kind: "tab", col: 0, row: 1, index: 0 }, SPEC)).toEqual({ ok: false, reason: "그런 칸이 없습니다." });
    expect(move(L, "d", { kind: "col", index: 7 }, SPEC)).toEqual({ ok: false, reason: "그런 칸이 없습니다." });
  });

  test("move 는 받은 배치를 바꾸지 않는다(새 객체)", () => {
    const L = TWO();
    const before = JSON.stringify(L);
    move(L, "c", { kind: "col", index: 2 }, SPEC);
    move(L, "d", { kind: "row", col: 1, pos: "bottom" }, SPEC);
    expect(JSON.stringify(L)).toBe(before);
  });
});

test("방어: 남는 폭 열이 둘인 꼴을 받아도 옮기기 · 닫기 뒤에는 정확히 하나(뒤의 것) · 앞의 것은 그 열의 최소 폭", () => {
  // readLayout 은 이런 꼴을 들이지 않는다(따로 시험) — 그래도 옮기기 · 닫기가 한 규칙을 스스로 지키는지
  const two = lay([col(null, area(["a"])), col(null, area(["b", "c", "d"])), col(480, area(["e"]))]);
  expect(layoutOf(move(two, "d", { kind: "tab", col: 0, row: 0, index: 1 }, SPEC))?.cols.map((c) => c.w)).toEqual([440, null, 480]);
  const r = close(two, "c", SPEC);
  expect(r.ok ? r.layout.cols.map((c) => c.w) : null).toEqual([440, null, 480]);
});

test.describe("닫기 · 다시 열기 · 앞 탭", () => {
  test("닫기 없는 판은 거절 ↔ 닫기 있는 판은 닫힌 판으로 · 앞 탭은 이웃", () => {
    expect(close(TWO(), "a", SPEC)).toEqual({ ok: false, reason: "닫을 수 없는 판입니다." });
    const L = lay([col(480, area(["a"])), col(null, area(["b", "c", "d", "e"], "c"))]);
    expect(close(L, "c", SPEC)).toEqual({ ok: true, layout: lay([col(480, area(["a"])), col(null, area(["b", "d", "e"], "d"))], ["c"]) });
  });

  test("다시 열기: 마지막 열의 위 칸 · 앞 탭 · 닫힌 판이 아니면 거절", () => {
    const L = lay([col(480, area(["a"])), col(null, area(["b", "d"]), area(["e"], "e", 0.4))], ["c"]);
    expect(reopen(L, "c", SPEC)).toEqual({ ok: true, layout: lay([col(480, area(["a"])), col(null, area(["b", "d", "c"], "c"), area(["e"], "e", 0.4))]), at: { col: 1, row: 0 } });
    expect(reopen(L, "d", SPEC)).toEqual({ ok: false, reason: "닫힌 판이 아닙니다." });
  });

  test("activate: 그 판이 있는 칸의 앞 탭만 바꾼다", () => {
    expect(activate(TWO(), "d").cols[1].rows[0].active).toBe("d");
    expect(activate(TWO(), "zz")).toEqual(TWO());
  });
});

test.describe("폭 · 접기 · 칸 높이", () => {
  test("fits · fold: 열 최소 폭의 합 + 구분선이 작업 폭을 넘으면 오른쪽 열을 앞 열의 위 칸 탭으로 · ★저장 꼴은 그대로★", () => {
    // 세 열의 최소 폭: 440 · 640 · 400(봉과 체결 · 하루 유형 중 큰 것) + 구분선 둘 32 = 1,512
    expect(fits(THREE(), 1512, SPEC)).toBe(true);
    expect(fits(THREE(), 1511, SPEC)).toBe(false);
    const L = THREE();
    const before = JSON.stringify(L);
    expect(fold(L, 1600, SPEC)).toEqual({ layout: THREE(), folded: 0 });
    expect(fold(L, 1500, SPEC)).toEqual({ layout: lay([col(480, area(["a"])), col(null, area(["b", "c", "d", "e"]))]), folded: 1 });
    expect(fold(L, 600, SPEC)).toEqual({ layout: lay([col(null, area(["a", "b", "c", "d", "e"]))]), folded: 2 });
    expect(JSON.stringify(L)).toBe(before);
    // 작업 폭을 모르면(재기 전) 접지 않는다
    expect(fold(L, Number.POSITIVE_INFINITY, SPEC).folded).toBe(0);
  });

  test("colWidths: 고정 폭 열은 [최소, 다른 열을 남긴 최대] 로 왼쪽부터 · 남는 폭 열은 null(1fr) · 정수", () => {
    expect(colWidths(TWO(), 1304, SPEC)).toEqual([480, null]);
    expect(colWidths(lay([col(300.4, area(["a"])), col(null, area(["b", "c", "d", "e"]))]), 1304, SPEC)).toEqual([440, null]);
    expect(colWidths(lay([col(2000, area(["a"])), col(null, area(["b", "c", "d", "e"]))]), 1304, SPEC)).toEqual([648, null]);
    // 셋: 1,400 = 구분선 32 + 1,368 · 왼쪽부터 — 첫째는 1,368 − 640 − 400 = 328 이 최대라 최소 440 · 셋째는 1,368 − 440 − 640 = 288 → 최소 400
    expect(colWidths(THREE(), 1400, SPEC)).toEqual([440, null, 400]);
    expect(colWidths(THREE(), 2000, SPEC)).toEqual([480, null, 480]);
  });

  test("colSplit: 남는 폭 열 쪽을 보는 구분선 — 왼쪽 열(start) 또는 오른쪽 열(end) · 범위는 남는 폭 열을 최소까지 줄인 폭", () => {
    const w = colWidths(THREE(), 2000, SPEC);
    expect(colSplit(THREE(), 0, w, 2000, SPEC)).toEqual({ col: 0, side: "start", min: 440, max: 2000 - 32 - 640 - 480, value: 480 });
    expect(colSplit(THREE(), 1, w, 2000, SPEC)).toEqual({ col: 2, side: "end", min: 400, max: 2000 - 32 - 480 - 640, value: 480 });
  });

  test("rowByKey: ↑ 넓힘 · ↓ 좁힘 5% · Home 0.2 · End 0.8 · 끝을 넘지 않는다 · 다른 키는 null", () => {
    expect(rowByKey("ArrowUp", 0.5)).toBe(0.55);
    expect(rowByKey("ArrowDown", 0.5)).toBe(0.45);
    expect(rowByKey("Home", 0.5)).toBe(0.2);
    expect(rowByKey("End", 0.5)).toBe(0.8);
    expect(rowByKey("ArrowUp", 0.8)).toBe(0.8);
    expect(rowByKey("ArrowDown", 0.2)).toBe(0.2);
    expect(rowByKey("Enter", 0.5)).toBeNull();
    expect(rowByKey("ArrowLeft", 0.5)).toBeNull();
  });

  test("rowByDrag: 위로 끈 만큼 아래 칸이 넓어진다 · 0.05 걸음 · [0.2, 0.8]", () => {
    expect(rowByDrag(0.5, 400, 320, 800)).toBe(0.6);
    expect(rowByDrag(0.5, 400, 430, 800)).toBe(0.45);
    expect(rowByDrag(0.5, 400, -2000, 800)).toBe(0.8);
    expect(rowByDrag(0.5, 400, 5000, 800)).toBe(0.2);
    expect(rowByDrag(0.5, 400, 300, 0)).toBe(0.5);
  });
});

test.describe("이름 · 조사", () => {
  test("areaName: 열은 서수 · 칸이 둘이면 위 · 아래", () => {
    const top = structuredClone(SPEC.presets[2].layout);
    expect(areaName(TWO(), 0, 0)).toBe("첫째 열");
    expect(areaName(top, 1, 0)).toBe("둘째 열 위 칸");
    expect(areaName(top, 1, 1)).toBe("둘째 열 아래 칸");
    expect(areaName(THREE(), 2, 0)).toBe("셋째 열");
  });

  test("조사: (으)로 — 받침 없음 · ㄹ 받침은 로 · 을/를", () => {
    expect(ro("둘째 열")).toBe("로");
    expect(ro("둘째 열 위 칸")).toBe("으로");
    expect(ro("새 열")).toBe("로");
    expect(eul("판정")).toBe("을");
    expect(eul("결과")).toBe("를");
    expect(eul("봉과 체결")).toBe("을");
  });
});

test.describe("이름 붙인 배치 · 내보내기 · 가져오기", () => {
  test("이름: 1 ~ 20자(앞뒤 빈칸 뺌) · 제어 문자 거절 ↔ 20자 · 한글 · 빈칸 안은 받는다", () => {
    expect(checkName("")).toBe("이름을 적으십시오.");
    expect(checkName("   ")).toBe("이름을 적으십시오.");
    expect(checkName("가".repeat(21))).toBe("이름은 20자까지입니다.");
    expect(checkName("관제\u0007")).toBe("이름에 쓸 수 없는 글자가 있습니다.");
    expect(checkName("가".repeat(20))).toBeNull();
    expect(checkName(" 관제 용 ")).toBeNull();
  });

  test("저장: 같은 이름은 바꾼다 · 아홉째는 거절 · 이름 바꾸기(겹치면 거절) · 지우기", () => {
    let list = [] as ReturnType<typeof readSaved>["items"];
    for (let i = 1; i <= 8; i++) {
      const r = saveNamed(list, `배치 ${i}`, TWO());
      expect(r.ok).toBe(true);
      list = r.ok ? r.items : list;
    }
    expect(saveNamed(list, "배치 9", TWO())).toEqual({ ok: false, reason: "이름 붙인 배치는 8개까지입니다. 하나를 지운 뒤 저장하십시오." });
    const same = saveNamed(list, " 배치 3 ", THREE());
    expect(same.ok && same.items.length).toBe(8);
    expect(same.ok && same.items[2]).toEqual({ name: "배치 3", layout: THREE() });
    expect(renameNamed(list, "배치 1", "배치 2")).toEqual({ ok: false, reason: "같은 이름의 배치가 있습니다." });
    const rn = renameNamed(list, "배치 1", "관제용");
    expect(rn.ok && rn.items[0].name).toBe("관제용");
    expect(removeNamed(list, "배치 4").map((x) => x.name)).toEqual(["배치 1", "배치 2", "배치 3", "배치 5", "배치 6", "배치 7", "배치 8"]);
  });

  test("readSaved: 꼴이 틀린 줄은 빼고 사유 ↔ 맞는 목록은 그대로 · 다른 화면의 목록은 버리고 사유", () => {
    const good = { v: 1, screen: "t", items: [{ name: "관제용", layout: THREE() }] };
    expect(readSaved(JSON.stringify(good), SPEC)).toEqual({ items: good.items, notes: [] });
    const bad = { v: 1, screen: "t", items: [{ name: "", layout: THREE() }, { name: "옛것", layout: { ...THREE(), v: 2 } }, { name: "관제용", layout: THREE() }] };
    const r = readSaved(JSON.stringify(bad), SPEC);
    expect(r.items).toEqual([{ name: "관제용", layout: THREE() }]);
    expect(r.notes).toEqual(["이름 붙인 배치 하나의 이름이 맞지 않아 뺐습니다.", "이름 붙인 배치 ‘옛것’을 읽지 못해 뺐습니다."]);
    expect(readSaved(JSON.stringify({ ...good, screen: "x" }), SPEC)).toEqual({ items: [], notes: ["다른 화면(‘x’)의 이름 붙인 배치라 쓰지 않았습니다."] });
    expect(readSaved(null, SPEC)).toEqual({ items: [], notes: [] });
  });

  test("내보내기 → 가져오기 왕복 = 같은 배치 · 이름은 파일이 이긴다 · 합쳐 8 넘으면 거절", () => {
    const text = exportFile(SPEC, THREE(), [{ name: "관제용", layout: TWO() }]);
    const back = importFile(text, SPEC, [{ name: "관제용", layout: THREE() }, { name: "넓게", layout: TWO() }]);
    expect(back).toEqual({ ok: true, current: THREE(), saved: [{ name: "관제용", layout: TWO() }, { name: "넓게", layout: TWO() }] });
    const many = Array.from({ length: 7 }, (_, i) => ({ name: `내 ${i}`, layout: TWO() }));
    expect(importFile(exportFile(SPEC, TWO(), [{ name: "a", layout: TWO() }, { name: "b", layout: TWO() }]), SPEC, many))
      .toEqual({ ok: false, reasons: ["합치면 이름 붙인 배치가 9개라 8개를 넘습니다."] });
  });

  test("가져오기는 엄격하다: JSON 아님 · 종류 · 다른 화면 · 모르는 판 · 64KB 넘음 · 겹친 이름 — 사유 목록 ↔ 맞는 파일은 받는다", () => {
    expect(importFile("{oops", SPEC, [])).toEqual({ ok: false, reasons: ["파일이 JSON 꼴이 아닙니다."] });
    expect(importFile(JSON.stringify({ kind: "x" }), SPEC, [])).toEqual({ ok: false, reasons: ["이 도구가 내보낸 배치 파일이 아닙니다."] });
    const other = JSON.parse(exportFile(SPEC, TWO(), [])) as Record<string, unknown>;
    expect(importFile(JSON.stringify({ ...other, screen: "my-account" }), SPEC, [])).toEqual({ ok: false, reasons: ["다른 화면(‘my-account’)의 배치 파일입니다."] });
    const unknown = { ...other, current: lay([col(480, area(["a", "zz"])), col(null, area(["b", "c", "d", "e"]))]) };
    expect(importFile(JSON.stringify(unknown), SPEC, [])).toEqual({ ok: false, reasons: ["지금 배치: 모르는 판 ‘zz’를 뺐습니다."] });
    expect(importFile("x".repeat(64 * 1024 + 1), SPEC, [])).toEqual({ ok: false, reasons: ["파일이 64KB를 넘습니다."] });
    const dup = { ...other, saved: [{ name: "a", layout: TWO() }, { name: "a", layout: THREE() }] };
    expect(importFile(JSON.stringify(dup), SPEC, [])).toEqual({ ok: false, reasons: ["파일 안에 같은 이름(‘a’)이 둘 있습니다."] });
    expect(importFile(exportFile(SPEC, TWO(), []), SPEC, [])).toEqual({ ok: true, current: TWO(), saved: [] });
  });
});

test.describe("dropAt — 끌어 놓기의 자리(결정적)", () => {
  // 두 열: 첫째 열 x 0 ~ 480 · 구분선 480 ~ 496 · 둘째 열 496 ~ 1296 · 높이 0 ~ 800 · 머리 40px · 둘째 열 탭 넷(폭 100)
  const geo: Geometry = {
    cols: [{ x: 0, y: 0, width: 480, height: 800 }, { x: 496, y: 0, width: 800, height: 800 }],
    areas: [
      { col: 0, row: 0, head: { x: 0, y: 0, width: 480, height: 40 }, body: { x: 0, y: 40, width: 480, height: 760 },
        tabs: [{ id: "a", rect: { x: 8, y: 4, width: 100, height: 32 } }] },
      { col: 1, row: 0, head: { x: 496, y: 0, width: 800, height: 40 }, body: { x: 496, y: 40, width: 800, height: 760 },
        tabs: ["b", "c", "d", "e"].map((id, i) => ({ id, rect: { x: 504 + i * 100, y: 4, width: 100, height: 32 } })) },
    ],
  };

  test("머리의 탭 사이: 가운데보다 오른쪽이면 그 뒤 자리 · 끄는 판은 세지 않는다", () => {
    expect(dropAt(geo, { x: 30, y: 20 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "tab", col: 0, row: 0, index: 0 });
    expect(dropAt(geo, { x: 90, y: 20 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "tab", col: 0, row: 0, index: 1 });
    // 둘째 열 안에서 e 를 끌어 b 와 c 사이(가운데 554 · 654): x 640 → 자리 1
    expect(dropAt(geo, { x: 640, y: 20 }, TWO(), "e", SPEC)?.target).toEqual({ kind: "tab", col: 1, row: 0, index: 1 });
  });

  test("열 가장자리 15%: 새 열(왼쪽 · 오른쪽) · 세 열이면 놓을 자리 없음(null)", () => {
    expect(dropAt(geo, { x: 1290, y: 400 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "col", index: 2 });
    expect(dropAt(geo, { x: 500, y: 400 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "col", index: 1 });
    const three = lay([col(480, area(["a"])), col(null, area(["b", "c"])), col(480, area(["e"]))], ["d"]);
    expect(dropAt(geo, { x: 1290, y: 400 }, three, "c", SPEC)).toBeNull();
  });

  test("칸 몸의 위 · 아래 25%: 새 칸 · 가운데: 그 칸 끝 탭 · 머리 · 몸 밖이면 null", () => {
    expect(dropAt(geo, { x: 900, y: 100 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "row", col: 1, pos: "top" });
    expect(dropAt(geo, { x: 900, y: 760 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "row", col: 1, pos: "bottom" });
    expect(dropAt(geo, { x: 900, y: 420 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "tab", col: 1, row: 0, index: 3 });
    // 경계(25%): 몸 40 ~ 800 의 위 25% 는 y < 230 · 아래 25% 는 y > 610 — 그 사이는 모두 그 칸 끝(새 칸 영역을 넓히거나 좁히는 변이를 거른다)
    expect(dropAt(geo, { x: 900, y: 229 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "row", col: 1, pos: "top" });
    expect(dropAt(geo, { x: 900, y: 231 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "tab", col: 1, row: 0, index: 3 });
    expect(dropAt(geo, { x: 900, y: 609 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "tab", col: 1, row: 0, index: 3 });
    expect(dropAt(geo, { x: 900, y: 611 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "row", col: 1, pos: "bottom" });
    expect(dropAt(geo, { x: 240, y: 420 }, TWO(), "d", SPEC)?.target).toEqual({ kind: "tab", col: 0, row: 0, index: 1 });
    expect(dropAt(geo, { x: 488, y: 400 }, TWO(), "d", SPEC)).toBeNull();
    expect(dropAt(geo, { x: 2000, y: 400 }, TWO(), "d", SPEC)).toBeNull();
  });

  test("놓일 자리 사각형: 머리는 2px 표시 · 새 열은 열의 1/3 · 새 칸은 몸의 절반 · 칸 끝은 몸 전체", () => {
    expect(dropAt(geo, { x: 90, y: 20 }, TWO(), "d", SPEC)?.box).toEqual({ x: 107, y: 4, width: 2, height: 32 });
    expect(dropAt(geo, { x: 1290, y: 400 }, TWO(), "d", SPEC)?.box).toEqual({ x: 496 + 800 * 2 / 3, y: 0, width: 800 / 3, height: 800 });
    expect(dropAt(geo, { x: 900, y: 760 }, TWO(), "d", SPEC)?.box).toEqual({ x: 496, y: 420, width: 800, height: 380 });
    expect(dropAt(geo, { x: 900, y: 420 }, TWO(), "d", SPEC)?.box).toEqual({ x: 496, y: 40, width: 800, height: 760 });
  });
});

test.describe("분봉 화면의 판 · 처음 배치(INTRADAY_WS)", () => {
  test("판 여섯 · 닫을 수 없는 판은 설정 · 결과 · 최소 폭 설정 440 · 결과 640(G5 잰 값)", () => {
    expect(INTRADAY_WS.screen).toBe("intraday");
    expect(INTRADAY_WS.panels.map((p) => p.id)).toEqual(["setup", "result", "bars", "verdict", "daytype", "regime"]);
    expect(INTRADAY_WS.panels.filter((p) => !p.closable).map((p) => p.id)).toEqual(["setup", "result"]);
    expect(INTRADAY_WS.panels.find((p) => p.id === "setup")?.min).toBe(440);
    expect(INTRADAY_WS.panels.find((p) => p.id === "result")?.min).toBe(640);
    // 나머지 넷은 G5 와 같은 방법으로 잰 값(2026-11-20 · 계획 §9.2a) — 자리표(400)가 남지 않았음을 건다 · 새 열 폭은 설계 값 480
    expect(Object.fromEntries(INTRADAY_WS.panels.map((p) => [p.id, p.min]))).toEqual({ setup: 440, result: 640, bars: 240, verdict: 144, daytype: 256, regime: 272 });
    expect(INTRADAY_WS.colNew).toBe(480);
  });

  test("처음 배치 셋이 모두 사유 없이 읽힌다 · 처음 켤 때는 '두 열'", () => {
    expect(INTRADAY_WS.presets.map((p) => p.name)).toEqual(["두 열", "세 열", "차트 위"]);
    for (const p of INTRADAY_WS.presets) {
      const r = readLayout(p.layout, INTRADAY_WS);
      expect(r.notes, p.name).toEqual([]);
      expect(r.layout, p.name).toEqual(p.layout);
    }
    expect(defaultLayout(INTRADAY_WS)).toEqual(INTRADAY_WS.presets[0].layout);
    expect(INTRADAY_WS.presets[0].layout.cols.map((c) => c.w)).toEqual([480, null]);
    // '차트 위'의 아래 칸 0.4(잰 값 · 2026-11-20 · 계획 §9.2a): 1920 × 1080 에서 아래 칸에 결과 머리 카드(185px)가 다 들어가는 가장 작은 5% 걸음이고
    // 2560 × 1440 에서 위 칸에 차트 틀(300px)이 다 보이는 가장 큰 걸음이다(0.5 는 1920 × 1080 위 칸에 차트 64px)
    const chart = INTRADAY_WS.presets.find((p) => p.id === "chart");
    expect(chart?.layout.cols[1].rows.map((r) => r.h ?? null)).toEqual([null, 0.4]);
  });
});
