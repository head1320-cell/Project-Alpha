"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// Breadcrumb — 모든 툴 탭 상단의 공통 경로 표시(셸 레벨, terminal-content 최상단).
//   pathname → 활성 모듈 해소(가장 긴 프리픽스) + 더 깊은 세그먼트가 있으면 말단 크럼 추가.
//   ⌂ PROJECT ALPHA › {NN} {모듈} [ › {서브} ]. 데이터 페칭 0 · 랜딩(/)엔 셸이 안 붙어 미표시.
// ═══════════════════════════════════════════════════════════════════════════════
import Link from "next/link";
import { usePathname } from "next/navigation";

// 셸 MODULES와 동일한 순서/라벨(경로 프리픽스 해소용) — 라벨은 크럼 표기에 맞춰 간결화.
const MODULES: { n: string; label: string; href: string }[] = [
  { n: "00", label: "Dashboard", href: "/dashboard" },
  { n: "01", label: "Screener", href: "/screener" },
  { n: "02", label: "Backtester", href: "/backtest" },
  { n: "03", label: "Macro Analysis", href: "/macro" },
  { n: "04", label: "Company Analysis", href: "/insights" },
  { n: "05", label: "Risk Analysis", href: "/risk-tools" },
  { n: "06", label: "Allocation Studio", href: "/allocation" },
  { n: "07", label: "Data Infra", href: "/admin/data" },
];

// 말단 세그먼트 라벨 — 알려진 것만 사람이 읽는 이름으로, 그 외엔 표시 안 함(동적 id 등 노출 방지).
const SUB_LABELS: Record<string, string> = {
  loading: "실행 중", results: "결과", compare: "비교",
  construct: "구성", thesis: "테제", timing: "타이밍", optimize: "최적화",
  stress: "스트레스", explain: "설명", journal: "저널", overview: "개요",
  execution: "실행", alphalab: "AlphaLab", data: "데이터", "live-trading": "라이브",
  "multi-backtest": "멀티 백테스트", realism: "리얼리즘",
};

export function Breadcrumb() {
  const pathname = usePathname() || "";
  // 가장 긴 프리픽스로 활성 모듈 해소
  const mod = MODULES
    .filter((m) => pathname === m.href || pathname.startsWith(m.href + "/"))
    .sort((a, b) => b.href.length - a.href.length)[0];
  if (!mod) return null; // 매핑 안 되는 경로(랜딩 등)엔 크럼 없음

  // 모듈 프리픽스 이후 세그먼트 중 알려진 라벨만 말단 크럼으로
  const rest = pathname.slice(mod.href.length).split("/").filter(Boolean);
  const subKey = [...rest].reverse().find((s) => SUB_LABELS[s]);
  const sub = subKey ? SUB_LABELS[subKey] : null;

  return (
    <nav className="tcrumb" aria-label="Breadcrumb">
      <Link href="/dashboard" className="tcrumb-home" aria-label="대시보드로">⌂</Link>
      <span className="tcrumb-brand">PROJECT ALPHA</span>
      <span className="tcrumb-sep" aria-hidden>›</span>
      <Link href={mod.href} className="tcrumb-cur">
        <span className="tcrumb-n">{mod.n}</span>{mod.label}
      </Link>
      {sub && <><span className="tcrumb-sep" aria-hidden>›</span><span className="tcrumb-sub">{sub}</span></>}
    </nav>
  );
}
