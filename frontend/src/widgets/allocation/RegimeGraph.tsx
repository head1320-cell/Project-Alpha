"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RegimeGraph — 국면 전이 그래프 (A7-3)
// ─────────────────────────────────────────────────────────────────────────────
// ★전이행렬이 곧 그래프다★
// `MarkovRegression` 이 주는 것은 확률 네 개가 아니라 **전이확률 행렬**이다. 표로
// 찍으면 숫자 넷이지만, 노드와 방향 엣지로 그리면 "지금 어디에 있고, 어디로 갈
// 확률이 높고, 얼마나 머무는가" 가 한눈에 읽힌다.
//
// ★reactflow 를 쓰지 않는다★
// 이미 dependency 지만 `strategy-builder` 전용이고, macro 청크(112 kB)로 끌어오면
// ADR 001 의 라우트당 4 kB 를 크게 넘긴다. 노드 4개·엣지 몇 개는 손으로 그린 SVG 로
// 충분하고 비용이 0 이다 — `parts.tsx` 의 `ConfidenceGauge`·`SensitivityHeatmap` 이
// 이미 쓰는 방식이라 새로운 기법도 아니다.
//
// ★배치가 힘-기반이 아닌 이유★
// "옵시디언처럼" 이 요청한 것은 노드·엣지·호버 강조라는 **읽는 방식**이지 물리
// 엔진이 아니다. 힘 시뮬레이션을 돌리면 좌표가 매 렌더 달라지고, 그 좌표는 아무
// 뜻도 없다. 여기서는 네 국면을 **성장 축 × 물가 축의 실제 사분면**에 놓는다 —
// 위치 자체가 의미를 갖고, 렌더가 결정적이라 스크린샷·E2E 도 안정된다.
//
// ★과대주장하지 않는다★
// 모형은 **성장 2상태**(확장/수축)를 추정한다. 4×4 전이행렬이 아니다. 그래서 전이
// 엣지는 현재 물가 축 부호가 대응시키는 **두 국면 사이에만** 그리고, 나머지 둘은
// 흐리게 두고 그 사실을 캡션에 적는다. 4개를 다 잇는 그림이 더 그럴듯해 보이지만
// 그 세 배의 엣지는 모형이 한 적 없는 말이다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import { REGIME_COLORS, type MarkovDetail, type Regime } from "@/entities/macro/api";

/** 사분면 좌표 — 가로 = 성장, 세로 = 물가(위가 상승). viewBox 기준. */
const POS: Record<Regime, { x: number; y: number }> = {
  Stagflation:  { x: 88,  y: 68 },   // 성장 ↓ · 물가 ↑
  Reflation:    { x: 262, y: 68 },   // 성장 ↑ · 물가 ↑
  Disinflation: { x: 88,  y: 184 },  // 성장 ↓ · 물가 ↓
  Goldilocks:   { x: 262, y: 184 },  // 성장 ↑ · 물가 ↓
};

const KO: Record<Regime, string> = {
  Goldilocks: "골디락스", Reflation: "리플레이션",
  Stagflation: "스태그플레이션", Disinflation: "디스인플레이션",
};

const R_MIN = 17;
const R_MAX = 40;
const VB_W = 350;
const VB_H = 252;

/** 노드 반지름 — 확률이 그대로 크기다. 확률이 없으면 최소 크기(추정하지 않았다는 뜻). */
function radius(p: number | undefined): number {
  if (p == null || !Number.isFinite(p)) return R_MIN;
  return R_MIN + (R_MAX - R_MIN) * Math.max(0, Math.min(1, p));
}

/** A → B 곡선. 두 방향이 겹치지 않도록 수직 방향으로 살짝 띄운다. */
function arc(a: { x: number; y: number }, b: { x: number; y: number }, ra: number, rb: number, bow: number) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  // 노드 원 바깥에서 시작하고 끝난다(화살촉이 원에 가려지지 않게 여유 4px).
  const sx = a.x + ux * (ra + 3), sy = a.y + uy * (ra + 3);
  const ex = b.x - ux * (rb + 7), ey = b.y - uy * (rb + 7);
  // 수직 단위벡터로 활 모양을 준다.
  const mx = (sx + ex) / 2 - uy * bow, my = (sy + ey) / 2 + ux * bow;
  return `M ${sx} ${sy} Q ${mx} ${my} ${ex} ${ey}`;
}

/** 자기루프 — 국면 지속성. 노드 바깥쪽(중앙 반대편)으로 원호를 건다. */
function loop(p: { x: number; y: number }, r: number) {
  const outX = p.x < VB_W / 2 ? -1 : 1;
  const outY = p.y < VB_H / 2 ? -1 : 1;
  const s = 0.7071;
  const sx = p.x + outX * r * s, sy = p.y - outY * r * s;
  const ex = p.x + outX * r * s, ey = p.y + outY * r * s;
  const cx = p.x + outX * (r + 26);
  return `M ${sx} ${sy} C ${cx} ${sy - outY * 12} ${cx} ${ey + outY * 12} ${ex} ${ey}`;
}

export interface RegimeGraphProps {
  /** 노드 크기의 출처가 되는 확률(축-확률 우선). 없으면 모든 노드가 최소 크기다. */
  probs?: Record<string, number>;
  /** 확률의 출처 이름 — 화면에 적는다. 어느 모형이 크기를 정했는지 숨기지 않는다. */
  probsSource: string;
  markov: MarkovDetail;
  regimes: Regime[];
}

export function RegimeGraph({ probs, probsSource, markov, regimes }: RegimeGraphProps) {
  const [hot, setHot] = useState<Regime | null>(null);

  // 2상태 → 4국면 대응: 물가 축 부호가 위/아래 절반을 고른다.
  const up = markov.inflation_up;
  const expansion: Regime = up ? "Reflation" : "Goldilocks";
  const contraction: Regime = up ? "Stagflation" : "Disinflation";
  const active = new Set<Regime>([expansion, contraction]);

  // ★행렬을 직접 인덱싱하지 않는다★ statsmodels 의 `regime_transition` 은 **열이
  // 출발**(`P[j][i] = i→j`)이라 `tm[a][b]` 는 b→a 다. 엔진 주석이 한때 반대로 적혀
  // 있었고 그대로 읽어 화살표를 뒤집어 그렸다 — 대각은 어느 규약이든 같은 값이라
  // 화면으로는 티가 나지 않았다. 서버가 이름을 붙여 주는 값만 쓴다.
  const e = markov.expansion_state;
  const tm = markov.transition;
  const pEE = markov.persistence ?? 0;                        // 확장 유지
  const pEC = markov.p_exp_to_con ?? 0;                       // 확장 → 수축
  const pCC = tm?.[1 - e]?.[1 - e] ?? 0;                      // 수축 유지 (대각 — 방향 무관)
  const pCE = markov.p_con_to_exp ?? 0;                       // 수축 → 확장

  const w = (p: number) => 1.2 + 6 * Math.max(0, Math.min(1, p));
  const dim = (r: Regime) => (hot != null && hot !== r ? 0.25 : 1);
  const edgeOn = (from: Regime, to: Regime) =>
    hot == null || hot === from || hot === to ? 1 : 0.15;

  const edges: { from: Regime; to: Regime; p: number; d: string; label: string }[] = [];
  const rEx = radius(probs?.[expansion]);
  const rCo = radius(probs?.[contraction]);
  edges.push({
    from: expansion, to: contraction, p: pEC, label: "확장 → 수축",
    d: arc(POS[expansion], POS[contraction], rEx, rCo, 26),
  });
  edges.push({
    from: contraction, to: expansion, p: pCE, label: "수축 → 확장",
    d: arc(POS[contraction], POS[expansion], rCo, rEx, 26),
  });

  return (
    <div className="as-rgg">
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="as-rgg-svg" role="img"
        aria-label={`국면 전이 그래프 — ${KO[expansion]} 유지 ${(pEE * 100).toFixed(0)}%, ${KO[contraction]} 유지 ${(pCC * 100).toFixed(0)}%`}>
        <defs>
          <marker id="as-rgg-ah" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--t-accent)" />
          </marker>
        </defs>

        {/* 축 안내선 — 사분면 배치가 임의가 아니라는 것을 보여 준다. */}
        <line x1={VB_W / 2} y1="26" x2={VB_W / 2} y2={VB_H - 26}
          stroke="var(--border)" strokeDasharray="3 4" />
        <line x1="26" y1={VB_H / 2 - 6} x2={VB_W - 26} y2={VB_H / 2 - 6}
          stroke="var(--border)" strokeDasharray="3 4" />
        <text x={VB_W - 26} y={VB_H / 2 - 12} textAnchor="end" fontSize="11"
          fill="var(--t-muted)">성장 →</text>
        <text x={VB_W / 2 + 6} y="24" fontSize="11" fill="var(--t-muted)">↑ 물가</text>

        {/* 자기루프 = 지속성. 전이 엣지보다 먼저 그려 노드 뒤로 보낸다. */}
        {([[expansion, pEE, rEx], [contraction, pCC, rCo]] as const).map(([reg, p, r]) => (
          <path key={`loop-${reg}`} d={loop(POS[reg], r)} fill="none"
            stroke="var(--t-accent)" strokeWidth={w(p)} strokeLinecap="round"
            opacity={0.55 * edgeOn(reg, reg)} markerEnd="url(#as-rgg-ah)" />
        ))}

        {edges.map((ed) => (
          <path key={`${ed.from}-${ed.to}`} d={ed.d} fill="none"
            stroke="var(--t-accent)" strokeWidth={w(ed.p)} strokeLinecap="round"
            opacity={0.7 * edgeOn(ed.from, ed.to)} markerEnd="url(#as-rgg-ah)">
            <title>{`${ed.label} ${(ed.p * 100).toFixed(0)}%`}</title>
          </path>
        ))}

        {regimes.map((reg) => {
          const p = POS[reg];
          if (!p) return null;
          const r = radius(probs?.[reg]);
          const col = REGIME_COLORS[reg];
          const on = active.has(reg);
          const pv = probs?.[reg];
          return (
            <g key={reg} className={`as-rgg-node${on ? " on" : ""}`} tabIndex={0}
              role="button"
              aria-label={`${KO[reg]} ${pv != null ? `${(pv * 100).toFixed(0)}%` : "확률 미산출"}${on ? "" : " — 현재 물가 부호에서 상태전환 모형이 다루지 않음"}`}
              onMouseEnter={() => setHot(reg)} onMouseLeave={() => setHot(null)}
              onFocus={() => setHot(reg)} onBlur={() => setHot(null)}
              opacity={on ? dim(reg) : 0.4 * dim(reg)}>
              <circle cx={p.x} cy={p.y} r={r} fill={col.bg} stroke={col.border}
                strokeWidth={hot === reg ? 2.5 : 1.5} />
              <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize="12"
                fill={col.fg} className="num">
                {pv != null ? `${(pv * 100).toFixed(0)}%` : "—"}
              </text>
              <text x={p.x} y={p.y + r + 15} textAnchor="middle" fontSize="11"
                fill="var(--t-ink)">{KO[reg]}</text>
            </g>
          );
        })}
      </svg>

      {/* ★그래프가 무엇을 말하고 무엇을 말하지 않는지★ — 접지 않는다. */}
      <p className="as-rgg-cap">
        노드 크기는 <b>{probsSource}</b> 의 현재 확률, 엣지 굵기는 <b>상태전환 확률</b>,
        자기루프는 <b>지속성</b>입니다. 모형이 추정한 것은 <b>성장 2상태(확장/수축)</b>이며,
        현재 물가 축이 {up ? "상승" : "하락"} 부호라 {KO[expansion]}·{KO[contraction]} 두 국면에
        대응됩니다 — <b>4×4 전이행렬이 아닙니다</b>. 나머지 두 국면은 이 모형이 다루지 않아
        흐리게 표시했습니다.
      </p>
      <div className="as-rgg-legend num">
        <span>{KO[expansion]} 유지 {(pEE * 100).toFixed(0)}%</span>
        <span>→ {KO[contraction]} {(pEC * 100).toFixed(0)}%</span>
        <span>{KO[contraction]} 유지 {(pCC * 100).toFixed(0)}%</span>
        <span>→ {KO[expansion]} {(pCE * 100).toFixed(0)}%</span>
        <span>관측 {markov.n_obs}개월</span>
      </div>
    </div>
  );
}
