"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

type FlowsStatus = Awaited<ReturnType<typeof api.flowsStatus>>;

export default function FlowsAdminPanel() {
  const [status, setStatus] = useState<FlowsStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [start, setStart] = useState("2018-01-01");

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setStatus(await api.flowsStatus());
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 백필 실행 중이면 5초마다 폴링
  useEffect(() => {
    if (!status?.krx_backfill_running) return;
    const id = setInterval(() => void load(), 5000);
    return () => clearInterval(id);
  }, [status?.krx_backfill_running, load]);

  const runBackfill = async () => {
    setMsg(null);
    setErr(null);
    try {
      const r = await api.backfillFlowsKrx(start, true);
      setMsg(r.message);
      void load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const running = status?.krx_backfill_running;

  return (
    <div className="mx-auto max-w-3xl p-6 font-mono text-sm text-[#111111]">
      <header className="mb-6 border-b border-[#e5e5e5] pb-3">
        <h1 className="text-lg font-semibold tracking-tight">투자자 수급 데이터 (Investor Flows)</h1>
        <p className="mt-1 text-xs text-[#71717a]">
          외국인·기관·개인 일별 순매수 적재 현황 + KRX MDC 과거 확정치 백필 (KIS ~30영업일 제한 보완).
        </p>
      </header>

      {/* 적재 현황 */}
      <section className="mb-6 rounded-sm border border-[#e5e5e5] bg-[#fafafa] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[#71717a]">적재 현황</h2>
          <button
            onClick={() => void load()}
            disabled={loading}
            className="rounded-sm border border-[#e5e5e5] bg-white px-2 py-1 text-xs hover:border-[#1200ff] disabled:opacity-50"
          >
            {loading ? "조회 중…" : "새로고침"}
          </button>
        </div>
        {status ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
            <Stat label="총 행수" value={status.rows.toLocaleString()} />
            <Stat label="종목 수" value={status.tickers.toLocaleString()} />
            <Stat label="세부주체" value={status.has_detail ? "있음 (KRX)" : "없음"} />
            <Stat label="최초 일자" value={status.min_date ?? "—"} />
            <Stat label="최근 일자" value={status.max_date ?? "—"} />
            <Stat label="백필 상태" value={running ? "실행 중…" : "대기"} />
          </dl>
        ) : (
          <p className="text-xs text-[#71717a]">{loading ? "조회 중…" : "데이터 없음"}</p>
        )}
        {status && status.rows === 0 && (
          <p className="mt-3 text-xs text-[#71717a]">
            적재된 수급 데이터가 없습니다. 일별 누적은 KIS(서버 자동), 과거 백필은 아래 KRX 백필을 실행하세요.
          </p>
        )}
      </section>

      {/* KRX 과거 백필 */}
      <section className="rounded-sm border border-[#e5e5e5] p-4">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[#71717a]">
          KRX MDC 과거 수급 백필
        </h2>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[#71717a]">시작일</span>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className="rounded-sm border border-[#e5e5e5] bg-white px-2 py-1 text-sm"
            />
          </label>
          <button
            onClick={() => void runBackfill()}
            disabled={running}
            className="rounded-sm bg-[#1200ff] px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
          >
            {running ? "백필 실행 중…" : "전종목 백필 시작"}
          </button>
        </div>
        <p className="mt-3 text-xs text-[#71717a]">
          ⚠ 비공식 KRX 엔드포인트 · 실데이터 모드(서버)에서만 동작 · 전종목 ~1.5시간(백그라운드).
        </p>
        {msg && <p className="mt-2 text-xs text-[#1200ff]">{msg}</p>}
        {err && <p className="mt-2 text-xs text-red-600">오류: {err}</p>}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-[#71717a]">{label}</dt>
      <dd className="mt-0.5 tabular-nums">{value}</dd>
    </div>
  );
}
