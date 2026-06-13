"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalShell — Variant "Institutional Terminal" 좌측 사이드바 셸
//   5개 핵심 모듈 + 시스템 상태 + 터미널 디테일 (코너마크/메타스탬프/그리드)
// ═══════════════════════════════════════════════════════════════════════════════

const MODULES = [
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
];

export function TerminalShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // 루트(/)는 랜딩 페이지 — 터미널 셸 없이 풀블리드 렌더 (CTA가 /dashboard로 진입)
  if (pathname === "/") return <>{children}</>;

  return (
    <div className="terminal-root">
      {/* ─── Header ─── */}
      <header className="terminal-header">
        <Link href="/dashboard" className="terminal-brand">
          <div className="logo-box">
            <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
          </div>
          <div className="project-name">
            Project Alpha
          </div>
        </Link>
      </header>

      {/* ─── App body: sidebar + main ─── */}
      <div className="terminal-body">
        <aside className="terminal-sidebar">
          <div className="nav-label">Core Modules</div>
          <nav className="terminal-nav">
            {MODULES.map((m) => {
              const active = pathname === m.href || pathname.startsWith(m.href + "/");
              return (
                <Link key={m.href} href={m.href} className={`nav-item${active ? " active" : ""}`}>
                  <span className="nav-number">{m.n}</span>
                  {m.icon}
                  {m.label}
                </Link>
              );
            })}
          </nav>
        </aside>

        <main className="terminal-main">
          <div className="grid-overlay" />
          <div className="corner-mark top-left" />
          <div className="corner-mark top-right" />
          <div className="corner-mark bottom-left" />
          <div className="corner-mark bottom-right" />
          <div className="terminal-content">{children}</div>
        </main>
      </div>
    </div>
  );
}
