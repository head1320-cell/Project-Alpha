import { test, expect } from "./fixtures";
import {
  ariaSort, clampPage, nextSort, pageCount, pageNumbers, pageSlice, restoreSort, rowByKey, sortNumber, sortRows, toCsv, type SortState,
} from "../src/shared/ui/table/table";

/**
 * 공용 표의 순수 규칙(브라우저 없이) — U1-a · ADR 007 §5 · 계획 `docs/superpowers/plans/2026-11-21-uiux-u1-table-screener.md`
 *  · 정렬: ★값이 없는 줄은 어느 방향에서도 끝★(미상은 가장 작은 값이 아니다) · 같은 값은 들어온 순서 그대로 · 원본을 바꾸지 않는다
 *  · 정렬 표시: 정렬 중인 열만 방향을 말한다 · 정렬할 수 없는 열에는 속성이 없다
 *  · 쪽: 늘 한 쪽 이상 · 쪽 번호는 범위 안으로 · 쪽 단추는 첫 쪽 · 끝 쪽 · 지금 쪽 둘레와 그 사이의 줄임
 *  · 줄 초점: ↑ ↓ Home End PageUp PageDown 만 다룬다(다른 키는 null — 기본 동작을 막지 않는다)
 *  · 내보내기: 값 없음은 빈칸(0 이 아니다) · 쉼표 · 따옴표 · 줄바꿈은 따옴표로 · 식으로 읽힐 글자는 글로 못 박는다
 */

type Row = { code: string; v: number | null | undefined | string };
const R = (code: string, v: Row["v"]): Row => ({ code, v });
const codes = (rows: Row[]) => rows.map((r) => r.code).join(" ");

test("정렬: 내림 · 오름 — ★값이 없는 줄은 어느 방향에서도 끝★(짝: 두 방향의 순서는 서로 다르다)", () => {
  const rows = [R("a", 3), R("n1", null), R("b", 10), R("n2", undefined), R("c", -2), R("n3", Number.NaN), R("d", 0), R("n4", "7"), R("n5", Number.POSITIVE_INFINITY)];
  const get = (r: Row) => r.v;
  expect(codes(sortRows(rows, get, "desc"))).toBe("b a d c n1 n2 n3 n4 n5");
  expect(codes(sortRows(rows, get, "asc"))).toBe("c d a b n1 n2 n3 n4 n5");
  expect(codes(sortRows(rows, get, "asc")), "0 은 값이다 — 값 없는 줄과 섞이지 않는다").toMatch(/^c d a b /);
  expect(codes(rows), "원본을 바꾸지 않는다").toBe("a n1 b n2 c n3 d n4 n5");
});

test("정렬: 같은 값은 들어온 순서 그대로(안정) · 빈 표 · 한 줄", () => {
  const rows = [R("x", 5), R("y", 5), R("z", 5), R("w", 9)];
  expect(codes(sortRows(rows, (r) => r.v, "desc"))).toBe("w x y z");
  expect(codes(sortRows(rows, (r) => r.v, "asc"))).toBe("x y z w");
  expect(sortRows([] as Row[], (r) => r.v, "desc")).toEqual([]);
  expect(codes(sortRows([R("only", null)], (r) => r.v, "asc"))).toBe("only");
});

test("정렬에 쓰는 수: 유한한 수만 값이다 — 글자 · 빈 값 · NaN · 무한대는 미상(null)", () => {
  expect([0, -1.5, 42].map(sortNumber)).toEqual([0, -1.5, 42]);
  expect([null, undefined, Number.NaN, Number.NEGATIVE_INFINITY, "3", "", {}, true].map(sortNumber)).toEqual([null, null, null, null, null, null, null, null]);
});

test("머리를 누르면: 같은 열은 방향을 뒤집고 다른 열은 그 열의 내림차순부터", () => {
  const s: SortState = { col: "score", dir: "desc" };
  expect(nextSort(s, "score")).toEqual({ col: "score", dir: "asc" });
  expect(nextSort({ col: "score", dir: "asc" }, "score")).toEqual({ col: "score", dir: "desc" });
  expect(nextSort({ col: "score", dir: "asc" }, "price")).toEqual({ col: "price", dir: "desc" });
});

test("정렬 표시: 정렬 중인 열만 방향 · 정렬할 수 있는 다른 열은 none · 정렬할 수 없는 열은 속성 없음", () => {
  const s: SortState = { col: "price", dir: "asc" };
  expect(ariaSort(true, "price", s)).toBe("ascending");
  expect(ariaSort(true, "price", { col: "price", dir: "desc" })).toBe("descending");
  expect(ariaSort(true, "score", s)).toBe("none");
  expect(ariaSort(false, "price", s), "정렬할 수 없는 열은 정렬 중인 이름과 같아도 속성이 없다").toBeUndefined();
  expect(ariaSort(true, "price", null)).toBe("none");
});

test("쪽: 늘 한 쪽 이상 · 번호는 범위 안으로 · 자르기", () => {
  expect([0, 1, 100, 101, 250].map((n) => pageCount(n, 100))).toEqual([1, 1, 1, 2, 3]);
  expect([-1, 0, 1, 2, 9, Number.NaN].map((p) => clampPage(p, 130, 100))).toEqual([0, 0, 1, 1, 1, 0]);
  const rows = Array.from({ length: 130 }, (_, i) => i);
  expect(pageSlice(rows, 0, 100)).toHaveLength(100);
  expect(pageSlice(rows, 1, 100)).toEqual(rows.slice(100));
  expect(pageSlice(rows, 5, 100), "범위 밖의 쪽은 끝 쪽").toEqual(rows.slice(100));
  expect(pageSlice([] as number[], 0, 100)).toEqual([]);
});

test("쪽 단추: 첫 쪽 · 끝 쪽 · 지금 쪽 둘레 둘씩 · 그 사이는 줄임 하나(null)", () => {
  expect(pageNumbers(1, 0)).toEqual([0]);
  expect(pageNumbers(3, 1)).toEqual([0, 1, 2]);
  expect(pageNumbers(10, 5)).toEqual([0, null, 3, 4, 5, 6, 7, null, 9]);
  expect(pageNumbers(10, 0)).toEqual([0, 1, 2, null, 9]);
  expect(pageNumbers(10, 9)).toEqual([0, null, 7, 8, 9]);
  expect(pageNumbers(30, 0).filter((x) => x === null), "줄임은 이어 붙지 않는다").toHaveLength(1);
});

test("줄 초점: ↑ ↓ Home End PageUp PageDown — 끝에서 멈춘다 · 다른 키는 null(짝)", () => {
  expect(rowByKey("ArrowDown", 0, 5)).toBe(1);
  expect(rowByKey("ArrowDown", 4, 5), "끝에서 멈춘다(돌아가지 않는다)").toBe(4);
  expect(rowByKey("ArrowUp", 0, 5)).toBe(0);
  expect(rowByKey("ArrowUp", 3, 5)).toBe(2);
  expect(rowByKey("Home", 3, 5)).toBe(0);
  expect(rowByKey("End", 1, 5)).toBe(4);
  expect(rowByKey("PageDown", 2, 50, 10)).toBe(12);
  expect(rowByKey("PageDown", 45, 50, 10)).toBe(49);
  expect(rowByKey("PageUp", 12, 50, 10)).toBe(2);
  expect(rowByKey("PageUp", 3, 50, 10)).toBe(0);
  for (const k of ["Enter", " ", "Tab", "ArrowLeft", "ArrowRight", "a", "Escape"]) expect(rowByKey(k, 2, 5), k).toBeNull();
  expect(rowByKey("ArrowDown", 0, 0), "줄이 없으면 갈 곳이 없다").toBeNull();
});

test("내보내기: 값 없음은 빈칸(★0 이 아니다★ — 짝: 수 0 은 0) · 쉼표 · 따옴표 · 줄바꿈은 따옴표로 · BOM 과 CRLF", () => {
  const csv = toCsv(["순위", "종목명", "현재가"], [[1, "가, 나", 0], [2, 'A "B"', null], [3, "줄\n바꿈", undefined], [4, "보통", 12.5]]);
  expect(csv.charCodeAt(0)).toBe(0xfeff);
  expect(csv.slice(1).split("\r\n")).toEqual(["순위,종목명,현재가", '1,"가, 나",0', '2,"A ""B""",', '3,"줄\n바꿈",', "4,보통,12.5"]);
  expect(toCsv(["a"], []).slice(1), "줄이 없어도 머리 줄은 있다").toBe("a");
});

test("내보내기: 식으로 읽힐 글자(= + - @ 로 시작하는 글)는 글로 못 박는다 ↔ 음수인 수는 그대로(짝)", () => {
  const lines = toCsv(["글", "수"], [["=1+1", -3.2], ["+합", 5], ["-빼기", -0], ["@name", 1], ["보통 = 글", 2]]).slice(1).split("\r\n");
  expect(lines.slice(1)).toEqual(["'=1+1,-3.2", "'+합,5", "'-빼기,0", "'@name,1", "보통 = 글,2"]);
});

test("저장한 정렬 되살리기: 꼴이 맞고 지금 정렬할 수 있는 열만 ↔ 모르는 열 · 없는 열 · 틀린 방향 · 꼴이 아닌 값은 기본(짝)", () => {
  const cols = ["current_price", "composite_score", "per"] as const;
  const def: SortState = { col: "composite_score", dir: "desc" };
  expect(restoreSort({ col: "current_price", dir: "asc" }, cols, def)).toEqual({ col: "current_price", dir: "asc" });
  expect(restoreSort({ col: "per", dir: "desc" }, cols, def)).toEqual({ col: "per", dir: "desc" });
  expect(restoreSort({ col: "roe", dir: "asc" }, cols, def), "지금 표에 없는 열").toEqual(def);
  expect(restoreSort({ col: "current_price", dir: "up" }, cols, def), "모르는 방향").toEqual(def);
  expect(restoreSort({ col: "current_price" }, cols, def), "방향이 없다").toEqual(def);
  expect(restoreSort({ col: 3, dir: "asc" }, cols, def)).toEqual(def);
  for (const raw of [null, undefined, "current_price", 1, true, [], ["current_price", "asc"]]) expect(restoreSort(raw, cols, def), JSON.stringify(raw) ?? "undefined").toEqual(def);
  const got = restoreSort({ col: "current_price", dir: "asc", extra: 1 }, cols, def);
  expect(got, "더 붙은 값은 버린다(되살린 값은 열과 방향 둘뿐)").toEqual({ col: "current_price", dir: "asc" });
  expect(restoreSort({ col: "per", dir: "asc" }, [], def), "정렬할 열이 아직 없으면(결과 전) 기본").toEqual(def);
});
