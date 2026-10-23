/** 포트 타입 → 선·포트 점 색. 모르는 타입은 회색, 카탈로그에 없는 포트는 빨간 점선(GraphNode).
 *  색은 테마 토큰(`--pg-port-*`, globals.css) — 라이트·다크 바탕 각각에서 3:1 이상(BQ Q3, E2E 가 잰다). */
export const PORT_TYPES = [
  "Universe", "Returns", "Belief", "Views", "Weights", "RiskReport", "BacktestResult",
  // BK — 레포 도구 노드의 값
  "Scenario", "StressReport", "Scores", "RegimeState", "TimingSignal", "Trades", "TargetVersion", "StrategyResult", "BacktestRun",
] as const;
export const PORT_COLORS: Record<string, string> = Object.fromEntries(PORT_TYPES.map((t) => [t, `var(--pg-port-${t})`]));
export const PORT_UNKNOWN_COLOR = "var(--pg-port-unknown)";
export const portColor = (t: string | undefined): string => (t && PORT_COLORS[t]) || PORT_UNKNOWN_COLOR;
