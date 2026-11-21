/**
 * 스파크라인 — 하나 (2026-11-10 · 설계 `2026-11-10-chart-indicator-system-design.md` §3 D)
 * ==========================================================================
 * 예전에는 다섯 곳이 제각각 그렸다(굵기 1 · 1.4 · 1.5 · 1.6 · 1.6 — 하나는 그림이 늘어나 선 굵기가 변했고, 하나는 값이 하나면 0 으로 나눴다).
 * 이제 한 부품이 그린다: 선 1.5px · 둥근 이음(`.sp-line`) · ★끝 점 하나 = 지금★(`.sp-end`) · 유한한 값만(모르는 기간은 건너뛴다) ·
 * 값이 둘 미만이면 아무것도 그리지 않는다(선을 지어내지 않는다 — 빈 자리는 부르는 쪽이 정한다).
 * 색·클래스·방향 표시는 부르는 쪽이 넘긴다 — 자리마다 색 규칙(등락색 · 한 색)과 E2E 가 보는 클래스(`mc-spark` · `ca-spark` …)가 다르다.
 * 지키는 시험: `e2e/figures.spec.ts`.
 */
import { sparkPoints } from "./plotGeo";

export function Spark({ values, w, h, stroke, className, dir }: {
  values: ReadonlyArray<number | null | undefined>; w: number; h: number; stroke: string; className?: string;
  /** `data-dir`(오름·내림·그대로) — 방향을 색만으로 말하지 않게 남기는 자리. */
  dir?: string;
}) {
  const pts = sparkPoints(values, w, h);
  if (!pts) return null;
  const last = pts[pts.length - 1];
  return (
    <svg className={className} width={w} height={h} viewBox={`0 0 ${w} ${h}`} data-dir={dir} aria-hidden="true">
      <polyline className="sp-line" points={pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")} fill="none" stroke={stroke} />
      <circle className="sp-end" cx={last.x.toFixed(1)} cy={last.y.toFixed(1)} r={2.5} fill={stroke} />
    </svg>
  );
}
