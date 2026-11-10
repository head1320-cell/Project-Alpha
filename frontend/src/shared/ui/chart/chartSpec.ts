/**
 * 차트 표식 규격 — 한 곳 (2026-11-10 · ADR 004 §6 · 설계 `2026-11-10-chart-indicator-system-design.md` §3 A)
 * ==========================================================================
 * recharts 차트(`*.charts.tsx`)와 손그림(`widgets/portfolio-graph/MiniPlots.tsx`)이 같은 값을 쓴다 — 화면마다 굵기·점·격자가 달라 보이지 않게.
 *   · 선 2px. 뒤로 물리는 선은 1.5px + 흐림(굵기로 강조하지 않는다).
 *   · 점 r4 + 표면색 고리 2px — 선과 겹치는 자리에서도 읽힌다.
 *   · 면은 계열 색 10% 단색(그라데이션 아님).
 *   · 격자는 실선 1px. 점선은 뜻이 있는 주석선(평균 · 손익분기 · 내재가치)에만 쓴다.
 *   · 막대는 24px 이하 · 자료 끝만 4px 둥글림(바닥은 각지게).
 *   · 축 글자 12px.
 * ★이 파일은 차트 라이브러리를 import 하지 않는다★(경계 규칙 — `eslint.config.js` 의 `no-restricted-imports`).
 * 지키는 시험: `e2e/chart-marks.spec.ts`.
 */
export const MARK = { line: 2, quiet: 1.5, quietOpacity: 0.65, dotR: 4, ring: 2, wash: 0.1, barMax: 24, barR: 4 } as const;

/** 축 눈금 글자(recharts `tick`). */
export const AXIS_TICK = { fontSize: 12, fill: "var(--tx-sub)" } as const;

/** 가로 격자(recharts `<CartesianGrid {...GRID} />`) — 실선. */
export const GRID = { stroke: "var(--tx-line)", vertical: false } as const;

/** 계열의 점 — 계열 색 + 표면색 고리. */
export const ringDot = (color: string) => ({ r: MARK.dotR, fill: color, stroke: "var(--tx-surface)", strokeWidth: MARK.ring });

/** 읽는 줄이 고른 자리 — 세로선. */
export const CROSSHAIR = { stroke: "var(--tx-mute)", strokeWidth: 1 } as const;

/** 읽는 줄이 고른 자리의 점 — 속이 빈 고리(계열의 찬 점과 구별된다). */
export const pickDot = (color: string) => ({ r: MARK.dotR, fill: "var(--tx-surface)", stroke: color, strokeWidth: MARK.ring });

/** 막대의 둥근 끝 — recharts `radius` [왼위, 오른위, 오른아래, 왼아래]. 자료 끝(위)만 둥글다. */
export const BAR_TOP: [number, number, number, number] = [MARK.barR, MARK.barR, 0, 0];
