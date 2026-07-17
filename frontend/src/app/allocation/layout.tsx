"use client";
// Allocation Studio 공유 레이아웃 — AllocationProvider(전역 상태) + ContextStrip +
// Sub-Navbar. layout은 자식 라우트 전환에도 유지 → 워크스페이스 간 이동 시
// 유니버스·뷰·가중치·결과가 보존된다 (Nested Routing & Micro-Workspaces).
import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AllocationProvider } from "@/components/allocation/AllocationProvider";
import { ContextStrip } from "@/components/allocation/ContextStrip";

const TABS: { href: string; label: string; exact?: boolean }[] = [
  { href: "/allocation", label: "Hub", exact: true },
  { href: "/allocation/thesis", label: "Thesis" },
  { href: "/allocation/optimizer", label: "Optimizer" },
  { href: "/allocation/robustness", label: "Robustness" },
  { href: "/allocation/explainability", label: "Explainability" },
  { href: "/allocation/journal", label: "Journal" },
];

function SubNav() {
  const pathname = usePathname();
  return (
    <nav className="as-subnav">
      {TABS.map((t) => {
        const active = t.exact ? pathname === t.href : pathname.startsWith(t.href);
        return (
          <Link key={t.href} href={t.href} className={`as-subnav-tab${active ? " on" : ""}`}>
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function AllocationLayout({ children }: { children: React.ReactNode }) {
  return (
    <AllocationProvider>
      <div className="as-root tpage-fade">
        <ContextStrip />
        <SubNav />
        {children}
      </div>
    </AllocationProvider>
  );
}
