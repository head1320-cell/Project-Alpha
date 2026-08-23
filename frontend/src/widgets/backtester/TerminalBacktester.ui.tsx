"use client";
// TerminalBacktester 표시 전용 컴포넌트 — 전부 props만 받는다(부모 상태 클로저 없음).
// JSX는 한 줄도 바꾸지 않고 그대로 옮겼다 — 클래스명이 E2E 계약이므로.
// (TerminalBacktester.tsx에서 분리)

import { useEffect, useMemo, useState } from "react";
import type {
  BacktestStatistics, BacktestTrade, MonthlyReturn, SymbolPerf,
} from "@/entities/backtest/bridgeModel";


// 자산 곡선 SVG
export function EquityChart({ curve, benchmark }: { curve: number[]; benchmark?: number[] }) {
  if (!curve || curve.length < 2) {
    return <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 11 }}>NO_DATA</div>;
  }
  const W = 1000, H = 240;
  // 전략·벤치마크 공통 스케일 (둘 다 같은 축에서 비교)
  const hasBench = benchmark && benchmark.length >= 2;
  const allVals = hasBench ? [...curve, ...benchmark!] : curve;
  const min = Math.min(...allVals), max = Math.max(...allVals);
  const range = max - min || 1;
  const toPts = (arr: number[]) => arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const pts = toPts(curve);
  const up = curve[curve.length - 1] >= curve[0];
  const color = up ? "#16a34a" : "#dc2626";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 240, borderBottom: "1px solid var(--t-border)", borderLeft: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polygon points={`0,${H} ${pts} ${W},${H}`} fill={color} opacity="0.06" />
      {hasBench && (
        <polyline points={toPts(benchmark!)} fill="none" stroke="#71717a" strokeWidth="1.5" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" opacity="0.8" />
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// 낙폭 곡선 (0 이하 음수 영역)
export function DrawdownChart({ curve }: { curve: number[] }) {
  if (!curve || curve.length < 2) {
    return <div style={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 11 }}>NO_DATA</div>;
  }
  // drawdown_curve는 음수(%) 또는 비율. 절대값 최대로 정규화
  const W = 1000, H = 140;
  const vals = curve.map((v) => (v > 0 ? -v : v)); // 양수로 들어오면 음수화
  const minV = Math.min(...vals, 0);
  const range = Math.abs(minV) || 1;
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * W;
    const y = (Math.abs(v) / range) * H; // 위에서 아래로 (0=top)
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 140, borderTop: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polygon points={`0,0 ${pts} ${W},0`} fill="#dc2626" opacity="0.08" />
      <polyline points={pts} fill="none" stroke="#dc2626" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// 월별 수익률 히트맵
export function MonthlyHeatmap({ data }: { data: Array<MonthlyReturn | number> }) {
  // data가 숫자 배열이거나 {month, return_pct} 배열 둘 다 지원
  const cells = data.map((d, i) => {
    if (typeof d === "number") return { label: `M${i + 1}`, val: d };
    return { label: d.month || `M${i + 1}`, val: d.return_pct ?? 0 };
  });
  const maxAbs = Math.max(...cells.map((c) => Math.abs(c.val)), 1);
  const colorFor = (v: number) => {
    const intensity = Math.min(1, Math.abs(v) / maxAbs);
    if (v >= 0) return `rgba(22, 163, 74, ${0.15 + intensity * 0.6})`;
    return `rgba(220, 38, 38, ${0.15 + intensity * 0.6})`;
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(64px, 1fr))", gap: 4 }}>
      {cells.map((c, i) => (
        <div key={i} style={{ padding: "10px 4px", borderRadius: 2, background: colorFor(c.val), textAlign: "center" }}>
          <div style={{ fontFamily: "var(--t-mono)", fontSize: 9, color: "var(--t-muted)", marginBottom: 2 }}>{c.label}</div>
          <div style={{ fontFamily: "var(--t-mono)", fontSize: 12, fontWeight: 600, color: c.val >= 0 ? "#15803d" : "#b91c1c" }}>
            {c.val >= 0 ? "+" : ""}{c.val.toFixed(1)}
          </div>
        </div>
      ))}
    </div>
  );
}

// 전체 성과지표 — QuantStats 티어시트식 그룹 표 (헤드라인 6카드 보강)
export function MetricsTearsheet({ st }: { st: BacktestStatistics }) {
  const has = (x: number | null | undefined): x is number => x !== null && x !== undefined;
  const pct = (x: number | null | undefined, dp = 2) => (has(x) ? `${x.toFixed(dp)}%` : "—");
  const num = (x: number | null | undefined, dp = 2) => (has(x) ? x.toFixed(dp) : "—");
  const won = (x: number | null | undefined) => (has(x) ? `₩${Math.round(x).toLocaleString()}` : "—");
  const days = (x: number | null | undefined) => (has(x) ? `${Math.round(x)}일` : "—");
  const RED = "#dc2626", GREEN = "#16a34a";

  type Row = { label: string; value: string; hint?: string; color?: string };
  const groups: { title: string; rows: Row[] }[] = [
    {
      title: "위험 · Risk",
      rows: [
        { label: "연변동성", value: pct(st.volatility_pct), hint: "Volatility (ann.)" },
        { label: "하방변동성", value: pct(st.downside_deviation_pct), hint: "Downside deviation" },
        { label: "VaR 95%", value: pct(st.var_pct), hint: "1기간 하위 5% 손실", color: has(st.var_pct) ? RED : undefined },
        { label: "CVaR 95%", value: pct(st.cvar_pct), hint: "꼬리손실 평균", color: has(st.cvar_pct) ? RED : undefined },
        { label: "Ulcer Index", value: num(st.ulcer_index), hint: "낙폭 깊이·지속" },
        { label: "평균낙폭", value: pct(st.avg_drawdown_pct), hint: "Avg drawdown", color: has(st.avg_drawdown_pct) ? RED : undefined },
        { label: "최장 수중기간", value: days(st.max_drawdown_days), hint: "Max DD duration" },
      ],
    },
    {
      title: "위험조정 · Risk-Adjusted",
      rows: [
        { label: "Omega", value: num(st.omega, 3), hint: "이익합/손실합" },
        { label: "Gain-to-Pain", value: num(st.gain_to_pain, 3), hint: "순수익/총손실" },
        { label: "Recovery Factor", value: num(st.recovery_factor, 3), hint: "총수익/최대낙폭" },
        { label: "Tail Ratio", value: num(st.tail_ratio, 3), hint: "우측/좌측 꼬리" },
        { label: "Information Ratio", value: num(st.information_ratio, 3), hint: "벤치 초과/추적오차" },
      ],
    },
    {
      title: "분포 · Distribution",
      rows: [
        { label: "왜도 Skew", value: num(st.skew, 3), hint: "수익분포 비대칭" },
        { label: "첨도 Kurtosis", value: num(st.kurtosis, 3), hint: "초과첨도(정규=0)" },
        { label: "최고 기간수익", value: pct(st.best_period_pct), color: has(st.best_period_pct) ? GREEN : undefined },
        { label: "최저 기간수익", value: pct(st.worst_period_pct), color: has(st.worst_period_pct) ? RED : undefined },
      ],
    },
    {
      title: "거래 · Trades",
      rows: [
        { label: "손익비 Payoff", value: num(st.payoff_ratio), hint: "평균이익/평균손실" },
        { label: "기대값 Expectancy", value: won(st.expectancy), hint: "거래당 기대손익", color: has(st.expectancy) ? (st.expectancy! >= 0 ? GREEN : RED) : undefined },
        { label: "평균이익", value: won(st.avg_win), color: has(st.avg_win) ? GREEN : undefined },
        { label: "평균손실", value: won(st.avg_loss), color: has(st.avg_loss) ? RED : undefined },
        { label: "Kelly 비중", value: pct(st.kelly_pct), hint: "최적 베팅비율" },
      ],
    },
  ];
  // 값이 전부 "—"인 그룹은 숨김(엔진모드/무거래 시 거래 그룹 자동 제거)
  const visible = groups.filter((g) => g.rows.some((r) => r.value !== "—"));
  if (visible.length === 0) return null;

  return (
    <div className="tbt-chart">
      <div className="tbt-chart-head">
        <div className="tbt-chart-title">전체 성과지표</div>
        <div className="tbt-chart-title" style={{ color: "var(--t-muted)" }}>QuantStats 표준</div>
      </div>
      <div className="tbt-tearsheet">
        {visible.map((g) => (
          <div key={g.title} className="tbt-ts-group">
            <div className="tbt-ts-gtitle">{g.title}</div>
            {g.rows.map((r) => (
              <div key={r.label} className="tbt-ts-row" title={r.hint || ""}>
                <span className="tbt-ts-label">{r.label}</span>
                <span className="tbt-ts-value" style={r.color && r.value !== "—" ? { color: r.color } : undefined}>{r.value}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// 종목별 성과 테이블 — 실현손익/평균수익률/보유일/기여도, 행 클릭 → 개별 거래 상세
// 거래내역 — "종목별 요약"(구 Constituents: 종목당 집계 + 행 클릭 상세)과 "전체 거래내역"
// (구 Trade Log의 상위호환: 모든 라운드트립을 종목 구분 없이 최신순 나열, 수량/손익/사유/
// 보유일수 포함) 두 뷰를 토글. 두 뷰 모두 같은 rows/roundTrips를 공유 — 데이터 손실 없음.
export function SymbolPerfTable({ rows, roundTrips, screened }: {
  rows: SymbolPerf[];
  roundTrips: BacktestTrade[];
  screened: Array<{ stock_code: string; corp_name: string }>;
}) {
  const [view, setView] = useState<"summary" | "flat">("summary");
  const [sortKey, setSortKey] = useState<string>("contribution_pct");
  const [desc, setDesc] = useState(true);
  const [tradedOnly, setTradedOnly] = useState(true);
  const [page, setPage] = useState(0);
  const [openSym, setOpenSym] = useState<string | null>(null);
  const PER_PAGE = 20;

  const sorted = useMemo(() => {
    const base = tradedOnly ? rows.filter((r) => (r.round_trips ?? 0) > 0) : [...rows];
    base.sort((a, b) => {
      const av = ((a as unknown as Record<string, unknown>)[sortKey] as number) ?? -Infinity;
      const bv = ((b as unknown as Record<string, unknown>)[sortKey] as number) ?? -Infinity;
      return desc ? bv - av : av - bv;
    });
    return base;
  }, [rows, sortKey, desc, tradedOnly]);

  // 전체 거래내역(플랫) — 청산일 기준 최신순, 청산일 없으면 진입일 기준
  const flatTrades = useMemo(() => {
    const dateOf = (t: BacktestTrade) => t.exit_date || t.entry_date || "";
    return [...roundTrips].sort((a, b) => dateOf(b).localeCompare(dateOf(a)));
  }, [roundTrips]);

  useEffect(() => { setPage(0); }, [sortKey, desc, tradedOnly, rows, view]);

  const won = (v: number | undefined) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}₩${Math.abs(Math.round(v)).toLocaleString()}`);
  const pct = (v: number | undefined, dp = 2) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`);
  const col = (v: number | undefined) => ((v ?? 0) >= 0 ? "#16a34a" : "#dc2626");
  const daysOf = (t: BacktestTrade) => {
    try {
      if (!t.entry_date || !t.exit_date) return "—";
      const d = Math.round((new Date(t.exit_date).getTime() - new Date(t.entry_date).getTime()) / 864e5);
      return `${Math.max(0, d)}일`;
    } catch { return "—"; }
  };
  const tradeRow = (t: BacktestTrade, i: number | string) => (
    <tr key={i}>
      <td>{t.corp_name || t.stock_code || "—"}</td>
      <td>{t.entry_date || "—"}</td>
      <td>{t.exit_date || "—"}</td>
      <td className="num">{t.entry_price?.toLocaleString() ?? "—"}</td>
      <td className="num">{t.exit_price?.toLocaleString() ?? "—"}</td>
      <td className="num">{t.quantity?.toLocaleString() ?? "—"}</td>
      <td className="num" style={{ color: col(t.return_pct), fontWeight: 600 }}>{pct(t.return_pct)}</td>
      <td className="num" style={{ color: col(t.pnl) }}>{won(t.pnl)}</td>
      <td>{daysOf(t)}</td>
      <td style={{ color: "var(--t-muted)", fontSize: 11 }}>{t.reason || "—"}</td>
    </tr>
  );

  const viewToggle = (
    <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
      {([["summary", "종목별 요약"], ["flat", "전체 거래내역"]] as const).map(([id, label]) => (
        <button key={id} type="button" onClick={() => setView(id)}
          className="tbt-export-btn" aria-pressed={view === id}
          style={view === id ? { borderColor: "var(--t-accent)", color: "var(--t-accent)" } : undefined}>
          {label}
        </button>
      ))}
    </div>
  );

  // 구버전/엔진모드 응답(symbol_results 없음) → 기존 칩 폴백 (요약 뷰만 해당, 플랫 뷰는 그대로 동작)
  if (!rows.length && view === "summary") {
    return (
      <div>
        {viewToggle}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {screened.slice(0, 12).map((t) => (
            <span key={t.stock_code} style={{ fontFamily: "var(--t-mono)", fontSize: 12, padding: "4px 10px", border: "1px solid var(--t-border)", borderRadius: 2 }}>
              {t.corp_name || t.stock_code}
            </span>
          ))}
        </div>
      </div>
    );
  }

  if (view === "flat") {
    const pageCount = Math.max(1, Math.ceil(flatTrades.length / PER_PAGE));
    const cur = Math.min(page, pageCount - 1);
    const pageRows = flatTrades.slice(cur * PER_PAGE, (cur + 1) * PER_PAGE);
    return (
      <div>
        {viewToggle}
        {flatTrades.length === 0 ? (
          <span style={{ fontSize: 12, color: "var(--t-muted)" }}>거래 내역 없음</span>
        ) : (
          <>
            <table className="tbt-tradelog">
              <thead>
                <tr><th>종목</th><th>진입일</th><th>청산일</th><th className="num">진입가</th><th className="num">청산가</th><th className="num">수량</th><th className="num">수익률</th><th className="num">손익</th><th>보유</th><th>사유</th></tr>
              </thead>
              <tbody>
                {pageRows.map((t, i) => tradeRow(t, i))}
              </tbody>
            </table>
            {pageCount > 1 && (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, padding: "10px 0 2px", fontFamily: "var(--t-mono)", fontSize: 12 }}>
                <button className="tbt-export-btn" onClick={() => setPage(Math.max(0, cur - 1))} disabled={cur === 0}>◀ 이전</button>
                <span>{cur + 1} / {pageCount}</span>
                <button className="tbt-export-btn" onClick={() => setPage(Math.min(pageCount - 1, cur + 1))} disabled={cur >= pageCount - 1}>다음 ▶</button>
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  const pageCount = Math.max(1, Math.ceil(sorted.length / PER_PAGE));
  const cur = Math.min(page, pageCount - 1);
  const pageRows = sorted.slice(cur * PER_PAGE, (cur + 1) * PER_PAGE);
  const head = (key: string, label: string) => (
    <th className="num" style={{ cursor: "pointer" }} onClick={() => { if (sortKey === key) setDesc(!desc); else { setSortKey(key); setDesc(true); } }}>
      {label}{sortKey === key ? (desc ? " ▼" : " ▲") : ""}
    </th>
  );

  return (
    <div>
      {viewToggle}
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8, fontSize: 12, color: "var(--t-muted)" }}>
        <label style={{ display: "inline-flex", alignItems: "center", gap: 5, cursor: "pointer" }}>
          <input type="checkbox" checked={tradedOnly} onChange={(e) => setTradedOnly(e.target.checked)} style={{ accentColor: "var(--t-accent)" }} />
          거래 발생 종목만 ({rows.filter((r) => (r.round_trips ?? 0) > 0).length}/{rows.length})
        </label>
        <span style={{ marginLeft: "auto", fontFamily: "var(--t-mono)", fontSize: 11 }}>
          행 클릭 → 개별 거래 상세
        </span>
      </div>
      <table className="tbt-tradelog">
        <thead>
          <tr>
            <th>종목</th>
            {head("round_trips", "거래")}
            {head("win_rate", "승률")}
            {head("realized_pnl", "실현손익")}
            {head("avg_return_pct", "평균수익률")}
            {head("avg_hold_days", "평균보유")}
            {head("contribution_pct", "기여도")}
          </tr>
        </thead>
        <tbody>
          {pageRows.map((r) => {
            const open = openSym === r.symbol;
            const trs = open ? roundTrips.filter((t) => t.stock_code === r.symbol) : [];
            return [
              <tr key={r.symbol} onClick={() => setOpenSym(open ? null : r.symbol)} style={{ cursor: "pointer", background: open ? "var(--t-surface)" : undefined }}>
                <td>{r.corp_name || r.symbol} <span style={{ color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 10 }}>{r.symbol}</span></td>
                <td className="num">{r.round_trips ?? 0}회</td>
                <td className="num">{(r.win_rate ?? 0).toFixed(0)}%</td>
                <td className="num" style={{ color: col(r.realized_pnl), fontWeight: 600 }}>{won(r.realized_pnl)}</td>
                <td className="num" style={{ color: col(r.avg_return_pct) }}>{pct(r.avg_return_pct)}</td>
                <td className="num">{r.avg_hold_days != null ? `${r.avg_hold_days}일` : "—"}</td>
                <td className="num">{r.contribution_pct != null ? `${r.contribution_pct}%` : "—"}</td>
              </tr>,
              open && (
                <tr key={`${r.symbol}-detail`}>
                  <td colSpan={7} style={{ padding: "6px 10px 12px", background: "var(--t-surface)" }}>
                    {trs.length === 0
                      ? <span style={{ fontSize: 12, color: "var(--t-muted)" }}>표시 가능한 개별 거래 없음 (거래 로그 500건 초과분은 생략될 수 있음)</span>
                      : (
                        <table className="tbt-tradelog" style={{ margin: 0 }}>
                          <thead>
                            <tr><th>진입일</th><th>청산일</th><th className="num">진입가</th><th className="num">청산가</th><th className="num">수량</th><th className="num">수익률</th><th className="num">손익</th><th>보유</th><th>사유</th></tr>
                          </thead>
                          <tbody>
                            {trs.map((t, i) => (
                              <tr key={i}>
                                <td>{t.entry_date || "—"}</td>
                                <td>{t.exit_date || "—"}</td>
                                <td className="num">{t.entry_price?.toLocaleString() ?? "—"}</td>
                                <td className="num">{t.exit_price?.toLocaleString() ?? "—"}</td>
                                <td className="num">{t.quantity?.toLocaleString() ?? "—"}</td>
                                <td className="num" style={{ color: col(t.return_pct), fontWeight: 600 }}>{pct(t.return_pct)}</td>
                                <td className="num" style={{ color: col(t.pnl) }}>{won(t.pnl)}</td>
                                <td>{daysOf(t)}</td>
                                <td style={{ color: "var(--t-muted)", fontSize: 11 }}>{t.reason || "—"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                  </td>
                </tr>
              ),
            ];
          })}
        </tbody>
      </table>
      {pageCount > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, padding: "10px 0 2px", fontFamily: "var(--t-mono)", fontSize: 12 }}>
          <button className="tbt-export-btn" onClick={() => setPage(Math.max(0, cur - 1))} disabled={cur === 0}>◀ 이전</button>
          <span>{cur + 1} / {pageCount}</span>
          <button className="tbt-export-btn" onClick={() => setPage(Math.min(pageCount - 1, cur + 1))} disabled={cur >= pageCount - 1}>다음 ▶</button>
        </div>
      )}
    </div>
  );
}

// 백테스트 진행 단계 — 백엔드 스트림의 실제 진행률(phase/done/total)로 구동.
// 가장 긴 "시세 데이터 로드" 단계는 종목 k/total·% 를 실시간 표시 → 빈 화면/체감 대기 제거.
export function BacktestProgress({ progress }: {
  progress: { phase: string; done?: number; total?: number; count?: number } | null;
}) {
  const stages = [
    { keys: ["screening", "screened"], label: "종목 스크리닝" },
    { keys: ["loading"], label: "과거 시세 데이터 로드" },
    { keys: ["simulating", "done"], label: "포지션 시뮬레이션·성과 집계" },
  ];
  const phase = progress?.phase ?? "screening";
  const foundIdx = stages.findIndex((s) => s.keys.includes(phase));
  const activeIdx = foundIdx < 0 ? 0 : foundIdx;
  const pct = progress?.total ? Math.round(((progress.done ?? 0) / progress.total) * 100) : 0;
  return (
    <div className="tbt-stages">
      {stages.map((s, i) => {
        const cls = i < activeIdx ? " done" : i === activeIdx ? " active" : "";
        const showCount = i === activeIdx
          && (phase === "loading" || phase === "screening" || phase === "simulating")
          && !!progress?.total;
        return (
          <div key={i} className={`tbt-stage${cls}`}>
            <span className="tbt-stage-dot">{i < activeIdx ? "✓" : i + 1}</span>
            <span className="tbt-stage-label">
              {s.label}
              {showCount ? ` — ${progress?.done ?? 0}/${progress?.total} 종목 (${pct}%)` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

