"use client";

import { useCallback, useEffect, useState } from "react";

import PageHeader from "@/components/layout/PageHeader";
import SectionHead from "@/components/layout/SectionHead";
import { ErrorState, LoadingState } from "@/components/layout/States";
import { api } from "@/lib/api";

type DbStatus = Awaited<ReturnType<typeof api.dbStatus>>;
type Cell = number | string | null;

const TABLE_LABELS: Record<string, string> = {
  daily_prices: "일봉 (주식)",
  index_kospi_kosdaq: "지수 (KOSPI/KOSDAQ)",
  etf_cross_asset: "크로스에셋 ETF",
  investor_flows: "투자자 수급",
  factor_snapshot: "펀더멘털 스냅샷",
  financials_history: "재무 시계열 (PIT)",
};

const INGEST_TARGETS: [string, string][] = [
  ["index", "지수"], ["etf", "ETF"], ["stocks", "주식 일봉"],
  ["factors", "펀더멘털"], ["financials", "재무시계열"], ["flows", "수급(KIS)"],
];

const fmtNum = (v: Cell | undefined) =>
  typeof v === "number" ? v.toLocaleString() : v == null ? "—" : String(v);

function period(t: Record<string, Cell>): string {
  const s = t.start, e = t.end;
  return s || e ? `${s ?? "—"} ~ ${e ?? "—"}` : "—";
}

export default function DbStatusPanel() {
  const [st, setSt] = useState<DbStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setSt(await api.dbStatus());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 적재 실행 중이면 폴링
  const anyRunning = !!(st?.ingest_running && Object.values(st.ingest_running).some(Boolean));
  useEffect(() => {
    if (!anyRunning) return;
    const id = setInterval(() => void load(), 5000);
    return () => clearInterval(id);
  }, [anyRunning, load]);

  const trigger = async (target: string) => {
    setMsg(null);
    try {
      setMsg((await api.ingest(target)).message);
      void load();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    }
  };

  const toolsReady = st ? Object.values(st.tools).filter(Boolean).length : 0;
  const toolsTotal = st ? Object.keys(st.tools).length : 0;

  return (
    <div className="tpage-fade">
      <PageHeader
        eyebrow="DATA / INFRASTRUCTURE"
        index="06 / 06"
        title="Data Infrastructure Status"
        intro="모든 도구가 쓰는 핵심 테이블의 적재 현황(행수·종목·기간)을 한 화면에서 점검하고, 부족분을 직접 적재합니다."
        status={st?.config?.kis_real ? "MODE: REAL" : "MODE: MOCK"}
      >
        <button className="tchip-toggle" onClick={() => void load()} disabled={loading}>
          {loading ? "조회 중…" : "↻ 새로고침"}
        </button>
      </PageHeader>

      {loading && !st && <LoadingState label="DB 적재 현황을 점검하는 중" />}
      {err && !st && <ErrorState label="DB 상태 조회 실패" sub={err} />}

      {st && (
        <div className="animate-fade-in">
          {/* 데이터 소스 키 */}
          <SectionHead label="DATA SOURCES" index="KEYS" />
          <div className="tscenario-bar">
            {Object.entries(st.config).map(([k, v]) => (
              <span key={k} className={`tchip-toggle${v ? " active" : ""}`} style={{ cursor: "default" }}>
                {v ? "● " : "○ "}
                {k}
              </span>
            ))}
          </div>

          {/* 도구별 준비상태 */}
          <SectionHead label="TOOL READINESS" index={`${toolsReady} / ${toolsTotal}`} />
          <div className="tscenario-bar">
            {Object.entries(st.tools).map(([k, ok]) => (
              <span
                key={k}
                className="tchip-toggle"
                style={{ cursor: "default", color: ok ? "var(--color-bull)" : "var(--color-bear)" }}
              >
                {ok ? "✓ " : "✗ "}
                {k}
              </span>
            ))}
          </div>

          {/* 테이블 적재 현황 */}
          <SectionHead label="TABLE COVERAGE" index="ROWS · TICKERS · PERIOD" />
          <table className="trisk-table">
            <thead>
              <tr>
                <th>테이블</th>
                <th className="num">행수</th>
                <th className="num">종목</th>
                <th>기간 (최초 ~ 최근)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(st.tables).map(([key, t]) => {
                const cells = t as Record<string, Cell>;
                const rows = cells.rows ?? cells.loaded;
                return (
                  <tr key={key}>
                    <td>{TABLE_LABELS[key] ?? key}</td>
                    <td className="num" style={{ fontFamily: "var(--t-mono)" }}>
                      {fmtNum(rows)}
                      {cells.total != null ? ` / ${fmtNum(cells.total)}` : ""}
                    </td>
                    <td className="num" style={{ fontFamily: "var(--t-mono)" }}>{fmtNum(cells.tickers)}</td>
                    <td style={{ fontFamily: "var(--t-mono)", color: "var(--t-muted)" }}>{period(cells)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* 유니버스 적재 진행 — 스크리너 유니버스가 마스터(전 상장) 대비 얼마나 채워졌는지 */}
          {st.universe_progress && Object.keys(st.universe_progress.progress ?? {}).length > 0 && (
            <>
              <SectionHead label="UNIVERSE COVERAGE" index="INGESTED / MASTER" />
              <table className="trisk-table">
                <thead>
                  <tr><th>유니버스</th><th className="num">마스터</th><th className="num">적재</th><th className="num">진행률</th></tr>
                </thead>
                <tbody>
                  {(["kospi", "kosdaq", "etf", "all_listed"] as const).map((k) => {
                    const p = st.universe_progress!.progress[k];
                    if (!p) return null;
                    const pct = p.master > 0 ? Math.round((p.ingested / p.master) * 100) : 0;
                    const label = { kospi: "KOSPI", kosdaq: "KOSDAQ", etf: "ETF", all_listed: "전체 (전종목)" }[k];
                    return (
                      <tr key={k}>
                        <td>{label}</td>
                        <td className="num" style={{ fontFamily: "var(--t-mono)" }}>{p.master.toLocaleString()}</td>
                        <td className="num" style={{ fontFamily: "var(--t-mono)" }}>{p.ingested.toLocaleString()}</td>
                        <td className="num" style={{ fontFamily: "var(--t-mono)", color: pct >= 100 ? "#16a34a" : pct >= 50 ? "var(--t-ink)" : "#dc2626" }}>{pct}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}

          {/* 적재 실행 */}
          <SectionHead label="INGEST" index="BACKGROUND" />
          <div className="tscenario-bar">
            {INGEST_TARGETS.map(([target, label]) => (
              <button
                key={target}
                className="tchip-toggle"
                disabled={!!st.ingest_running?.[target]}
                onClick={() => void trigger(target)}
              >
                {st.ingest_running?.[target] ? `${label} 적재 중…` : label}
              </button>
            ))}
            <button className="tchip-toggle active" disabled={anyRunning} onClick={() => void trigger("all")}>
              {anyRunning ? "적재 중…" : "★ 전체 적재"}
            </button>
          </div>
          <p className="tpage-intro" style={{ marginTop: 10 }}>
            키 없는 소스는 자동 건너뜀(no-op) · 진행은 "↻ 새로고침"으로 확인 · 대형 백필은 백그라운드 수 시간.
          </p>
          {msg && (
            <p style={{ marginTop: 8, fontFamily: "var(--t-mono)", fontSize: 12, color: "var(--t-accent)" }}>{msg}</p>
          )}
        </div>
      )}
    </div>
  );
}
