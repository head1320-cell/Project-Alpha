/**
 * Landing — 루트(/). **모듈 갤러리** 형식 (L1 재작성).
 *
 * ★참고한 형식과 바꾼 것★
 * lapa.ninja 류 갤러리 사이트의 정보구조(큰 카드 그리드 · 최소한의 크롬 · 타이포 중심 ·
 * 넉넉한 여백 · 호버로 드러나는 상세)를 가져왔다. 다만 갤러리 항목이 **장식용 스크린샷**이
 * 아니라 **여섯 개 모듈과 그 실제 지표**다. 리서치 도구의 첫 화면이 근거보다 분위기를
 * 앞세우면, 제품 안에서 지켜 온 규칙을 입구에서 깨는 셈이다.
 *
 * ★수치는 전부 출처가 있다★
 * 이전 페이지의 통계 블록은 "MEASURED, NOT MARKETED" 라는 제목을 달고 `TEST SUITE 470`
 * 이라고 적고 있었다 — 실측은 pytest 1,534 / Playwright 163 이다. `142×`(벡터화 배수),
 * `290+`(팩터 수) 같이 재현할 수 없는 값도 함께 있었다. CLAUDE.md 가 경고하는 바로 그
 * 실패다("수치는 문서가 아니라 코드가 진실입니다").
 * 그래서 EVIDENCE 의 모든 항목에 **재현 방법**을 달았고, 달 수 없는 값은 지웠다.
 * 적은 수의 참말이 많은 수의 어림보다 낫다.
 *
 * 모션: 스크롤 **연동**(scroll-linked)이지 스크롤 **가로채기**(scroll-jacking)가 아니다.
 * wheel/touch 를 가로채지 않고 스냅으로 가두지 않는다. 콘텐츠는 첫 페인트에 이미 완결돼
 * 있고 모션은 도착 방식만 바꾼다. prefers-reduced-motion 이면 전부 꺼지고 정적 레이아웃이
 * 곧 최종 디자인이다. globals.css §46 참고.
 */

import Link from "next/link";
import Reveal from "@/widgets/landing/Reveal";
import CountUp from "@/widgets/landing/CountUp";
import HeroDeckLive from "@/widgets/landing/HeroDeckLive";

/** 갤러리 항목 = 모듈. `signature` 는 쉴 때도 보이는 한 줄, `metrics` 는 펼칠 때. */
const MODULES = [
  {
    n: "01", code: "SCREENER", title: "Screener", href: "/screener",
    purpose: "전 종목을 팩터로 좁힌다.",
    desc: "멀티팩터 필터링 · 자연어 검색(nl2ast) · 유동성 게이트 3레이어. 조건은 AST 로 남아 그대로 백테스터로 넘어간다.",
    signature: ["필터 구조", "게이트 → 필터 → 애널라이저"],
    metrics: [["대상", "국내 주권 전체"], ["검색", "자연어 → AST"]],
    visual: "bars",
  },
  {
    n: "02", code: "BACKTEST", title: "Backtester", href: "/backtest",
    purpose: "규칙을 과거에 대고 확인한다.",
    desc: "룰 기반 조건식 엔진. 실행은 run_id 로 영속되어 새로고침·공유·재현이 성립하고, 진행률은 엔진이 실제로 끝낸 일에서 나온다.",
    signature: ["실행 단위", "run_id (영속)"],
    metrics: [["진행 보고", "엔진 실측"], ["결과", "URL 로 재방문"]],
    visual: "line",
  },
  {
    n: "03", code: "MACRO", title: "Macro Analysis", href: "/macro",
    purpose: "지금 어떤 국면인지 고정한다.",
    desc: "4-국면 레짐 판정과 카나리 지표. 판정을 스냅샷으로 **고정**하면 이후 단계가 그 ID를 참조한다 — 값을 복사하지 않으므로 나중에도 같은 근거를 가리킨다.",
    signature: ["근거 고정", "스냅샷 ID 참조"],
    metrics: [["레짐", "4-국면"], ["PIT", "빈티지 기반"]],
    visual: "heat",
  },
  {
    n: "04", code: "COMPANY", title: "Company Analysis", href: "/insights",
    purpose: "한 기업을 공시로 파고든다.",
    desc: "DART 재무를 공시시차(PIT)를 반영해 읽는다. 내재가치와 점수 분해를 함께 보여 주되, 계산할 수 없는 항목은 0 이 아니라 사유를 적는다.",
    signature: ["재무 기준", "DART · 공시시차 반영"],
    metrics: [["가치평가", "RIM · DCF · DDM"], ["없는 값", "0 이 아닌 사유"]],
    visual: "rows",
  },
  {
    n: "05", code: "RISK", title: "Risk Analysis", href: "/risk-tools",
    purpose: "꼬리를 먼저 본다.",
    desc: "시나리오 스트레스와 생존율 분석. 시나리오는 라벨이 아니라 **내용 해시**로 식별되므로, 충격 정의가 바뀌면 화면이 그 사실을 말한다.",
    signature: ["시나리오 신원", "pack_id@해시"],
    metrics: [["충격 정의", "변경 시 경고"], ["분해", "역사 vs 가정"]],
    visual: "gauge",
  },
  {
    n: "06", code: "ALLOCATION", title: "Allocation Studio", href: "/allocation",
    purpose: "결정을 기록으로 남긴다.",
    desc: "Black-Litterman 뷰 · 효율적 프론티어 · 타이밍 오버레이를 리서치 파이프라인으로 묶는다. 결정 → 런 → 스냅샷 → 룰셋 버전이 하나의 사슬로 이어져 나중에 귀인할 수 있다.",
    signature: ["재현 사슬", "결정 → 런 → 스냅샷"],
    metrics: [["모델", "BL · HRP · MVO"], ["타이밍", "일방향 오버레이"]],
    visual: "donut",
  },
];

/**
 * ★EVIDENCE — 모든 항목에 재현 방법이 붙는다★
 * `how` 는 장식이 아니라 계약이다. 여기 적은 방법으로 다시 세었을 때 값이 나오지 않으면
 * 그 항목은 고치거나 지운다. 재현할 수 없어서 **지운** 것: 벡터화 배수(142×), 팩터 수
 * (290+), 체결가 모델 수(13), 조건 함수 수(19) — 근거 레지스트리를 특정하지 못했다.
 */
const EVIDENCE: Array<{ k: string; v: string; how: string }> = [
  { k: "BACKEND TESTS", v: "1,534", how: "pytest tests/ — 1,534 passed / 10 skipped" },
  { k: "E2E TESTS", v: "172", how: "playwright test — 172 passed, 전 라우트 · 오류 가드 포함" },
  { k: "API ENDPOINTS", v: "292", how: "src/api/*.py 의 @router 데코레이터" },
  { k: "APP ROUTES", v: "29", how: "frontend/src/app 의 page.tsx" },
  { k: "DATA SOURCES", v: "5", how: "KRX · DART · KIS · ECOS · FRED — 각 모듈 존재 확인" },
];

// ─── 카드 미니 비주얼 (순수 SVG · 외부 자산 0) ───────────────────────────────
function Visual({ kind }: { kind: string }) {
  if (kind === "bars") {
    const hs = [9, 14, 7, 18, 12, 22, 16, 27, 20, 31];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        {hs.map((h, i) => (
          <rect key={i} className="lp-vbar" x={i * 12 + 2} y={36 - h} width="7" height={h}
            fill={i === hs.length - 1 ? "var(--bs-primary)" : "#d4d4d8"} />
        ))}
      </svg>
    );
  }
  if (kind === "line") {
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        <polyline className="lp-vline2" points="2,32 22,31 42,32 62,28 82,29 102,24 118,26"
          fill="none" stroke="#d4d4d8" strokeWidth="1.2" pathLength={1} />
        <polyline className="lp-vline" points="2,30 22,26 42,29 62,18 82,21 102,10 118,13"
          fill="none" stroke="var(--bs-primary)" strokeWidth="1.6" pathLength={1} />
      </svg>
    );
  }
  if (kind === "heat") {
    const cells = [0.35, 0.7, 1, 0.25, 0.5, 0.2, 1, 0.45, 0.3, 0.6, 0.15, 0.4];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        {cells.map((o, i) => (
          <rect key={i} className="lp-vheat" x={(i % 4) * 30 + 1} y={Math.floor(i / 4) * 12 + 1}
            width="27" height="10" fill="var(--bs-primary)" opacity={0.12 + o * 0.55} />
        ))}
      </svg>
    );
  }
  if (kind === "rows") {
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        {[6, 16, 26].map((y, i) => (
          <g key={i}>
            <rect x="2" y={y} width={86 - i * 18} height="3.5" fill="#e4e4e7" />
            <rect className="lp-vrow" x="2" y={y} width={40 - i * 8} height="3.5" fill="var(--bs-primary)" opacity="0.65" />
          </g>
        ))}
      </svg>
    );
  }
  if (kind === "donut") {
    const C = 2 * Math.PI * 13;
    const segs = [
      { frac: 0.5, color: "var(--bs-primary)", off: 0 },
      { frac: 0.3, color: "#a5b4fc", off: 0.5 },
      { frac: 0.2, color: "#d4d4d8", off: 0.8 },
    ];
    return (
      <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
        <g transform="translate(60,18) rotate(-90)">
          {segs.map((s, i) => (
            <circle key={i} className="lp-vdonut" cx="0" cy="0" r="13" fill="none"
              stroke={s.color} strokeWidth="5"
              strokeDasharray={`${s.frac * C} ${C}`} strokeDashoffset={-s.off * C} pathLength={C} />
          ))}
        </g>
      </svg>
    );
  }
  return (
    <svg className="lp-visual" viewBox="0 0 120 36" aria-hidden>
      <circle cx="60" cy="18" r="13" fill="none" stroke="#e4e4e7" strokeWidth="2.5" />
      <path className="lp-vgauge" d="M 60 5 A 13 13 0 0 1 72.3 22" fill="none" stroke="var(--bs-primary)" strokeWidth="2.5" pathLength={1} />
    </svg>
  );
}

export default function Landing() {
  return (
    <div className="lp-root">
      {/* JS·모션이 없어도 콘텐츠가 숨지 않도록 — 등장 애니메이션의 기본값이 opacity:0 이다. */}
      <noscript>
        <style>{".lp-reveal,.lp-stagger>*,.lp-module{opacity:1!important;transform:none!important}"}</style>
      </noscript>

      <header className="lp-header">
        <div className="lp-brand">
          <span className="lp-logo" aria-hidden>
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
          </span>
          Project Alpha
        </div>
        <nav className="lp-nav">
          <a href="#modules">MODULES</a>
          <a href="#evidence">EVIDENCE</a>
          <Link href="/dashboard" className="lp-nav-cta">Dashboard →</Link>
        </nav>
      </header>

      {/* ── 진술: 문장 하나 + 살아 있는 증거 하나 ── */}
      <section className="lp-statement">
        <Reveal className="lp-statement-copy" stagger>
          <p className="lp-eyebrow lp-mono">KOREAN EQUITY · QUANT RESEARCH</p>
          <h1>
            근거를 남기는<br />리서치 환경.
          </h1>
          <p className="lp-lede">
            화면이 예뻐 보이는 것보다 <b>수치가 어디서 왔는지</b> 말할 수 있는 것을 우선합니다.
            계산할 수 없는 값은 0 으로 채우지 않고, 없다고 적습니다.
          </p>
        </Reveal>
        <div className="lp-statement-live">
          {/* 스톡 일러스트가 아니라 백테스터 화면의 레이아웃 예시다.
              ★수치는 실적이 아니다★ — 처음에 나는 여기에 "백엔드가 없으면 스스로 빈 상태를
              말한다" 라고 적었는데, 사실이 아니었다. 덱은 백엔드를 아예 호출하지 않고 전부
              하드코딩이다. 그래서 배지를 `예시 수치` 로 바꾸고 덱 아래에 그 사실을 적는다. */}
          <HeroDeckLive />
        </div>
      </section>

      {/* ── 갤러리: 여섯 개 모듈 ── */}
      <section className="lp-gallery-wrap" id="modules">
        <div className="lp-section-head">
          <span className="lp-mono">RESEARCH MODULES</span>
          <span className="lp-mono">SIX SURFACES · ONE RECORD</span>
        </div>
        <div className="lp-gallery">
          {MODULES.map((m) => (
            <Link key={m.n} href={m.href} className="lp-module">
              <div className="lp-module-top">
                <span className="lp-mono lp-module-code">{m.n} / {m.code}</span>
                <span className="lp-module-open lp-mono" aria-hidden>OPEN ↗</span>
              </div>
              <h3>{m.title}</h3>
              <p className="lp-module-purpose">{m.purpose}</p>

              {/* 쉴 때도 보이는 한 줄 — 카드가 이름만 있는 상자가 되지 않게. */}
              <div className="lp-module-sig lp-mono">
                <span>{m.signature[0]}</span><b>{m.signature[1]}</b>
              </div>

              {/* 펼침: 호버 **그리고** 포커스에서 열린다(키보드 사용자에게도 같은 정보). */}
              <div className="lp-module-more">
                <p className="lp-module-desc">{m.desc}</p>
                <div className="lp-module-metrics">
                  {m.metrics.map(([k, v]) => (
                    <div key={k} className="lp-metric-row lp-mono">
                      <span>{k}</span><span className="lp-metric-val">{v}</span>
                    </div>
                  ))}
                </div>
                <Visual kind={m.visual} />
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── 증거: 출처 없는 수치는 없다 ── */}
      <section className="lp-evidence-wrap" id="evidence">
        <div className="lp-section-head">
          <span className="lp-mono">EVIDENCE</span>
          <span className="lp-mono">모든 값에 재현 방법이 붙습니다</span>
        </div>
        <Reveal className="lp-evidence" stagger>
          {EVIDENCE.map((e) => (
            <div key={e.k} className="lp-ev">
              <div className="lp-mono lp-ev-k">{e.k}</div>
              <div className="lp-ev-v"><CountUp value={e.v} /></div>
              <div className="lp-ev-how">{e.how}</div>
            </div>
          ))}
        </Reveal>
        <p className="lp-evidence-note">
          재현할 수 없는 수치는 이 표에서 <b>지웠습니다</b> — 반올림해서 남겨 두는 것보다
          없는 편이 정확합니다.
        </p>
      </section>

      <Reveal as="footer" className="lp-footer" stagger>
        <div className="lp-mono lp-footer-left">
          <i className="lp-status-dot" aria-hidden />PROJECT ALPHA
        </div>
        <div className="lp-mono lp-footer-right">
          © 2026 PROJECT ALPHA · BUILT FOR ACCURACY
        </div>
      </Reveal>
    </div>
  );
}
