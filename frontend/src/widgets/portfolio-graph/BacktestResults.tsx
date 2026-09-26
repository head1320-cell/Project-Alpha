"use client";
/**
 * 백테스트 웨이브의 결과 (BL3 W1) — 설정 요약 · 진행 카드 · 결과(곡선·지표) · 매크로 팩터 귀인 · 두 실행 비교
 * ==========================================================================
 * 시작은 버튼, 읽기는 노드다. 진행 중인 실행은 노드가 '아직 끝나지 않았어요' 로 실패하고, 이 화면이 그 실행의 상태를
 * **읽기만**(GET) 3초마다 확인한다 — 끝나면 '결과 불러오기' 버튼이 밝아진다. 이 웨이브에서 움직이는 것은 이 카드 하나다.
 */
import { useEffect, useState, type ReactNode } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";
import { backtestRunApi, STAGE_LABELS, TERMINAL, type RunStatusLite } from "@/entities/backtest-run";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt = (v: unknown, d = 2, unit = "") => (num(v) === null ? "—" : `${(v as number).toFixed(d)}${unit}`);
const signed = (v: unknown, d = 2, unit = "") =>
  (num(v) === null ? "—" : `${(v as number) >= 0 ? "+" : "−"}${Math.abs(v as number).toFixed(d)}${unit}`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

// ── 설정 ─────────────────────────────────────────────────────────────────────

export function BacktestSetupResult({ v }: { v: Dict }) {
  const c = (v.config as Dict) ?? {};
  return (
    <>
      <KV rows={[
        ["후보 범위", String(v.universe_label ?? c.universe ?? "—")],
        ["규칙", String(v.strategy_label ?? c.strategy_name ?? "—")],
        ["기간", `${String(c.start_date)} ~ ${String(c.end_date)}`],
        ["종목 · 동시 보유", `${String(c.max_tickers)}개 · ${String(c.max_positions)}개`],
        ["비용", `수수료 ${fmt((num(c.commission_rate) ?? 0) * 100)}% · 슬리피지 ${fmt((num(c.slippage_rate) ?? 0) * 100)}%${c.charge_sell_tax ? " · 매도세" : ""}`],
      ]} />
      <p className="pg-note">아직 돌리지 않았어요 — 설정 탭의 ‘백테스트 시작’을 누르면 백그라운드에서 돌아요.</p>
    </>
  );
}

// ── 진행 카드 (노드가 '아직' 으로 실패했을 때) ───────────────────────────────

export function RunProgress({ runId, onReload }: { runId: string; onReload: () => void }) {
  const [st, setSt] = useState<RunStatusLite | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const tick = async () => {
      try {
        const s = await backtestRunApi.status(runId);
        if (!live) return;
        setSt(s); setErr(null);
        if (!TERMINAL.includes(s.status)) timer = setTimeout(tick, 3000);
      } catch (e) {
        if (!live) return;
        setErr((e as Error).message);
        timer = setTimeout(tick, 6000);                                   // 일시 장애면 천천히 다시
      }
    };
    void tick();
    return () => { live = false; if (timer) clearTimeout(timer); };
  }, [runId]);
  const done = st?.status === "completed";
  const ended = st ? TERMINAL.includes(st.status) && !done : false;
  const pct = Math.max(0, Math.min(100, st?.progress_percent ?? 0));
  return (
    <div className={`pg-runprog${done ? " pg-runprog--done" : ""}`} data-run={runId} role="status" aria-live="polite">
      <div className="pg-runprog-head">
        <b>{done ? "백테스트가 끝났어요" : ended ? `백테스트가 ${STAGE_LABELS[st!.status] ?? st!.status}` : "백테스트가 돌고 있어요"}</b>
        <span className="pg-runprog-pct">{st ? `${pct.toFixed(0)}%` : "—"}</span>
      </div>
      <div className="pg-runprog-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} /></div>
      <p className="pg-runprog-stage">
        {err ? `상태를 읽지 못했어요 — ${err}. 잠시 뒤 다시 확인해요.`
          : ended ? (st?.error_message ?? "사유 미상")
            : st ? `${STAGE_LABELS[st.status] ?? st.status}${st.status_message ? ` · ${st.status_message}` : ""}` : "상태를 확인하는 중이에요."}
      </p>
      <button type="button" className={`pg-btn${done ? " pg-btn--primary" : ""}`} disabled={!done} onClick={onReload}>
        결과 불러오기
      </button>
    </div>
  );
}

// ── 결과 ─────────────────────────────────────────────────────────────────────

const STATS: [string, string, number, string][] = [
  ["total_return_pct", "총수익", 2, "%"], ["cagr", "연평균(CAGR)", 2, "%"], ["sharpe_ratio", "샤프", 2, ""],
  ["max_drawdown_pct", "최대 낙폭", 2, "%"], ["win_rate", "승률", 1, "%"], ["num_trades", "거래 수", 0, "회"],
];

export function BacktestLoadResult({ v, prov }: { v: Dict; prov: Dict }) {
  const s = (v.statistics as Dict) ?? {};
  const eq = (v.equity as { dates?: string[]; values?: number[] }) ?? {};
  const vals = eq.values ?? [];
  const step = Math.max(1, Math.floor(vals.length / 300));
  const data = vals.map((y, i) => ({ d: (eq.dates ?? [])[i], y })).filter((_, i) => i % step === 0);
  return (
    <>
      {prov.perf_label ? <div className="pg-perf"><PerfLabel value={prov.perf_label as PerfLabelValue} /></div> : null}
      <KV rows={STATS.map(([k, label, d, u]) => [label, fmt(s[k], d, u)] as [string, ReactNode])} />
      {data.length > 1 && (
        <div className="pg-chart" role="img" aria-label={`자산 추이 ${data.length}점`}>
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="d" hide />
              <YAxis width={52} tick={{ fontSize: 10 }} domain={["auto", "auto"]}
                     tickFormatter={(x: number) => `${(x / 1e8).toFixed(2)}억`} />
              <Tooltip formatter={(x: number) => `${Math.round(x).toLocaleString("ko-KR")}원`} />
              <Line dataKey="y" name="자산" dot={false} stroke="var(--pg-blue)" strokeWidth={1.5} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="pg-note">실행 {String(v.run_id)} · 조건 통과 {String(v.screened_count ?? "—")}종목</p>
    </>
  );
}

export function BacktestAttributionResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const rows = ((r.rows as Dict[]) ?? []).slice().sort((a, b) => Math.abs(num(b.contribution_pct) ?? 0) - Math.abs(num(a.contribution_pct) ?? 0));
  const max = Math.max(0.01, ...rows.map((x) => Math.abs(num(x.contribution_pct) ?? 0)));
  return (
    <>
      <KV rows={[["기간", `${String(r.months_from_run ?? "—")}개월`],
                 ["설명력(R²)", fmt(((r.diagnostics as Dict) ?? {}).r_squared, 2)],
                 ["팩터 몫 · 설명 안 된 몫", `${signed(r.factor_contribution_pct, 2, "%")} · ${signed(r.alpha_contribution_pct, 2, "%")}`]]} />
      <table className="pg-table pg-attr"><tbody>{rows.map((x) => {
        const c = num(x.contribution_pct) ?? 0;
        return (
          <tr key={String(x.factor)}>
            <td className="pg-td-name" title={String(x.series ?? "")}>{labels[String(x.factor)] ?? String(x.factor)}{x.collinear ? <span className="pg-tag pg-tag--assumed" title={String(x.collinear_reason ?? "")}>겹침</span> : null}</td>
            <td className="pg-td-bar"><span className={`pg-bar${c < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(c) / max) * 100}%` }} /></td>
            <td className={`pg-td-num${c < 0 ? " pg-neg" : ""}`}>{signed(c, 2, "%")}</td>
          </tr>
        );
      })}</tbody></table>
      <p className="pg-note">같이 움직인 정도를 나눈 것이에요 — 원인이라는 뜻은 아니에요.</p>
    </>
  );
}

export function BacktestCompareResult({ v }: { v: Dict }) {
  const rows = (v.rows as Dict[]) ?? [];
  const diffs = (v.differences as Dict[]) ?? [];
  return (
    <>
      {diffs.length > 0 && (
        <div className="pg-warn pg-cmp-warn" role="note">
          같은 조건이 아니에요 — {diffs.map((d) => `${String(d.label)}(${String(d.a)} / ${String(d.b)})`).join(", ")}.
          차이가 규칙 때문인지 조건 때문인지 가를 수 없어요.
        </div>
      )}
      <table className="pg-table pg-cmp">
        <thead><tr><th>지표</th><th className="pg-td-num">A {String(v.a)}</th><th className="pg-td-num">B {String(v.b)}</th><th className="pg-td-num">B − A</th></tr></thead>
        <tbody>{rows.map((x) => (
          <tr key={String(x.key)}>
            <td className="pg-td-name">{String(x.label)}</td>
            <td className="pg-td-num">{fmt(x.a, 2)}</td>
            <td className="pg-td-num">{fmt(x.b, 2)}</td>
            <td className={`pg-td-num${(num(x.diff) ?? 0) < 0 ? " pg-neg" : ""}`}>{signed(x.diff, 2)}</td>
          </tr>
        ))}</tbody>
      </table>
    </>
  );
}
