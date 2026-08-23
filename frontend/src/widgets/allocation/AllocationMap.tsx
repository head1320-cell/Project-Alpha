"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AllocationMap + 팔레트 — **recharts 를 쓰지 않는 유일한 배분 시각화** (P3 분리)
// ─────────────────────────────────────────────────────────────────────────────
// parts.tsx 안에 있었는데, 그 파일이 recharts 를 import 하는 탓에 이 순수 div
// 스트립 하나를 쓰려면 차트 라이브러리가 통째로 딸려왔다 — 실측으로 `/dev/ui` 가
// 131 kB → 254 kB. A6 이 `TIP_STYLE` 을 같은 이유로 꺼낸 선례를 따른다.
// parts.tsx 는 기존 소비자를 위해 re-export 한다 — import 경로는 바뀌지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";

/**
 * 범주 팔레트 — 하드코딩 hex 에서 토큰으로 (A3 S3f).
 * 예전 배열에는 `#16a34a` 가 들어 있었는데, S1b-2 에서 그 값이 zinc-50 위 3.16:1 로
 * 측정돼 `--chart-up` 에서 이미 퇴출된 색이다. 같은 값이 팔레트에는 그대로 남아 있었다.
 * §51 이 `--cat-1..10` 을 라이트/다크 양쪽으로 정의한다.
 */
const DONUT_COLORS = Array.from({ length: 10 }, (_, i) => `var(--cat-${i + 1})`);

export const paletteColor = (i: number): string => DONUT_COLORS[i % DONUT_COLORS.length];

/**
 * 비중 비례 스트립 + 범례.
 *
 * ★막대 안의 흰 글씨를 뺐다★ 예전에는 각 블록 위에 `color:#fff` 로 종목명과 비중을
 * 얹었다. 팔레트 10색 중 어떤 색 위에 얹힐지는 자산 개수와 순서에 따라 달라지므로,
 * 대비가 보장되는 조합이 하나도 없었다(밝은 색 위 흰 글씨). 게다가 블록이 좁아지면
 * 글자가 잘려서 어차피 안 읽힌다. 텍스트는 아래 범례로 내리고 스트립은 비율만 그린다 —
 * 색은 범례에서 이름과 짝지어지므로 "색만으로 의미를 전달"하지도 않는다.
 */
export function AllocationMap({ items }: { items: { code: string; name: string; weight: number }[] }) {
  const tot = items.reduce((a, x) => a + Math.max(x.weight, 0), 0) || 1;
  const shown = items.filter((x) => x.weight > 0);
  // ★숏을 조용히 버리지 않는다 (P3)★ 예전에는 `filter(w > 0)` 하나뿐이라 숏이
  // 스트립에서도 범례에서도 사라졌다 — 화면에 없으니 없는 것처럼 보였다.
  // 스트립은 비율 그림이라 음수를 같은 줄에 넣을 수 없다. 그래서 **두 번째 줄**로
  // 그리고, 두 줄의 스케일을 gross 로 공유해 길이를 서로 비교할 수 있게 한다.
  const shorts = items.filter((x) => x.weight < 0);
  const gross = tot + shorts.reduce((a, x) => a + Math.abs(x.weight), 0);
  if (!shown.length && !shorts.length) return <div className="as-empty">비중이 있는 자산이 없습니다.</div>;
  const scale = shorts.length ? gross : tot;
  return (
    <div className="aas-mapwrap">
      <div className="aas-map">
        {shown.map((x, i) => (
          <div key={x.code} className="aas-map-b" title={`${x.name} ${x.weight.toFixed(1)}%`}
            style={{ flex: `${(x.weight / scale) * 100} 0 0`, background: paletteColor(i) }} />
        ))}
      </div>
      {shorts.length > 0 && (
        <>
          <div className="as-ls-legrow">
            <span className="as-ls-legtag short">숏</span>
            <span className="as-ls-legnote">
              아래 막대는 숏 다리입니다 — 위 롱 다리와 같은 gross 스케일이라 길이를 그대로 비교할 수 있습니다.
            </span>
          </div>
          <div className="aas-map as-ls-map-short">
            {shorts.map((x, i) => (
              <div key={x.code} className="aas-map-b" title={`${x.name} ${x.weight.toFixed(1)}%`}
                style={{ flex: `${(Math.abs(x.weight) / scale) * 100} 0 0`,
                         background: paletteColor(shown.length + i) }} />
            ))}
          </div>
        </>
      )}
      <ul className="aas-legend">
        {[...shown, ...shorts].map((x, i) => (
          <li key={x.code} className="aas-legend-i">
            <span className="aas-legend-sw" style={{ background: paletteColor(i) }} aria-hidden="true" />
            <span className="aas-legend-nm">{x.name}</span>
            <b className={`num${x.weight < 0 ? " as-ls-neg" : ""}`}>{x.weight.toFixed(1)}%</b>
          </li>
        ))}
      </ul>
    </div>
  );
}
