import { test, expect } from "./fixtures";
import { clampSplit, splitByDrag, splitByKey } from "../src/shared/ui/split/split";
import { BAR_W, DEFAULT_SPLIT, OUT_MIN, SET_DEFAULT, SET_MIN, SET_STEP, paneMax, paneWidth, readSplit } from "../src/widgets/intraday/splitPane";

/**
 * 분할 창의 순수 규칙(브라우저 없이) — 계획 문서 §6.2
 *  · 구분선 하나가 키 · 끌기로 폭을 정한다. 폭은 ★정수 px★ 이고 [최소, 최대] 안이다(최대가 최소보다 작으면 최소).
 *  · side = start: 구분선 앞(왼쪽) 칸의 폭 — → 가 넓힌다 · side = end: 구분선 뒤(오른쪽) 칸의 폭 — ← 가 넓힌다(캔버스 오른쪽 판). Home 은 최소 · End 는 최대.
 *  · 분봉 화면은 ★선호 폭★을 저장하고 그릴 때마다 지금 작업 칸 폭으로 clamp 한다 — 창을 줄였다 늘리면 선호가 돌아온다.
 *  · 저장 꼴이 틀리면 기본값으로 그린다(지어내지 않고 · 실패하지 않고).
 */

test("clamp: 범위 안은 반올림만 · 밖은 경계 · 최대가 최소보다 작으면 최소 · 수가 아니면 최소", () => {
  expect(clampSplit(480.4, 440, 648)).toBe(480);
  expect(clampSplit(480.5, 440, 648)).toBe(481);
  expect(clampSplit(100, 440, 648)).toBe(440);
  expect(clampSplit(9999, 440, 648)).toBe(648);
  expect(clampSplit(500, 440, 300)).toBe(440);   // 작업 칸이 좁아 최대 < 최소
  expect(clampSplit(Number.NaN, 440, 648)).toBe(440);
  expect(clampSplit(Number.POSITIVE_INFINITY, 440, 648)).toBe(440);
  // 짝: 캔버스의 옛 clampW(Math.round(Math.min(600, Math.max(300, w)))) 와 범위 안팎에서 같다
  for (const w of [-50, 0, 299.5, 300, 301.49, 450.5, 599.6, 600, 1e6]) expect(clampSplit(w, 300, 600)).toBe(Math.round(Math.min(600, Math.max(300, w))));
});

test("키: start 는 → 가 넓히고 ← 가 좁힌다 · end 는 거꾸로 · Home 최소 · End 최대 · 다른 키는 null · 결과는 clamp", () => {
  const start = { min: 440, max: 648, step: 16, side: "start" as const };
  const end = { min: 300, max: 600, step: 16, side: "end" as const };
  expect(splitByKey("ArrowRight", 480, start)).toBe(496);
  expect(splitByKey("ArrowLeft", 480, start)).toBe(464);
  expect(splitByKey("ArrowLeft", 392, end)).toBe(408);
  expect(splitByKey("ArrowRight", 392, end)).toBe(376);
  expect(splitByKey("Home", 480, start)).toBe(440);
  expect(splitByKey("End", 480, start)).toBe(648);
  expect(splitByKey("Home", 392, end)).toBe(300);
  expect(splitByKey("End", 392, end)).toBe(600);
  expect(splitByKey("ArrowRight", 640, start)).toBe(648);   // 끝을 넘지 않는다
  expect(splitByKey("ArrowLeft", 444, start)).toBe(440);
  for (const k of ["Enter", " ", "ArrowUp", "ArrowDown", "PageUp", "a", "Tab"]) expect(splitByKey(k, 480, start)).toBeNull();
});

test("끌기: start 는 오른쪽으로 끈 만큼 넓어지고 end 는 왼쪽으로 끈 만큼 넓어진다 · 결과는 clamp", () => {
  expect(splitByDrag(480, 700, 800, "start", 440, 648)).toBe(580);
  expect(splitByDrag(480, 700, 650, "start", 440, 648)).toBe(440);
  expect(splitByDrag(480, 700, 1000, "start", 440, 648)).toBe(648);
  expect(splitByDrag(392, 900, 800, "end", 300, 600)).toBe(492);
  expect(splitByDrag(392, 900, 1000, "end", 300, 600)).toBe(300);
  expect(splitByDrag(480, 700, 700.6, "start", 440, 648)).toBe(481);
});

test("분봉 화면의 폭: 최소 440 · 기본 480 · 최대 = 작업 칸 − 구분선 16 − 오른쪽 최소 640 · 선호는 그대로 두고 그릴 때 clamp", () => {
  expect([SET_MIN, SET_DEFAULT, BAR_W, OUT_MIN, SET_STEP]).toEqual([440, 480, 16, 640, 16]);
  expect(DEFAULT_SPLIT).toEqual({ w: 480, open: true });
  expect(paneMax(1304)).toBe(648);
  expect(paneWidth(480, 1304)).toBe(480);
  expect(paneWidth(1200, 1304)).toBe(648);      // 1440 화면: 선호 1200 → 그릴 때 648
  expect(paneWidth(1200, 1784)).toBe(1128);     // 1920 화면으로 돌아오면 선호가 다시 맞는다
  expect(paneWidth(300, 1784)).toBe(440);
  expect(paneWidth(480, 900)).toBe(440);        // 작업 칸이 좁아 최대 < 최소 → 최소
});

test("저장 꼴 읽기: 맞는 꼴은 그 값 · 틀린 꼴 · 빈 값 · 수가 아닌 폭은 기본 · 접힘은 true/false 만", () => {
  expect(readSplit(JSON.stringify({ w: 612, open: false }))).toEqual({ w: 612, open: false });
  expect(readSplit(JSON.stringify({ w: 512, open: true }))).toEqual({ w: 512, open: true });
  expect(readSplit(null)).toEqual(DEFAULT_SPLIT);
  expect(readSplit("")).toEqual(DEFAULT_SPLIT);
  expect(readSplit("{oops")).toEqual(DEFAULT_SPLIT);
  expect(readSplit("[]")).toEqual(DEFAULT_SPLIT);
  expect(readSplit("null")).toEqual(DEFAULT_SPLIT);
  expect(readSplit(JSON.stringify({ w: "612", open: false }))).toEqual({ w: 480, open: false });
  expect(readSplit(JSON.stringify({ w: -5, open: false }))).toEqual({ w: 480, open: false });
  expect(readSplit(JSON.stringify({ w: 612, open: "no" }))).toEqual({ w: 612, open: true });
  expect(readSplit(JSON.stringify({ w: 612 }))).toEqual({ w: 612, open: true });
});
