"use client";

// ══════════════════════════════════════════════════════════════════════════════
// Dashboard (00) — Institutional Terminal 콕핏
//   5개 모듈(Screener·Backtester·Macro·Company·Risk)과 깊이 연동된 라이트 터미널 홈.
//   · 글로벌 종목 검색(이름/코드 자동완성 → 기업분석)
//   · 매크로 국면(실데이터) · 모듈 그리드 · 스크리너 저평가 Top · 데이터 적재 현황
// ══════════════════════════════════════════════════════════════════════════════

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import PageHeader from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/States";
import { macroApi, type RegimeState, REGIME_COLORS } from "@/lib/macroApi";
import { screenerApiAdvanced, companyApi, type ScreenerItem } from "@/lib/screenerApi";
import { API_BASE } from "@/lib/apiBase";

const MODULES = [
  { n: "01", label: "Screener", href: "/screener", desc: "116팩터 멀티팩터 스크리닝 · 전종목/ETF" },
  { n: "02", label: "Backtester", href: "/backtest", desc: "전략 실행·설계·비교 · 체결가 13종" },
  { n: "03", label: "Macro", href: "/macro", desc: "4-국면도 · 동적 무위험수익률" },
  { n: "04", label: "Company", href: "/insights", desc: "DART+KIS 통합 · RIM·DCF·DDM 내재가치" },
  { n: "05", label: "Risk", href: "/risk-tools", desc: "VaR · 스트레스 시나리오 · 생존율" },
];

export default function Dashboard() {
  return (
    <div className="tpage-fade">
      <PageHeader
        eyebrow="PLATFORM / COMMAND CENTER"
        index="00"
        title="Dashboard"
        intro="스크리너 · 백테스터 · 매크로 · 기업분석 · 리스크 — 5개 모듈을 한 화면에서. DART+KIS 실데이터 연동."
        status="LIVE"
      >
        <QuickSearch />
      </PageHeader>

      <MacroStrip />
      <ModuleGrid />
      <TopPicks />
    </div>
  );
}

// ─── 글로벌 종목 검색 (이름/코드 자동완성 → 기업분석) ───────────────────────────
function QuickSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sug, setSug] = useState<{ code: string; name: string }[]>([]);
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(-1);
  const blurT = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const s = q.trim();
    if (!s) { setSug([]); return; }
    const t = setTimeout(() => {
      companyApi.stockSearch(s, 12).then((r) => { setSug(r); setIdx(-1); }).catch(() => setSug([]));
    }, 140);
    return () => clearTimeout(t);
  }, [q]);

  const go = (code: string) => {
    try { sessionStorage.setItem("alpha_company_ticker", code); } catch { /* noop */ }
    setQ(""); setSug([]); setOpen(false);
    router.push("/insights");
  };
  const submit = () => {
    if (idx >= 0 && sug[idx]) return go(sug[idx].code);
    const m = q.match(/\d{6}/); if (m) return go(m[0]);
    if (sug[0]) return go(sug[0].code);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setIdx((i) => Math.min(i + 1, sug.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, -1)); }
    else if (e.key === "Enter") { e.preventDefault(); submit(); }
    else if (e.key === "Escape") setOpen(false);
  };

  return (
    <div className="dash-search">
      <span className="dash-search-ic">⌕</span>
      <input
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onKeyDown={onKey}
        onFocus={() => setOpen(true)}
        onBlur={() => { blurT.current = setTimeout(() => setOpen(false), 150); }}
        placeholder="기업 검색 — 이름 또는 종목코드 (예: 삼성, 005930)"
        autoComplete="off"
      />
      {open && sug.length > 0 && (
        <ul className="dash-sug">
          {sug.map((s, i) => (
            <li key={s.code} className={`dash-sug-item${i === idx ? " on" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); go(s.code); }}
              onMouseEnter={() => setIdx(i)}>
              <span className="dash-sug-name">{s.name}</span>
              <span className="dash-sug-code">{s.code}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ─── 매크로 국면 (실데이터) ────────────────────────────────────────────────────
function MacroStrip() {
  const [st, setSt] = useState<RegimeState | null | undefined>(undefined);
  useEffect(() => { macroApi.regime().then(setSt).catch(() => setSt(null)); }, []);

  if (st === undefined) return <div className="dash-card dash-macro"><div className="dash-skel" style={{ height: 92 }} /></div>;
  if (!st) return <Link href="/macro" className="dash-card dash-macro dash-macro-empty">매크로 데이터 로드 실패 — 매크로 모듈 열기 →</Link>;

  const rc = REGIME_COLORS[st.regime];
  const modeColor = st.recommended_mode === "DEFENSIVE" ? "var(--color-bear)" : st.recommended_mode === "CAUTIOUS" ? "var(--color-caution)" : "var(--color-bull)";
  const stress = st.stress_score;
  const stat = (label: string, value: string, suffix = "", color = "var(--t-ink)") => (
    <div className="dash-macro-stat"><div className="dash-macro-k">{label}</div><div className="dash-macro-v" style={{ color }}>{value}<i>{suffix}</i></div></div>
  );

  return (
    <Link href="/macro" className="dash-card dash-macro" style={{ borderTop: `2px solid ${modeColor}` }}>
      <div className="dash-macro-head">
        <span className="dash-macro-title">◴ 매크로 국면</span>
        <span className="dash-regime" style={{ background: rc.bg, color: rc.fg, borderColor: rc.border }}>{st.regime}</span>
      </div>
      <div className="dash-macro-grid">
        {stat("권고 모드", st.recommended_mode, "", modeColor)}
        {stat("STRESS INDEX", stress.toFixed(0), " / 100", stress >= 60 ? "var(--color-bear)" : stress >= 40 ? "var(--color-caution)" : "var(--color-bull)")}
        {stat("RISK-FREE (10Y)", st.dynamic_risk_free_rate != null ? (st.dynamic_risk_free_rate * 100).toFixed(2) : "—", "%")}
        {stat("YIELD CURVE", st.yield_inversion ? "역전" : "정상", st.inversion_severity != null ? ` ${st.inversion_severity.toFixed(0)}bp` : "", st.yield_inversion ? "var(--color-bear)" : "var(--color-bull)")}
      </div>
      <div className="dash-macro-foot"><span style={{ color: rc.fg }}>{st.description}</span><span className="dash-arrow">→</span></div>
    </Link>
  );
}

// ─── 모듈 그리드 (5 툴) + 데이터 적재 현황 ───────────────────────────────────────
function ModuleGrid() {
  const [rows, setRows] = useState<number | null>(null);
  useEffect(() => {
    fetch(`${API_BASE}/api/v1/screener/snapshot-status`).then((r) => r.ok ? r.json() : null)
      .then((d) => setRows(d?.db_rows ?? null)).catch(() => setRows(null));
  }, []);
  return (
    <div className="dash-modgrid">
      {MODULES.map((m) => (
        <Link key={m.href} href={m.href} className="dash-card dash-mod">
          <div className="dash-mod-top"><span className="dash-mod-n">{m.n}</span><span className="dash-arrow">→</span></div>
          <div className="dash-mod-label">{m.label}</div>
          <div className="dash-mod-desc">{m.desc}</div>
        </Link>
      ))}
      <div className="dash-card dash-mod dash-mod-stat">
        <div className="dash-mod-top"><span className="dash-mod-n">◆</span></div>
        <div className="dash-mod-label">데이터 적재</div>
        <div className="dash-mod-bignum">{rows == null ? "—" : rows.toLocaleString()}</div>
        <div className="dash-mod-desc">factor_snapshot 행 (펀더멘털+가격)</div>
      </div>
    </div>
  );
}

// ─── 스크리너 저평가 Top (실데이터) ─────────────────────────────────────────────
function TopPicks() {
  const [items, setItems] = useState<ScreenerItem[] | null>(null);
  useEffect(() => {
    screenerApiAdvanced.runAdvanced({
      universe: "kospi200",
      filter_ast: { logic: "AND", conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }], groups: [] },
      sort_by: "composite_score", ascending: false, limit: 8, liquidity_floor: "relaxed",
    }).then((r) => setItems(r.items)).catch(() => setItems([]));
  }, []);

  return (
    <div className="dash-card dash-picks">
      <div className="dash-picks-head">
        <span className="dash-macro-title">◇ 스크리너 — 종합점수 Top</span>
        <Link href="/screener" className="dash-picks-more">전체 스크리너 →</Link>
      </div>
      {items == null ? <div className="dash-skel" style={{ height: 180 }} />
        : items.length === 0 ? <EmptyState label="데이터 적재 후 표시됩니다" sub="스크리너 스냅샷이 쌓이면 자동 표시됩니다" />
          : (
            <table className="dash-picks-table">
              <thead><tr><th>#</th><th>종목</th><th className="num">현재가</th><th className="num">PER</th><th className="num">ROE</th><th className="num">종합점수</th><th>판정</th></tr></thead>
              <tbody>
                {items.map((it, i) => {
                  const v = it.verdict || "";
                  const vc = v.includes("저평가") ? "var(--color-bull)" : v.includes("고평가") ? "var(--color-bear)" : "var(--t-muted)";
                  const num = (x: unknown) => typeof x === "number" ? x : null;
                  return (
                    <tr key={it.stock_code} onClick={() => { try { sessionStorage.setItem("alpha_company_ticker", it.stock_code); } catch { /* noop */ } window.location.href = "/insights"; }}>
                      <td className="dash-rank">{i + 1}</td>
                      <td className="dash-nm"><b>{it.corp_name}</b> <span className="dash-cd">{it.stock_code}</span></td>
                      <td className="num">{num(it.current_price)?.toLocaleString() ?? "—"}</td>
                      <td className="num">{num(it.per)?.toFixed(1) ?? "—"}</td>
                      <td className="num">{num(it.roe_pct)?.toFixed(1) ?? "—"}{num(it.roe_pct) != null ? "%" : ""}</td>
                      <td className="num"><b>{num(it.composite_score)?.toFixed(1) ?? "—"}</b></td>
                      <td><span className="dash-verdict" style={{ color: vc }}>{v || "—"}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
    </div>
  );
}
