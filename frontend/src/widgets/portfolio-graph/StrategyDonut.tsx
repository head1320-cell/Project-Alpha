"use client";
/**
 * 몫 도넛 (BN N1 · 전략 합치기 노드 카드) — 조각 = 서버 `view.strategies[].share_pct`(전략 합치기 노드 결과) 그대로.
 * ★모르는 몫은 조각을 만들지 않는다★ — 목록에 "—" 로만 적는다(0 조각·균등 조각으로 채우지 않는다). 색 = 그 전략의 띠 색.
 * 조각 길이는 **100 에 대한 몫**이다(아는 조각끼리 다시 나누지 않는다) — 모르는 몫이 있으면 그만큼 고리가 비어 보인다.
 */
export interface DonutSlice { port: string; label: string; share: number | null; color: string }

const R = 34;
const C = 2 * Math.PI * R;

export function StrategyDonut({ slices, size = 88 }: { slices: DonutSlice[]; size?: number }) {
  const known = slices.filter((x): x is DonutSlice & { share: number } => x.share !== null && x.share > 0);
  let acc = 0;
  let used = 0;
  return (
    <div className="pg-donut" data-slices={known.length}>
      <svg width={size} height={size} viewBox="0 0 88 88" role="img"
           aria-label={`전략 몫 — ${slices.map((x) => `${x.label} ${x.share === null ? "모름" : `${x.share.toFixed(1)}%`}`).join(", ")}`}>
        <circle cx="44" cy="44" r={R} fill="none" className="pg-donut-track" strokeWidth="12" />
        {known.map((x) => {
          const pct = Math.min(x.share, Math.max(0, 100 - used));     // 반올림으로 100 을 넘으면 고리 끝에서 멈춘다
          used += pct;
          const len = (pct / 100) * C;
          const el = (
            <circle key={x.port} cx="44" cy="44" r={R} fill="none" stroke={x.color} strokeWidth="12"
                    strokeDasharray={`${Math.max(0, len - 1.5)} ${C}`} strokeDashoffset={-acc} transform="rotate(-90 44 44)"
                    data-port={x.port} data-share={x.share} />
          );
          acc += len;
          return el;
        })}
        <text x="44" y="42" textAnchor="middle" className="pg-donut-n">{slices.length}</text>
        <text x="44" y="56" textAnchor="middle" className="pg-donut-sub">전략</text>
      </svg>
      <ul className="pg-donut-legend">
        {slices.map((x) => (
          <li key={x.port} data-port={x.port}>
            <i style={{ background: x.color }} /><span>{x.label}</span><b>{x.share === null ? "—" : `${x.share.toFixed(1)}%`}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}
