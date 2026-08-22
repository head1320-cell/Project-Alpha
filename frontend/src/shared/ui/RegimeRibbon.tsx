"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RegimeRibbon — 월별 국면 색띠 (A8, 시간 맥락)
// ─────────────────────────────────────────────────────────────────────────────
// 확률만 보면 "지금 골디락스" 는 알아도 **그게 흔한 일인지 드문 일인지**를 모른다.
// 한 줄짜리 색띠는 세로 공간을 거의 쓰지 않으면서 순환·지속성·희소성을 한눈에 준다.
//
// ★기간을 주장하지 않는다★
// 이 저장소의 매크로 시계열은 실측 60개월이고, YoY 변환과 불완전한 달을 빼면 실제로
// 분류되는 것은 그보다 적다. 그래서 리본은 **서버가 준 span 을 그대로 적는다** —
// `관측 53개월 (2022-04 ~ 2026-08)`. "최근 10년" 같은 문구는 데이터가 그만큼일 때만
// 참이고, 여기서는 참이 아니다. 실키(FRED/ECOS)를 넣으면 자동으로 길어진다.
//
// ★`CycleStripGrid` 의 패턴은 따르되 결함 둘은 따라가지 않는다★
// (`widgets/macro/visualParts.tsx:24` — 손으로 그린 flex 셀, 번들 비용 0)
//   · 그쪽은 `#dc2626`/`#2563eb` 를 박아 라이트 전용이다 → 여기서는 토큰만 쓴다(A4-X2).
//   · 그쪽은 `title=` 이 유일한 설명이다 → 호버는 키보드·터치에 존재하지 않는다(P3).
//     여기서는 보이는 요약과 `aria-label` 을 함께 둔다.
//
// FSD: `widgets/allocation` 은 같은 계층의 `widgets/macro` 를 import 할 수 없다
// (`.eslintrc.js` peer 금지). 그래서 shared/ui 에 둔다 — `CatalogueShell`·
// `ArchiveDrawer` 가 같은 이유로 여기 있다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";

export interface RibbonPoint {
  t: string;
  regime: string;
}

export interface RibbonSpan {
  first: string | null;
  last: string | null;
  n_months: number;
  requested: number;
  truncated: boolean;
  dropped_incomplete: number;
}

const KO: Record<string, string> = {
  Goldilocks: "골디락스", Reflation: "리플레이션",
  Stagflation: "스태그플레이션", Disinflation: "디스인플레이션",
};

/** 국면 → 토큰. `REGIME_COLORS` 와 같은 팔레트를 쓰되 shared 는 entities 를 못 보므로
 *  토큰 이름을 직접 참조한다(값이 아니라 이름이라 라이트/다크가 알아서 따라온다). */
const FILL: Record<string, string> = {
  Goldilocks: "var(--rg-gold-bd)", Reflation: "var(--rg-refl-bd)",
  Stagflation: "var(--rg-stag-bd)", Disinflation: "var(--rg-disi-bd)",
};

export interface RegimeRibbonProps {
  points: RibbonPoint[];
  span: RibbonSpan;
  /** 현재 국면이 몇 달째인지 — 지속성의 가장 직관적인 표현. */
  runLength?: number;
  /** 국면별 역사 점유율 — 지금이 흔한지 드문지. */
  occupancy?: Record<string, number>;
}

export function RegimeRibbon({ points, span, runLength, occupancy }: RegimeRibbonProps) {
  if (!points.length) {
    return (
      <div className="as-rgr as-rgr-empty">
        분류 가능한 달이 없어 리본을 그릴 수 없습니다
        {span.dropped_incomplete > 0 && ` (축이 불완전한 달 ${span.dropped_incomplete}개월 제외)`}
      </div>
    );
  }

  const current = points[points.length - 1].regime;
  const share = occupancy?.[current];

  return (
    <div className="as-rgr">
      <div className="as-rgr-band" role="img"
        aria-label={`국면 이력 ${span.n_months}개월, ${span.first} 부터 ${span.last} 까지. 현재 ${KO[current] ?? current}.`}>
        {points.map((p, i) => (
          <i key={`${p.t}-${i}`} className="as-rgr-cell"
            style={{ background: FILL[p.regime] ?? "var(--t-border)" }}
            title={`${p.t} · ${KO[p.regime] ?? p.regime}`} />
        ))}
      </div>

      {/* 눈금 — 처음·중간·끝. 셀마다 라벨을 달면 읽을 수 없다. */}
      <div className="as-rgr-axis num">
        <span>{points[0].t}</span>
        <span>{points[Math.floor(points.length / 2)].t}</span>
        <span>{points[points.length - 1].t}</span>
      </div>

      {/* ★구간을 적는다 — 이것이 이 컴포넌트의 정직성 장치다★ */}
      <div className="as-rgr-meta">
        <span className="as-rgr-span num">
          관측 {span.n_months}개월 ({span.first} ~ {span.last})
        </span>
        {runLength != null && (
          <span className="as-rgr-run">
            현재 <b>{KO[current] ?? current}</b> · 연속 <b className="num">{runLength}</b>개월
          </span>
        )}
        {share != null && (
          <span className="as-rgr-share num">역사 점유율 {(share * 100).toFixed(0)}%</span>
        )}
        {span.truncated && (
          <span className="as-rgr-trunc">
            요청 {span.requested}개월 중 {span.n_months}개월만 분류 가능
            {span.dropped_incomplete > 0 && ` (축 불완전 ${span.dropped_incomplete}개월 제외)`}
          </span>
        )}
      </div>

      {/* 범례 — 색만으로 의미를 전달하지 않는다. */}
      <div className="as-rgr-legend">
        {Object.keys(FILL).map((r) => (
          <span key={r} className="as-rgr-lg">
            <i style={{ background: FILL[r] }} aria-hidden="true" />
            {KO[r] ?? r}
            {occupancy?.[r] != null && <b className="num">{(occupancy[r] * 100).toFixed(0)}%</b>}
          </span>
        ))}
      </div>
    </div>
  );
}
