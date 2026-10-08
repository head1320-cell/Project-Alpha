"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { backtestBridgeApi } from "@/entities/backtest/bridgeApi";
import { analysisApi } from "@/entities/macro/analysisApi";
import { screenerApiAdvanced } from "@/entities/screener/api/ast";
import { screenerApi } from "@/entities/screener/api/core";
import { macroApi } from "@/entities/macro/api";
import { loadCompanyCore } from "@/entities/company/data";
import { allocationApi } from "@/entities/allocation/api";
import { useSession } from "@/entities/session";
import { ProfileMenu, useThemeSync } from "@/features/profile";
import {
  Building2, Database, Gauge, Globe2, Home, Layers, LineChart, ListFilter, Radio, Settings, ShieldAlert, Sigma, Workflow,
  type LucideIcon,
} from "lucide-react";
import { Breadcrumb } from "./Breadcrumb";
import { ShellSearch } from "./ShellSearch";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalShell — 앱 셸(머리 줄 + 왼쪽 메뉴 + 본문). BU0(ADR-003)에서 토스식으로 바꿨다:
//   한국어 메뉴 + 아이콘 · 번호·고정폭·격자 무늬·모서리 표식 없음 · 머리 줄 찾기(`/`) · 관리 메뉴는 관리자에게만.
//   클래스 `.terminal-*`·`.nav-item` 는 E2E 계약이라 그대로 둔다(스타일만 바뀐다).
// ═══════════════════════════════════════════════════════════════════════════════

type NavLink = { label: string; href: string; Icon: LucideIcon };

/** 하는 일 순서 — 홈 → 찾고 → 돌려 보고 → 흐름·기업·위험을 읽고 → 설계하고 → 데이터 상태. */
const MAIN: NavLink[] = [
  { label: "홈", href: "/dashboard", Icon: Home },
  { label: "종목 찾기", href: "/screener", Icon: ListFilter },
  { label: "백테스트", href: "/backtest", Icon: LineChart },
  { label: "매크로 분석", href: "/macro", Icon: Globe2 },
  { label: "기업 분석", href: "/insights", Icon: Building2 },
  { label: "위험 점검", href: "/risk-tools", Icon: ShieldAlert },
  { label: "포트폴리오 설계", href: "/allocation", Icon: Workflow },
  { label: "데이터 상태", href: "/admin/data", Icon: Database },
];
const MORE: NavLink[] = [
  { label: "파생상품 계산기", href: "/derivatives", Icon: Sigma },
  { label: "설정", href: "/settings", Icon: Settings },
];
/** 관리자에게만 보인다 — 숨김은 편의일 뿐 권한이 아니다(권한은 서버가 판정한다). */
const ADMIN: NavLink[] = [
  { label: "실거래", href: "/admin/live-trading", Icon: Radio },
  { label: "여러 전략 백테스트", href: "/admin/multi-backtest", Icon: Layers },
  { label: "현실성 점검", href: "/admin/realism", Icon: Gauge },
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
    // ★매크로 키는 실패를 null 로 감싸지 않는다★ prefetchQuery 는 실패를 던지지 않고 캐시에 실패 상태로 둔다 — 화면이 마운트되면
    // 다시 묻는다. 예전 `.catch(() => null)` 은 실패를 "성공 null" 로 하루 동안 캐시해 화면이 실패를 몰랐다(BU5a).
    "/macro": () => {
      qc.prefetchQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime() });
      qc.prefetchQuery({ queryKey: ["macro", "dashboard"], queryFn: () => analysisApi.macroDashboard() });
      qc.prefetchQuery({ queryKey: ["macro", "valuation"], queryFn: () => analysisApi.macroValuation() });
      qc.prefetchQuery({ queryKey: ["macro", "strategies", "kr"], queryFn: () => analysisApi.macroStrategies("kr") });
      qc.prefetchQuery({ queryKey: ["macro", "recommend", "kr"], queryFn: () => analysisApi.macroRecommend("kr") });
    },
    "/insights": () => {
      // 페이지 기본 종목(005930)과 동일 — 다른 종목으로 들어오면 그 종목만 별도 요청됨(정상)
      qc.prefetchQuery({ queryKey: ["company", "core", "005930"], queryFn: () => loadCompanyCore("005930") });
    },
    "/allocation": () => {
      // 게이트(목표 선택) 시드 소스 + 시나리오 카탈로그를 미리 워밍 → 목표 카드 즉시 시드
      qc.prefetchQuery({ queryKey: ["allocation", "stress-catalog"], queryFn: () => allocationApi.stressCatalog().catch(() => null) });
      qc.prefetchQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime() });
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
  // 화면 테마(BR R3) — 랜딩으로 나가도 다크가 남지 않게 셸이 조기 반환하기 전에 맞춘다.
  useThemeSync(pathname ?? "");
  const { session } = useSession();
  const admin = session.kind === "signed_in" && session.role === "admin";
  const screens = useMemo(() => [...MAIN, ...MORE, ...(admin ? ADMIN : [])].map(({ label, href }) => ({ label, href })), [admin]);

  // 루트(/)는 랜딩 페이지, /login 은 메뉴 없는 단독 한 화면(BU8b) — 터미널 셸 없이 풀블리드 렌더
  if (pathname === "/" || pathname === "/login") return <>{children}</>;

  const isOn = (href: string) => pathname === href || pathname.startsWith(href + "/");
  const item = (m: NavLink) => {
    const on = isOn(m.href);
    return (
      <Link key={m.href} href={m.href} aria-label={m.label} aria-current={on ? "page" : undefined}
        onClick={() => setPinned(false)} onMouseEnter={() => prefetchTab(m.href)} className={`nav-item${on ? " active" : ""}`}>
        <m.Icon className="nav-icon" aria-hidden />
        <span className="nav-meta"><span className="nav-text">{m.label}</span></span>
      </Link>
    );
  };

  return (
    <div className="terminal-root">
      {/* ─── 머리 줄 ─── */}
      <header className="terminal-header">
        <Link href="/" className="terminal-brand" aria-label="Project Alpha 첫 화면으로">
          <span className="logo-box" aria-hidden>
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
          </span>
          <span className="project-name">Project Alpha</span>
        </Link>
        <ShellSearch screens={screens} />
        {/* 회원 프로필(BR R3) — 동그라미를 누르면 아래로 카드. 국면 배지는 뺐다(국면은 /macro 에). */}
        <div className="header-actions">
          <ProfileMenu />
        </div>
      </header>

      {/* ─── 메뉴 + 본문 ─── */}
      <div className="terminal-body">
        <aside className={`terminal-sidebar${pinned ? " pinned" : ""}`}>
          <button type="button" className="rail-toggle" aria-label={pinned ? "메뉴 접기" : "메뉴 펼치기"}
            aria-expanded={pinned} onClick={() => setPinned((p) => !p)}>
            <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
          </button>
          <nav className="terminal-nav" aria-label="메뉴">
            {MAIN.map(item)}
            <div className="nav-sep" role="separator" />
            {MORE.map(item)}
            {admin && (
              <>
                <div className="nav-sep" role="separator" />
                <div className="nav-group fade-x" aria-hidden>관리</div>
                {ADMIN.map(item)}
              </>
            )}
          </nav>
        </aside>
        {pinned && <div className="sidebar-backdrop" onClick={() => setPinned(false)} />}

        <main className="terminal-main">
          <div className="terminal-content">
            <Breadcrumb />
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
