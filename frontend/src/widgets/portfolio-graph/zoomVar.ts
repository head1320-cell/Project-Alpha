/**
 * 확대 값 `--pg-z` 를 쓰는 곳 (CF 3부 R8 — 재서 찾음).
 * 예전에는 ZoomWatch 가 캔버스(`.pg-canvas`)에 `--pg-z` 를 쓰고 모든 요소가 물려받았다 — 그래서 휠 한 칸마다 캔버스 아래 ★모든 요소★의
 * 스타일을 다시 계산했다(200노드 확대 20칸 = 스타일 계산 약 5초 · 이 환경 기준). 이제 `--pg-z` 는 물려받지 않는 값으로 등록하고(globals.css
 * `@property`), 캔버스 자신(E2E 가 읽는 계약)과 ★아래 목록의 요소에만★ 같은 값을 놓는다 — 보이는 크기는 예전과 같다.
 * ★globals.css 에서 `var(--pg-z` 를 새로 쓰면 그 요소를 이 목록에 더한다★ — 빠지면 그 요소는 늘 1(확대와 무관한 크기)이 된다.
 * `e2e/canvas-perf.spec.ts` 가 globals.css 의 모든 `var(--pg-z` 규칙이 이 목록에 드는지 잰다.
 * 순수 — 시험이 직접 부른다.
 */
export const PG_Z_USERS = [
  ".pg-node-far-name", ".pg-node-far-v",                          // 먼 보기 카드 이름·숫자
  ".pg-ghost-name",                                               // 먼 보기 유령 이름
  ".pg-lane-head",                                                // 단계 띠 머리
  ".pg-waypoint",                                                 // 꺾는 점(화면 크기 고정)
  ".pg-wire-flag",                                                // 먼 보기 선 점검 점
  ".pg-branch-name",                                              // 먼 보기 갈래 이름
  ".pg-group-label", ".pg-group-share", ".pg-group-share b",     // 먼 보기 전략 상자 이름·몫
] as const;

/** 캔버스 안 쓰는 곳에 확대 값을 놓는 규칙 한 줄. 캔버스는 한 화면에 하나다(`/allocation` 만 그린다). */
export function pgZRule(z: number): string {
  return `.pg-canvas :is(${PG_Z_USERS.join(", ")}) { --pg-z: ${z}; }`;
}
