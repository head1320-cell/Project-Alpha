"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// Breadcrumb — 중첩 경로에만 "상위 › 현재" 한 줄 (BU0 · ADR-003).
//   최상위 화면(홈·종목 찾기 …)은 메뉴가 이미 "지금 어디"를 말하므로 그리지 않는다(예전엔 메뉴를 되풀이했다).
//   알려진 중첩만 이름을 붙인다 — 동적 id(실행 번호 등)는 화면에 내보내지 않는다. 데이터 페칭 0.
//   클래스 `.tcrumb`·`.tcrumb-up`·`.tcrumb-sep`·`.tcrumb-cur` 는 E2E 계약(nav.spec).
// ═══════════════════════════════════════════════════════════════════════════════
import Link from "next/link";
import { usePathname } from "next/navigation";

type Crumb = { up: string; upHref: string | null; cur: string };

const MACRO_STUDIO: Record<string, string> = {
  "tsfm-latent": "잠재 요인", "neural-sde": "기간 구조", "causal-deepm": "인과 관계",
  "pinn-tail": "꼬리 위험", "agentic-mcp": "뷰 만들기",
};
const RUN_STEP: Record<string, string> = { loading: "실행 중", results: "결과", compare: "비교" };
const ADMIN: Record<string, string> = { "live-trading": "실거래", "multi-backtest": "여러 전략 백테스트", realism: "현실성 점검" };

/** 경로 → 크럼. 알려진 중첩이 아니면 null(최상위·모르는 경로는 그리지 않는다). */
export function crumbOf(pathname: string): Crumb | null {
  const seg = pathname.split("/").filter(Boolean);
  if (seg[0] === "backtest" && seg[1] === "runs" && seg.length === 4 && RUN_STEP[seg[3]])
    return { up: "백테스트", upHref: "/backtest", cur: RUN_STEP[seg[3]] };
  if (seg[0] === "macro" && seg.length === 2 && MACRO_STUDIO[seg[1]])
    return { up: "경제 흐름", upHref: "/macro", cur: MACRO_STUDIO[seg[1]] };
  if (seg[0] === "admin" && seg.length === 2 && ADMIN[seg[1]])
    return { up: "관리", upHref: null, cur: ADMIN[seg[1]] };
  return null;
}

export function Breadcrumb() {
  const c = crumbOf(usePathname() || "");
  if (!c) return null;
  return (
    <nav className="tcrumb" aria-label="현재 위치">
      {c.upHref ? <Link href={c.upHref} className="tcrumb-up">{c.up}</Link> : <span className="tcrumb-up">{c.up}</span>}
      <span className="tcrumb-sep" aria-hidden>›</span>
      <span className="tcrumb-cur" aria-current="page">{c.cur}</span>
    </nav>
  );
}
