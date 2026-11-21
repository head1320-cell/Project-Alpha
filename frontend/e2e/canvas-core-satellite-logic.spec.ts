import { test, expect } from "./fixtures";
import { coreOf, gradeOf, pctOf, signedOf } from "../src/widgets/portfolio-graph/coreSatelliteFormat";

/**
 * 매매 몫 결합(K4) 결과 판의 서식 — 순수 규칙(브라우저 없이)
 *  · 서버의 퍼센트 값(×100)을 ★그대로★ 서식한다 — 100 으로 나눴다 곱하는 왕복은 27.45 를 27.449999… 로 만들어 27.4% 로 보였다
 *    (E2E 에서 찾은 결함 · 서버가 넷째 자리로 싣게 된 뒤로는 E2E 자료로 갈리지 않아 여기서 건다)
 *  · 부호: 보이는 자릿수로 0 이면 붙이지 않는다(+0.00% · −0.00% 를 만들지 않는다) · 모르면 N/A(0 이 아니다)
 *  · 등급 문구: E0 · E3 만 그대로, 그 밖은 미상 · 핵심의 모의 시세 여부(참 · 거짓 · 미상)
 */

test("퍼센트는 서버 값 그대로 반올림한다 — 27.45 는 27.5% (짝: 왕복했다면 27.4%) · 음수는 빼기 기호 · 모르면 N/A", () => {
  expect(pctOf(27.45, 1)).toBe("27.5%");
  expect(((27.45 / 100) * 100).toLocaleString("ko-KR", { maximumFractionDigits: 1, minimumFractionDigits: 1 })).toBe("27.4");   // 왕복의 결과(전제)
  expect(pctOf(24.6512, 2)).toBe("24.65%");
  expect(pctOf(1234.5, 1)).toBe("1,234.5%");
  expect(pctOf(-1.234, 2)).toBe("−1.23%");
  expect(pctOf(-0.004, 2)).toBe("0.00%");
  for (const bad of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, "1", {}]) expect(pctOf(bad, 1)).toBe("N/A");
});

test("부호를 붙인 퍼센트 — 양수 + · 음수 − · 보이는 자릿수로 0 이면 부호 없음 · 모르면 N/A", () => {
  expect(signedOf(1.5, 2)).toBe("+1.50%");
  expect(signedOf(-1.5, 2)).toBe("−1.50%");
  expect(signedOf(0.004, 2)).toBe("0.00%");
  expect(signedOf(-0.004, 2)).toBe("0.00%");
  expect(signedOf(0, 2)).toBe("0.00%");
  expect(signedOf(0.005, 2)).toBe("+0.01%");
  expect(signedOf(null, 2)).toBe("N/A");
});

test("등급 문구 — E0 · E3 만 그대로 · 그 밖은 미상 · 핵심은 모의 시세 / 실제 시세 / 미상", () => {
  expect(gradeOf("E0")).toBe("E0");
  expect(gradeOf("E3")).toBe("E3");
  for (const other of [null, undefined, "E9", "e0", 3]) expect(gradeOf(other)).toBe("미상");
  expect(coreOf(true)).toBe("모의 시세");
  expect(coreOf(false)).toBe("실제 시세");
  for (const other of [null, undefined, "true", 1]) expect(coreOf(other)).toBe("미상");
});
