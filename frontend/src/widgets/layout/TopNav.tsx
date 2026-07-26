"use client";

import { useState } from "react";
import { RegimeBadge, CommandHint, useRegimeInfo } from "@/shared/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown } from "lucide-react";

const NAV = [
  {
    label: "전략 빌더",
    href: "/builder",
    items: [
      { label: "비주얼 빌더",     href: "/builder",                 desc: "지표 + 조건 5단계 설계" },
      { label: "DSL 커스텀",      href: "/builder?tab=dsl",         desc: "수식으로 직접 작성" },
      { label: "YAML 가져오기",   href: "/builder?tab=yaml",        desc: ".kis.yaml 임포트" },
      { label: "전략 라이브러리", href: "/builder?tab=library",     desc: "10개 KIS 프리셋" },
      { label: "노드 캔버스",     href: "/builder?tab=canvas",      desc: "React Flow 시각적 설계" },
    ],
  },
  {
    label: "백테스팅",
    href: "/backtest",
    items: [
      { label: "전략 백테스트",     href: "/backtest",                desc: "KIS 10대 전략 검증" },
      { label: "파라미터 최적화",    href: "/backtest?tab=optimize",   desc: "Grid Search 최적값" },
      { label: "포트폴리오 백테스트", href: "/backtest?tab=portfolio", desc: "다종목 비교" },
      { label: "리밸런싱 시뮬",      href: "/backtest?tab=rebalance",  desc: "주기별 효과 분석" },
      { label: "전략 실행",          href: "/backtest?tab=execute",    desc: "실시간 시그널·주문" },
    ],
  },
  {
    label: "리스크 도구",
    href: "/risk-tools",
    items: [
      { label: "VaR 계산",         href: "/risk-tools",                desc: "Value at Risk + ES" },
      { label: "포트폴리오 분석",   href: "/risk-tools?tab=portfolio",  desc: "상관관계 · 분산비율" },
      { label: "효율적 프론티어",   href: "/risk-tools?tab=frontier",   desc: "Mean-Variance 최적화" },
      { label: "팩터 회귀",        href: "/risk-tools?tab=factor",     desc: "Fama-French 분석" },
    ],
  },
  {
    label: "스크리너",
    href: "/screener",
    items: [
      { label: "전 종목 스캔",      href: "/screener",                   desc: "RIM·DCF·DDM 통합 평가" },
      { label: "Top 저평가",       href: "/screener?sort=composite",   desc: "Composite 점수 순위" },
      { label: "고배당주",          href: "/screener?filter=dividend",  desc: "배당수익률 필터" },
      { label: "재무 우량주",       href: "/screener?filter=quality",   desc: "ROE+FCF+낮은 부채" },
      { label: "방법론",            href: "/screener#methodology",      desc: "스코어링 공식 설명" },
    ],
  },
  {
    label: "매크로",
    href: "/macro",
    items: [
      { label: "매크로 레이더",     href: "/macro",                   desc: "16지표 + Heatmap + Yield Curve" },
      { label: "4-Quadrant",     href: "/macro#quadrant",          desc: "Growth × Inflation 국면" },
      { label: "Yield Curve",   href: "/macro#yield",             desc: "3M~30Y 곡선 + 역전 감지" },
      { label: "Stress Index",  href: "/macro#stress",            desc: "시장 공포 지수 0-100" },
      { label: "동적 파라미터",     href: "/macro#dynamic",           desc: "Valuation/KillSwitch 자동 갱신" },
    ],
  },
  {
    label: "AI 인사이트",
    href: "/insights",
    items: [
      { label: "종목 분석",        href: "/insights?d=stock",          desc: "Claude의 가치평가 해석" },
      { label: "포트폴리오 보고서", href: "/insights?d=portfolio",      desc: "5-Factor Attribution 해설" },
      { label: "매크로 브리핑",     href: "/insights?d=macro",          desc: "Regime + 5종 지표 해석" },
      { label: "운영 사건 분석",    href: "/insights?d=operations",     desc: "Kill switch 사후 분석" },
      { label: "What-If 시나리오", href: "/insights?d=counterfactual", desc: "의사결정 가치 정량화" },
      { label: "일일 요약",        href: "/insights?d=daily",          desc: "오늘 활동 통합 요약" },
    ],
  },
  {
    label: "파생상품 평가",
    href: "/derivatives",
    items: [
      { label: "옵션 프라이싱",   href: "/derivatives",               desc: "Black-76 + Greeks" },
      { label: "변동성 표면",     href: "/derivatives?tab=vol-surface", desc: "Implied Vol Surface" },
      { label: "XVA / CVA",      href: "/derivatives?tab=xva",        desc: "Credit Valuation" },
      { label: "금리 모델",       href: "/derivatives?tab=rates",      desc: "Hull-White · SABR" },
      { label: "Monte Carlo",    href: "/derivatives?tab=mc",         desc: "MC 시뮬레이션" },
    ],
  },
];

export default function TopNav() {
  const regimeInfo = useRegimeInfo();
  const regimeBorderClass = regimeInfo
    ? regimeInfo.mode === "DEFENSIVE" ? "regime-border-danger"
      : regimeInfo.mode === "CAUTIOUS" ? "regime-border-caution"
      : "regime-border-normal"
    : "";
  const path = usePathname();
  const [open, setOpen] = useState<number | null>(null);

  return (
    <header className={`pv-navbar ${regimeBorderClass}`}>
      <div className="container-pv pv-navbar-inner">
        {/* Brand */}
        <Link href="/" className="pv-navbar-brand">
          <div style={{
            width: 32, height: 32,
            background: "rgba(255,255,255,0.15)",
            borderRadius: 6,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 16, fontWeight: 800,
            fontFamily: "'Roboto Mono', monospace",
          }}>F</div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, lineHeight: 1.1 }}>FICC Quant Platform</div>
            <div style={{ fontSize: 10, color: "rgba(255,255,255,0.6)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
              Institutional Trading Tools
            </div>
          </div>
        </Link>

        {/* Nav */}
        <nav className="flex items-center gap-1" style={{ display: "flex" }}>
          {NAV.map((item, i) => {
            const isActive = path === item.href || path.startsWith(item.href + "/");
            const isOpen = open === i;
            return (
              <div key={item.href}
                style={{ position: "relative" }}
                onMouseEnter={() => setOpen(i)}
                onMouseLeave={() => setOpen(null)}>
                <Link
                  href={item.href}
                  className={`pv-navbar-link${isActive ? " active" : ""}`}
                >
                  {item.label}
                  <ChevronDown size={11} style={{
                    opacity: 0.7,
                    transform: isOpen ? "rotate(180deg)" : "none",
                    transition: "transform 0.15s",
                  }} />
                </Link>
                {isOpen && (
                  <div className="pv-dropdown">
                    {item.items.map((tool) => (
                      <Link key={tool.href} href={tool.href} className="pv-dropdown-item">
                        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--bs-body-color)" }}>
                          {tool.label}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--bs-secondary-color)", marginTop: 1 }}>
                          {tool.desc}
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Status indicator + Regime + Command */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <RegimeBadge />
          <CommandHint />
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            fontSize: 11, color: "rgba(255,255,255,0.7)",
          }}>
            <span className="animate-pulse-dot" style={{
              width: 6, height: 6, borderRadius: "50%", background: "#35ffb6",
            }} />
            KIS Mock
          </span>
        </div>
      </div>
    </header>
  );
}
