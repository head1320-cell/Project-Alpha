/**
 * 고리(도넛)의 조각들 — 직접 SVG (2026-11-10 · ADR 004 §2.3 ㈐)
 * ==========================================================================
 * 캔버스 전략 합치기 카드의 몫 도넛(`widgets/portfolio-graph/StrategyDonut.tsx`)이 그리던 고리를 그대로 옮겨, 매크로의 보유 도넛
 * (`widgets/macro/cockpitParts.tsx::HoldingsDonut` — 예전엔 recharts Pie)과 같이 쓴다. 한 조각 = `circle` 하나의 `stroke-dasharray`.
 * svg · 가운데 글자 · 범례 · 접근 이름은 부르는 쪽이 만든다(자리마다 다르다) — 여기는 조각 묶음만 낸다.
 *
 * ★분모는 `total`★ — 조각 길이 = value / total. 조각의 합이 total 보다 모자라면 그만큼 고리가 비어 보인다(채우지 않는다).
 * 캔버스는 100(모르는 몫이 있으면 비어 보이게), 매크로는 값의 합(비중 합이 100 이 아니어도 한 바퀴 — 예전 Pie 와 같은 비율).
 */
export interface RingSlice {
  key: string; value: number; color: string;
  /** 조각에 붙일 `data-*`(E2E·읽기용). 예: `{ port: "a", share: 61.2 }` → `data-port` · `data-share`. */
  data?: Record<string, string | number>;
}

export function DonutRing({ slices, total, box = 88, r = 34, width = 12, gap = 1.5, trackClass, arcClass }: {
  slices: RingSlice[]; total: number;
  /** 정사각 viewBox 한 변(가운데 = box / 2). */
  box?: number; r?: number; width?: number;
  /** 조각 사이 틈(viewBox 단위). */
  gap?: number; trackClass?: string;
  /** 조각의 class — 주면 스타일 골든이 조각을 이름으로 본다(없으면 class 없는 circle · 캔버스 도넛의 예전 DOM). */
  arcClass?: string;
}) {
  const c = box / 2, round = 2 * Math.PI * r;
  const arcs: { s: RingSlice; len: number; off: number }[] = [];
  let acc = 0, used = 0;
  for (const s of total > 0 ? slices : []) {
    const v = Math.min(s.value, Math.max(0, total - used));      // 반올림으로 total 을 넘으면 고리 끝에서 멈춘다
    used += v;
    const len = (v / total) * round;
    arcs.push({ s, len, off: acc });
    acc += len;
  }
  return (
    <>
      <circle cx={c} cy={c} r={r} fill="none" className={trackClass} strokeWidth={width} />
      {arcs.map(({ s, len, off }) => (
        <circle key={s.key} className={arcClass} cx={c} cy={c} r={r} fill="none" stroke={s.color} strokeWidth={width}
                strokeDasharray={`${Math.max(0, len - gap)} ${round}`} strokeDashoffset={-off} transform={`rotate(-90 ${c} ${c})`}
                {...Object.fromEntries(Object.entries(s.data ?? {}).map(([k, v]) => [`data-${k}`, v]))} />
      ))}
    </>
  );
}
