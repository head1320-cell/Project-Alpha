"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

type DbStatus = Awaited<ReturnType<typeof api.dbStatus>>;

const TABLE_LABELS: Record<string, string> = {
  daily_prices: "일봉(주식)",
  index_kospi_kosdaq: "지수(KOSPI/KOSDAQ)",
  etf_cross_asset: "크로스에셋 ETF",
  investor_flows: "투자자 수급",
  factor_snapshot: "펀더멘털 스냅샷",
  financials_history: "재무 시계열(PIT)",
};

export default function DbStatusPanel() {
  const [st, setSt] = useState<DbStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSt(await api.dbStatus());
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 적재 실행 중이면 폴링
  const anyRunning = st?.ingest_running && Object.values(st.ingest_running).some(Boolean);
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

  const fmt = (v: number | string | null | undefined) =>
    v === null || v === undefined ? "—" : typeof v === "number" ? v.toLocaleString() : String(v);

  return (
    <div className="mx-auto max-w-3xl px-6 pt-6 font-mono text-sm text-[#111111]">
      <header className="mb-4 border-b border-[#e5e5e5] pb-3">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold tracking-tight">데이터 인프라 점검 (DB Status)</h1>
          <button
            onClick={() => void load()}
            disabled={loading}
            className="rounded-sm border border-[#e5e5e5] bg-white px-2 py-1 text-xs hover:border-[#1200ff] disabled:opacity-50"
          >
            {loading ? "조회 중…" : "새로고침"}
          </button>
        </div>
        <p className="mt-1 text-xs text-[#71717a]">모든 도구가 쓰는 핵심 테이블 적재 현황을 한 화면에서 — SSH 불필요.</p>
      </header>

      {!st && <p className="text-xs text-[#71717a]">{loading ? "조회 중…" : "데이터 없음"}</p>}

      {st && (
        <>
          {/* 키 설정 */}
          <section className="mb-4 rounded-sm border border-[#e5e5e5] bg-[#fafafa] p-3">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#71717a]">키 / 모드</h2>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {Object.entries(st.config).map(([k, v]) => (
                <span key={k} className={v ? "text-[#111111]" : "text-[#a1a1aa]"}>
                  {v ? "●" : "○"} {k}
                </span>
              ))}
            </div>
          </section>

          {/* 도구별 준비상태 */}
          <section className="mb-4 rounded-sm border border-[#e5e5e5] p-3">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#71717a]">도구별 준비상태</h2>
            <div className="grid grid-cols-2 gap-y-1 sm:grid-cols-3">
              {Object.entries(st.tools).map(([k, ok]) => (
                <span key={k} className="text-xs">
                  <span className={ok ? "text-green-600" : "text-red-600"}>{ok ? "✓" : "✗"}</span> {k}
                </span>
              ))}
            </div>
          </section>

          {/* 테이블 적재 현황 */}
          <section className="mb-4 overflow-hidden rounded-sm border border-[#e5e5e5]">
            <table className="w-full text-xs">
              <thead className="bg-[#fafafa] text-[#71717a]">
                <tr>
                  <th className="px-3 py-1.5 text-left font-medium">테이블</th>
                  <th className="px-3 py-1.5 text-right font-medium">행/종목</th>
                  <th className="px-3 py-1.5 text-right font-medium">상세</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {Object.entries(st.tables).map(([k, v]) => (
                  <tr key={k} className="border-t border-[#f0f0f0]">
                    <td className="px-3 py-1.5">{TABLE_LABELS[k] ?? k}</td>
                    <td className="px-3 py-1.5 text-right">
                      {fmt(v.rows ?? v.loaded)}
                      {v.tickers !== undefined && ` / ${fmt(v.tickers)}`}
                      {v.total !== undefined && ` / ${fmt(v.total)}`}
                    </td>
                    <td className="px-3 py-1.5 text-right text-[#71717a]">
                      {v.start ? `${fmt(v.start)}~${fmt(v.end)}` : v.max_date ? `~${fmt(v.max_date)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* 적재 트리거 — 테이블별 + 전체 */}
          <section className="mb-2 rounded-sm border border-[#e5e5e5] p-3">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#71717a]">적재 실행 (백그라운드)</h2>
            <div className="flex flex-wrap gap-2">
              {([
                ["index", "지수"], ["etf", "ETF"], ["stocks", "주식 일봉"],
                ["factors", "펀더멘털"], ["financials", "재무시계열"], ["flows", "수급(KIS)"],
              ] as const).map(([target, label]) => (
                <button
                  key={target}
                  onClick={() => void trigger(target)}
                  disabled={!!st.ingest_running?.[target]}
                  className="rounded-sm border border-[#1200ff] bg-white px-3 py-1.5 text-xs font-semibold text-[#1200ff] hover:bg-[#f0f0ff] disabled:opacity-50"
                >
                  {st.ingest_running?.[target] ? `${label} 적재 중…` : label}
                </button>
              ))}
              <button
                onClick={() => void trigger("all")}
                disabled={anyRunning}
                className="rounded-sm bg-[#1200ff] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
              >
                {anyRunning ? "적재 중…" : "★ 전체 적재"}
              </button>
            </div>
            <p className="mt-2 text-xs text-[#71717a]">키 없는 소스는 자동 건너뜀(no-op). 진행은 "새로고침"으로 확인.</p>
            {msg && <p className="mt-1 text-xs text-[#1200ff]">{msg}</p>}
          </section>
        </>
      )}
    </div>
  );
}
