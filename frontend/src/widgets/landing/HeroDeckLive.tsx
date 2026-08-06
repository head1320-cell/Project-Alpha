"use client";
// 대상 경로: frontend/src/components/landing/HeroDeckLive.tsx
//
// 히어로 백테스터 프리뷰 덱(원래 page.tsx 의 HeroDeck) — 클라이언트 아일랜드.
//   · 자산곡선/벤치마크 라인이 그려지고(stroke draw-in, CSS)
//   · 월별 히트맵 셀이 스태거 팝(CSS, 인라인 delay)
//   · 통계(CAGR/Sharpe/Sortino·성과)가 카운트업(CountUp)
//   · 3D 덱이 커서 쪽으로 미세 틸트(pointer:fine·non-reduced 만)
// 마크업은 SSR 동일 → 하이드레이션 미스매치 없음. reduced-motion 폴백은 globals.css.

// ═══════════════════════════════════════════════════════════════════════════════
// ★이 덱의 수치는 전부 하드코딩된 예시다 — 실적이 아니다★
// eqY/bcY 곡선, +24.6%, Sharpe 2.14, MAX DD -9.1%, 312 트레이드… 전부 이 파일 안의
// 리터럴이다. 어떤 백테스트도 실행하지 않는다.
//
// 그런데 예전에는 이것이 초록 점이 깜빡이는 **LIVE 배지** 아래 있었다. 퀀트 플랫폼의
// 첫 화면에서 지어낸 성과를 LIVE 라고 적는 것은, 이 프로젝트가 제품 안에서 내내 지켜 온
// 규칙("완료된 결과를 지어내지 않는다")을 입구에서 정면으로 깨는 일이다. 방문자는 그것을
// 이 플랫폼의 트랙 레코드로 읽을 수 있다.
//
// 그래서 배지를 `예시 수치` 로 바꾸고, 덱 아래에 무엇인지 한 줄로 적는다.
// 시각적 역할(백테스터 UI 가 어떻게 생겼는지 보여 주기)은 그대로 하되, 성과를 주장하지
// 않는다. 실제 수치를 보여 주고 싶다면 런을 하나 실행해 그 run_id 를 읽어야 한다.
// ═══════════════════════════════════════════════════════════════════════════════

import { useEffect, useRef } from "react";
import CountUp from "./CountUp";

// Catmull-Rom → cubic bezier 스무딩 (자산곡선 곡선화)
function smooth(pts: [number, number][]): string {
  if (pts.length < 2) return "";
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

export default function HeroDeckLive() {
  const deckRef = useRef<HTMLDivElement | null>(null);

  // 포인터 틸트 — 데스크톱(pointer:fine) + 모션 허용일 때만. 모바일/터치/reduced 는 CSS 정적 틸트 유지.
  useEffect(() => {
    const el = deckRef.current;
    if (!el || typeof window === "undefined") return;
    const fine = window.matchMedia?.("(pointer: fine)").matches;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!fine || reduce) return;
    const zone = el.parentElement ?? el; // .lp-hero-visual 위에서 추적
    let raf = 0, tx = 0, ty = 0, cx = 0, cy = 0;
    const apply = () => {
      cx += (tx - cx) * 0.09; cy += (ty - cy) * 0.09;
      el.style.transform = `perspective(2100px) rotateY(${(-8 + cx * 6).toFixed(2)}deg) rotateX(${(2.5 - cy * 5).toFixed(2)}deg)`;
      if (Math.abs(tx - cx) > 0.001 || Math.abs(ty - cy) > 0.001) raf = requestAnimationFrame(apply);
      else raf = 0;
    };
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      tx = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / (r.width / 2)));
      ty = Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / (r.height / 2)));
      if (!raf) raf = requestAnimationFrame(apply);
    };
    const onLeave = () => { tx = 0; ty = 0; if (!raf) raf = requestAnimationFrame(apply); };
    zone.addEventListener("pointermove", onMove);
    zone.addEventListener("pointerleave", onLeave);
    return () => {
      zone.removeEventListener("pointermove", onMove);
      zone.removeEventListener("pointerleave", onLeave);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  const N = 22;
  const x = (i: number) => 10 + i * (460 / (N - 1));
  const eqY = [124, 118, 121, 110, 113, 103, 108, 95, 90, 96, 83, 88, 75, 69, 74, 61, 55, 60, 47, 39, 43, 32];
  const bcY = [126, 124, 125, 121, 122, 118, 120, 114, 112, 116, 110, 113, 108, 105, 108, 101, 98, 101, 94, 90, 93, 87];
  const eqPts: [number, number][] = eqY.map((y, i) => [x(i), y]);
  const bcPts: [number, number][] = bcY.map((y, i) => [x(i), y]);
  const eqLine = smooth(eqPts);
  const eqArea = `${eqLine} L ${x(N - 1).toFixed(1)},150 L ${x(0).toFixed(1)},150 Z`;
  const stats: Array<[string, string]> = [
    ["MAX DD", "−9.1%"], ["WIN RATE", "61.4%"], ["PROFIT FACTOR", "2.43"],
    ["CALMAR", "2.70"], ["VOLATILITY", "11.2%"], ["TRADES", "312"],
  ];
  const months = [3.2, 1.1, -2.4, 4.6, 0.8, 2.1, -1.3, 5.2, 1.9, -0.6, 3.4, 2.7, 1.5, -3.1, 4.0, 2.2, 0.5, 3.8];

  return (
    <>
    <div className="lp-deck" ref={deckRef}>
      <div className="lp-deck-top">
        <span className="lp-deck-dots"><i /><i /><i /></span>
        <span className="lp-deck-title">BACKTESTER // MULTI-FACTOR VALUE</span>
        <span className="lp-deck-sample">예시 수치</span>
      </div>
      <div className="lp-deck-body">
        <div className="lp-deck-headrow">
          <div className="lp-deck-stat">
            <span className="lp-deck-k">CAGR · 2019—2024</span>
            <span className="lp-deck-v"><CountUp value="+24.6" /><em>%</em></span>
          </div>
          <div className="lp-deck-pills">
            <span className="lp-deck-pill"><b>SHARPE</b><CountUp value="2.14" /></span>
            <span className="lp-deck-pill"><b>SORTINO</b><CountUp value="3.01" /></span>
          </div>
        </div>
        <svg className="lp-deck-chart" viewBox="0 0 480 150" preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id="lp-eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#1200ff" stopOpacity="0.16" /><stop offset="1" stopColor="#1200ff" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[30, 66, 102, 138].map((y, i) => <line key={i} x1="0" y1={y} x2="480" y2={y} stroke="#eef0f4" strokeWidth="1" />)}
          <path className="lp-deck-area" d={eqArea} fill="url(#lp-eq)" />
          <path className="lp-deck-bc" d={smooth(bcPts)} fill="none" stroke="#c7c8d0" strokeWidth="1.3" strokeDasharray="4 3" pathLength={1} />
          <path className="lp-deck-eq" d={eqLine} fill="none" stroke="#1200ff" strokeWidth="2" pathLength={1} />
          <circle className="lp-deck-end" cx={x(N - 1)} cy={eqY[N - 1]} r="6.5" fill="#1200ff" opacity="0.16" />
          <circle className="lp-deck-end" cx={x(N - 1)} cy={eqY[N - 1]} r="3.4" fill="#1200ff" />
        </svg>
        <div className="lp-deck-grid">
          <div className="lp-deck-card">
            <div className="lp-deck-card-h">PERFORMANCE</div>
            <div className="lp-deck-stats">
              {stats.map(([k, v]) => (
                <div key={k} className="lp-deck-srow"><span>{k}</span><b><CountUp value={v} /></b></div>
              ))}
            </div>
          </div>
          <div className="lp-deck-card">
            <div className="lp-deck-card-h">MONTHLY P/L · 18M</div>
            <div className="lp-deck-heat">
              {months.map((m, i) => {
                const o = Math.min(0.6, 0.12 + (Math.abs(m) / 8) * 0.58);
                return <span key={i} className="lp-deck-cell"
                  style={{ background: m >= 0 ? `rgba(22,163,74,${o.toFixed(3)})` : `rgba(220,38,38,${o.toFixed(3)})`, animationDelay: `${(0.55 + i * 0.022).toFixed(3)}s` }} />;
              })}
            </div>
            <div className="lp-deck-heat-x"><span>LOSS</span><span>FLAT</span><span>GAIN</span></div>
          </div>
        </div>
      </div>
    </div>
    <p className="lp-deck-note">
      백테스터 화면이 어떻게 생겼는지 보여 주는 <b>예시</b>입니다. 위에 있는 숫자는 코드에
      그냥 박아 둔 값이라, 실제로 돌린 백테스트가 아닙니다. 진짜 결과를 보려면 런을 하나
      실행해야 하고, 그러면 <code>run_id</code> 와 데이터 범위가 같이 붙습니다.
    </p>
    </>
  );
}
