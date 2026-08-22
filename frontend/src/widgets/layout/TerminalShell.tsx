"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { backtestBridgeApi } from "@/entities/backtest/bridgeApi";
import { analysisApi } from "@/entities/macro/analysisApi";
import { screenerApiAdvanced } from "@/entities/screener/api/ast";
import { screenerApi } from "@/entities/screener/api/core";
import { macroApi } from "@/entities/macro/api";
import { loadCompanyCore } from "@/entities/company/data";
import { allocationApi } from "@/entities/allocation/api";
import { RegimeBadge } from "@/entities/macro/RegimeBadge";
import { Breadcrumb } from "./Breadcrumb";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalShell — Variant "Institutional Terminal" 좌측 사이드바 셸
//   5개 핵심 모듈 + 시스템 상태 + 터미널 디테일 (코너마크/메타스탬프/그리드)
// ═══════════════════════════════════════════════════════════════════════════════

const MODULES = [
  {
    n: "00", label: "Dashboard", href: "/dashboard",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></svg>
    ),
  },
  {
    n: "01", label: "Screener", href: "/screener",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18M9 21V9" /></svg>
    ),
  },
  {
    n: "02", label: "Backtester", href: "/backtest",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" /></svg>
    ),
  },
  {
    n: "03", label: "Macro Analysis", href: "/macro",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20M2 12h20" /></svg>
    ),
  },
  {
    n: "04", label: "Company Analysis", href: "/insights",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><path d="M3 3h18v18H3zM21 9H3M21 15H3M12 3v18" /></svg>
    ),
  },
  {
    n: "05", label: "Risk Analysis", href: "/risk-tools",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
    ),
  },
  {
    n: "06", label: "Allocation Studio", href: "/allocation",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><path d="M21.21 15.89A10 10 0 1 1 8 2.83" /><path d="M22 12A10 10 0 0 0 12 2v10z" /></svg>
    ),
  },
  {
    n: "07", label: "Data Infra", href: "/admin/data",
    icon: (
      <svg className="nav-icon" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5" /><path d="M3 12a9 3 0 0 0 18 0" /></svg>
    ),
  },
];

// 사이드바 hover → 탭 핵심 진입 데이터 prefetch (react-query 캐시에 미리 채워둠 — 이 코드베이스
// 최초의 hover-prefetch 패턴). 탭 클릭 전에 이미 로드가 끝나 있으면 스피너 없이 즉시 렌더된다.
// 각 탭의 useQuery와 정확히 같은 queryKey/queryFn을 써야 캐시가 재사용됨.
function usePrefetchers() {
  const qc = useQueryClient();
  const prefetch: Record<string, () => void> = {
    "/screener": () => {
      qc.prefetchQuery({ queryKey: ["screener", "fields"], queryFn: () => screenerApiAdvanced.fields() });
      qc.prefetchQuery({ queryKey: ["screener", "indicators"], queryFn: () => screenerApiAdvanced.indicators() });
      qc.prefetchQuery({ queryKey: ["screener", "factor-field-map"], queryFn: () => screenerApiAdvanced.factorFieldMap() });
      qc.prefetchQuery({ queryKey: ["screener", "universes"], queryFn: () => screenerApi.universes() });
    },
    "/macro": () => {
      qc.prefetchQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime().catch(() => null) });
      qc.prefetchQuery({ queryKey: ["macro", "dashboard"], queryFn: () => analysisApi.macroDashboard().catch(() => null) });
      qc.prefetchQuery({ queryKey: ["macro", "valuation"], queryFn: () => analysisApi.macroValuation().catch(() => null) });
      qc.prefetchQuery({ queryKey: ["macro", "strategies", "kr"], queryFn: () => analysisApi.macroStrategies("kr").catch(() => null) });
      qc.prefetchQuery({ queryKey: ["macro", "recommend", "kr"], queryFn: () => analysisApi.macroRecommend("kr").catch(() => null) });
    },
    "/insights": () => {
      // 페이지 기본 종목(005930)과 동일 — 다른 종목으로 들어오면 그 종목만 별도 요청됨(정상)
      qc.prefetchQuery({ queryKey: ["company", "core", "005930"], queryFn: () => loadCompanyCore("005930") });
    },
    "/allocation": () => {
      // 게이트(목표 선택) 시드 소스 + 시나리오 카탈로그를 미리 워밍 → 목표 카드 즉시 시드
      qc.prefetchQuery({ queryKey: ["allocation", "stress-catalog"], queryFn: () => allocationApi.stressCatalog().catch(() => null) });
      qc.prefetchQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime().catch(() => null) });
      qc.prefetchQuery({ queryKey: ["screener", "sectors"], queryFn: () => backtestBridgeApi.sectors().catch(() => null) });
    },
  };
  return (href: string) => prefetch[href]?.();
}

export function TerminalShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // 터치/클릭 토글 — 호버가 없는 환경에서 사이드바를 고정으로 펼침
  const [pinned, setPinned] = useState(false);
  const prefetchTab = usePrefetchers();

  // 루트(/)는 랜딩 페이지 — 터미널 셸 없이 풀블리드 렌더 (CTA가 /dashboard로 진입)
  if (pathname === "/") return <>{children}</>;

  return (
    <div className="terminal-root">
      {/* ─── Header ─── */}
      <header className="terminal-header">
        <Link href="/" className="terminal-brand" title="랜딩 페이지로">
          <div className="logo-box">
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
          </div>
          <div className="project-name">
            Project Alpha
          </div>
        </Link>

        {/* 현재 시장 국면 배지 — 클릭하면 /macro 로. 삭제된 TopNav 가 유일 소비자였던
            것을 셸로 옮겨 살렸다. .header-actions 는 이미 정의만 되어 있던 빈 슬롯. */}
        <div className="header-actions">
          <RegimeBadge />
        </div>
      </header>

      {/* ─── App body: sidebar + main ─── */}
      <div className="terminal-body">
        <aside className={`terminal-sidebar${pinned ? " pinned" : ""}`}>
          <button type="button" className="rail-toggle" aria-label={pinned ? "사이드바 접기" : "사이드바 펼치기"}
            aria-expanded={pinned} onClick={() => setPinned((p) => !p)}>
            <svg className="nav-icon" viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
          </button>
          <div className="nav-label fade-x">Core Modules</div>
          <nav className="terminal-nav">
            {MODULES.map((m) => {
              const active = pathname === m.href || pathname.startsWith(m.href + "/");
              return (
                <Link key={m.href} href={m.href} title={m.label} onClick={() => setPinned(false)}
                  onMouseEnter={() => prefetchTab(m.href)} className={`nav-item${active ? " active" : ""}`}>
                  {m.icon}
                  <span className="nav-meta">
                    <span className="nav-number">{m.n}</span>
                    <span className="nav-text">{m.label}</span>
                  </span>
                </Link>
              );
            })}
          </nav>
        </aside>
        {pinned && <div className="sidebar-backdrop" onClick={() => setPinned(false)} />}

        <main className="terminal-main">
          <div className="grid-overlay" />
          <div className="corner-mark top-left" />
          <div className="corner-mark top-right" />
          <div className="corner-mark bottom-left" />
          <div className="corner-mark bottom-right" />
          <div className="terminal-content">
            <Breadcrumb />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
