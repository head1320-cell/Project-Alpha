/**
 * Landing — 루트(/) 첫 화면. Variant "Institutional Terminal" 랜딩 (레퍼런스 3종 합성):
 *   ① 다크 티커 마퀴 ② 미니멀 헤더(브랜드 + 앵커 내비) ③ 분할 히어로
 *   ④ INTEGRATED TOOLSET — 5모듈 컬럼(설명 + mono 메트릭 + 미니 비주얼)
 *   ⑤ 플랫폼 지표 스트립(실제 수치) ⑥ 푸터(미니 티커 + ©)
 * 셸(TerminalShell)은 "/"에서 렌더하지 않음 — 풀블리드. CTA → /dashboard.
 * 데이터·마크업 전부 정적(서버 컴포넌트) — 백엔드 미기동에도 완전 동작.
 */

import Link from "next/link";

const MODULES = [
  {
    n: "01", code: "SCREENER", title: "Screener", href: "/screener",
    desc: "전 주권 ~2,700종목을 290+ 팩터로 멀티팩터 필터링. 자연어 검색(nl2ast)과 실시간 라이브 카운트.",
    metrics: [["FACTORS", "290+"], ["UNIVERSE", "~2,700"], ["LIQUIDITY GATE", "3-LAYER"]],
    visual: "bars",
  },
  {
    n: "02", code: "BACKTEST", title: "Backtester", href: "/backtest",
    desc: "룰 기반 조건식 엔진 — 팩터 함수 19종, 논리식(every·any·before), 체결가 13종, 시그널 벡터화.",
    metrics: [["FILL MODELS", "13"], ["VECTORIZED", "142×"], ["SIGNAL BASIS", "T-1 / T"]],
    visual: "line",
  },
  {
    n: "03", code: "MACRO", title: "Macro Analysis", href: "/macro",
    desc: "4-국면 매크로 레짐 + 금리·환율 실데이터(ECOS·FRED). 마켓타이밍 게이트로 백테스터와 직결.",
    metrics: [["SOURCES", "ECOS·FRED"], ["REGIME", "4-QUADRANT"]],
    visual: "heat",
  },
  {
    n: "04", code: "COMPANY", title: "Company Analysis", href: "/insights",
    desc: "DART 재무 PIT(공시시차 반영) 기반 심층 분석. RIM·DCF·DDM 내재가치와 점수 분해.",
    metrics: [["FINANCIALS", "DART PIT"], ["VALUATION", "RIM·DCF·DDM"]],
    visual: "rows",
  },
  {
    n: "05", code: "RISK", title: "Risk Analysis", href: "/risk-tools",
    desc: "시나리오 스트레스 테스트와 생존율 분석. 취약 종목 식별로 꼬리위험을 사전에 점검.",
    metrics: [["SCENARIOS", "10+"], ["STRESS TEST", "LIVE"]],
    visual: "gauge",
  },
];

// 플랫폼 실측 지표 — 과장 없이 코드베이스에서 나온 수치
const PLATFORM_STATS: Array<[string, string, string]> = [
  ["SUPPORTED FACTORS", "290+", "카탈로그 344 중 220 + 자체 73"],
  ["FILL PRICE MODELS", "13", "종가·시가·전일가·피벗·TWAP"],
  ["CONDITION FUNCTIONS", "19", "+ 논리식 and·or·not·every·any·before"],
  ["SIGNAL ENGINE", "142×", "전 봉 사전계산 벡터화 실측"],
  ["TEST SUITE", "470", "passed — 등가성·회귀 고정"],
  ["DATA SOURCES", "5", "KRX·DART·KIS·ECOS·FRED (무료)"],
];

// ─── 모듈 카드 미니 비주얼 (refs의 sparkline/heatmap/gauge 재현, 순수 SVG) ───
function Visual({ kind }: { kind: string }) {
  if (kind === "bars") {
    const hs = [9, 14, 7, 18, 12, 22, 16, 27, 20, 31];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36">
        {hs.map((h, i) => (
          <rect key={i} x={i * 12 + 2} y={36 - h} width="7" height={h}
            fill={i === hs.length - 1 ? "var(--bs-primary)" : "#d4d4d8"} />
        ))}
      </svg>
    );
  }
  if (kind === "line") {
    return (
      <svg className="lp-visual" viewBox="0 0 120 36">
        <polyline points="2,30 22,26 42,29 62,18 82,21 102,10 118,13"
          fill="none" stroke="var(--bs-primary)" strokeWidth="1.6" />
        <polyline points="2,32 22,31 42,32 62,28 82,29 102,24 118,26"
          fill="none" stroke="#d4d4d8" strokeWidth="1.2" />
      </svg>
    );
  }
  if (kind === "heat") {
    const cells = [0.35, 0.7, 1, 0.25, 0.5, 0.2, 1, 0.45, 0.3, 0.6, 0.15, 0.4];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36">
        {cells.map((o, i) => (
          <rect key={i} x={(i % 4) * 30 + 1} y={Math.floor(i / 4) * 12 + 1}
            width="27" height="10" fill="var(--bs-primary)" opacity={0.12 + o * 0.55} />
        ))}
      </svg>
    );
  }
  if (kind === "rows") {
    return (
      <svg className="lp-visual" viewBox="0 0 120 36">
        {[6, 16, 26].map((y, i) => (
          <g key={i}>
            <rect x="2" y={y} width={86 - i * 18} height="3.5" fill="#e4e4e7" />
            <rect x="2" y={y} width={40 - i * 8} height="3.5" fill="var(--bs-primary)" opacity="0.65" />
          </g>
        ))}
      </svg>
    );
  }
  // gauge
  return (
    <svg className="lp-visual" viewBox="0 0 120 36">
      <circle cx="60" cy="18" r="13" fill="none" stroke="#e4e4e7" strokeWidth="2.5" />
      <path d="M 60 5 A 13 13 0 0 1 72.3 22" fill="none" stroke="var(--bs-primary)" strokeWidth="2.5" />
    </svg>
  );
}

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

// ─── 히어로 비주얼 — 퀀트 백테스터 제품 프리뷰 (자체 SVG/HTML · 외부 의존 0) ───
function HeroDeck() {
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
    <div className="lp-deck">
      <div className="lp-deck-top">
        <span className="lp-deck-dots"><i /><i /><i /></span>
        <span className="lp-deck-title">BACKTESTER // MULTI-FACTOR VALUE</span>
        <span className="lp-deck-live"><i />LIVE</span>
      </div>
      <div className="lp-deck-body">
        <div className="lp-deck-headrow">
          <div className="lp-deck-stat">
            <span className="lp-deck-k">CAGR · 2019—2024</span>
            <span className="lp-deck-v">+24.6<em>%</em></span>
          </div>
          <div className="lp-deck-pills">
            <span className="lp-deck-pill"><b>SHARPE</b>2.14</span>
            <span className="lp-deck-pill"><b>SORTINO</b>3.01</span>
          </div>
        </div>
        <svg className="lp-deck-chart" viewBox="0 0 480 150" preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id="lp-eq" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#1200ff" stopOpacity="0.16" /><stop offset="1" stopColor="#1200ff" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[30, 66, 102, 138].map((y, i) => <line key={i} x1="0" y1={y} x2="480" y2={y} stroke="#eef0f4" strokeWidth="1" />)}
          <path d={eqArea} fill="url(#lp-eq)" />
          <path d={smooth(bcPts)} fill="none" stroke="#c7c8d0" strokeWidth="1.3" strokeDasharray="4 3" />
          <path d={eqLine} fill="none" stroke="#1200ff" strokeWidth="2" />
          <circle cx={x(N - 1)} cy={eqY[N - 1]} r="6.5" fill="#1200ff" opacity="0.16" />
          <circle cx={x(N - 1)} cy={eqY[N - 1]} r="3.4" fill="#1200ff" />
        </svg>
        <div className="lp-deck-grid">
          <div className="lp-deck-card">
            <div className="lp-deck-card-h">PERFORMANCE</div>
            <div className="lp-deck-stats">
              {stats.map(([k, v]) => (
                <div key={k} className="lp-deck-srow"><span>{k}</span><b>{v}</b></div>
              ))}
            </div>
          </div>
          <div className="lp-deck-card">
            <div className="lp-deck-card-h">MONTHLY P/L · 18M</div>
            <div className="lp-deck-heat">
              {months.map((m, i) => {
                const o = Math.min(0.6, 0.12 + (Math.abs(m) / 8) * 0.58);
                return <span key={i} style={{ background: m >= 0 ? `rgba(22,163,74,${o.toFixed(3)})` : `rgba(220,38,38,${o.toFixed(3)})` }} />;
              })}
            </div>
            <div className="lp-deck-heat-x"><span>LOSS</span><span>FLAT</span><span>GAIN</span></div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  return (
    <div className="lp-root">
      {/* ─── Header ─── */}
      <header className="lp-header">
        <div className="lp-brand">
          <span className="lp-logo" aria-hidden>
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
          </span>
          Project Alpha
        </div>
        <nav className="lp-nav">
          <a href="#toolset">MODULES</a>
          <a href="#metrics">METRICS</a>
        </nav>
      </header>

      {/* ─── Hero ─── */}
      <section className="lp-hero">
        <div className="lp-hero-left">
          <div className="lp-eyebrow lp-mono">KOREAN EQUITY / QUANT ACCESS</div>
          <h1>
            The operating<br />system for<br />quantitative<br />research.
          </h1>
          <div className="lp-cta-row">
            <Link href="/dashboard" className="lp-launch">Launch Terminal</Link>
          </div>
        </div>
        <div className="lp-hero-visual">
          <span className="lp-hero-glow" aria-hidden />
          <HeroDeck />
        </div>
      </section>

      {/* ─── Integrated Toolset ─── */}
      <section className="lp-toolset" id="toolset">
        <div className="lp-section-head">
          <span className="lp-mono">INTEGRATED TOOLSET</span>
          <span className="lp-mono">01 — 05</span>
        </div>
        <div className="lp-modules">
          {MODULES.map((m) => (
            <Link key={m.n} href={m.href} className="lp-module">
              <div className="lp-mono lp-module-code">{m.n}/{m.code}</div>
              <h3>{m.title}</h3>
              <p>{m.desc}</p>
              <div className="lp-module-metrics">
                {m.metrics.map(([k, v]) => (
                  <div key={k} className="lp-metric-row lp-mono">
                    <span>{k}</span><span className="lp-metric-val">{v}</span>
                  </div>
                ))}
              </div>
              <Visual kind={m.visual} />
            </Link>
          ))}
        </div>
      </section>

      {/* ─── Platform Metrics ─── */}
      <section className="lp-stats" id="metrics">
        <div className="lp-section-head">
          <span className="lp-mono">PLATFORM METRICS</span>
          <span className="lp-mono">MEASURED, NOT MARKETED</span>
        </div>
        <div className="lp-stats-grid">
          {PLATFORM_STATS.map(([k, v, sub]) => (
            <div key={k} className="lp-stat">
              <div className="lp-mono lp-stat-key">{k}</div>
              <div className="lp-stat-val">{v}</div>
              <div className="lp-stat-sub">{sub}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ─── Footer ─── */}
      <footer className="lp-footer">
        <div className="lp-mono lp-footer-left">PROJECT ALPHA · KOREAN EQUITY QUANT PLATFORM</div>
        <div className="lp-mono lp-footer-right">
          © 2026 PROJECT ALPHA SYSTEMS · BUILT FOR ACCURACY
        </div>
      </footer>
    </div>
  );
}
