"use client";
/**
 * 몫 도넛 (BN N1 · 전략 합치기 노드 카드) — 조각 = 서버 `view.strategies[].share_pct`(전략 합치기 노드 결과) 그대로.
 * ★모르는 몫은 조각을 만들지 않는다★ — 목록에 "—" 로만 적는다(0 조각·균등 조각으로 채우지 않는다). 색 = 그 전략의 띠 색.
 * 조각 길이는 **100 에 대한 몫**이다(아는 조각끼리 다시 나누지 않는다) — 모르는 몫이 있으면 그만큼 고리가 비어 보인다.
 * 고리 자체는 공용 `shared/ui/Donut.tsx::DonutRing`(매크로 보유 도넛과 같이 쓴다 · ADR 004) — 분모 100 · DOM 은 예전 그대로.
 */
import { DonutRing } from "@/shared/ui/Donut";

export interface DonutSlice { port: string; label: string; share: number | null; color: string }

export function StrategyDonut({ slices, size = 88 }: { slices: DonutSlice[]; size?: number }) {
  const known = slices.filter((x): x is DonutSlice & { share: number } => x.share !== null && x.share > 0);
  return (
    <div className="pg-donut" data-slices={known.length}>
      <svg width={size} height={size} viewBox="0 0 88 88" role="img"
           aria-label={`전략 배분 비중 — ${slices.map((x) => `${x.label} ${x.share === null ? "모름" : `${x.share.toFixed(1)}%`}`).join(", ")}`}>
        <DonutRing total={100} trackClass="pg-donut-track"
          slices={known.map((x) => ({ key: x.port, value: x.share, color: x.color, data: { port: x.port, share: x.share } }))} />
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
