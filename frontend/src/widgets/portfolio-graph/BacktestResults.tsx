"use client";
/**
 * 백테스트 웨이브의 결과 (BL3 W1) — 설정 요약 · 진행 카드 · 결과(곡선·지표) · 매크로 팩터 귀인 · 두 실행 비교
 * ==========================================================================
 * 시작은 버튼, 읽기는 노드다. 진행 중인 실행은 노드가 '아직 끝나지 않았어요' 로 실패하고, 이 화면이 그 실행의 상태를
 * **읽기만**(GET) 3초마다 확인한다 — 끝나면 '결과 불러오기' 버튼이 밝아진다. 이 웨이브에서 움직이는 것은 이 카드 하나다.
 */
import { useEffect, useState, type ReactNode } from "react";
import { backtestRunApi, STAGE_LABELS, TERMINAL, type RunStatusLite } from "@/entities/backtest-run";
import type { NodeExplain } from "@/entities/portfolio-graph";
import { PerfPanel } from "./perf/PerfPanel";
import { compareViewOf, perfViewOfLoad, type CompareCurves, type DdEpisode, type YearDiffRow } from "@/shared/ui/perf/perfView";
import { PerfCompare } from "@/shared/ui/perf/PerfCompare";
import { CompareYearTable } from "@/shared/ui/perf/CompareYearTable";
import { DrawdownEpisodes } from "@/shared/ui/perf/DrawdownEpisodes";

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
        ["종목 · 동시 보유", `${num(c.max_tickers) === null ? "—" : `${String(c.max_tickers)}개`} · ${num(c.max_positions) === null ? "—" : `${String(c.max_positions)}개`}`],
        ["비용", `수수료 ${num(c.commission_rate) === null ? "—" : `${fmt((c.commission_rate as number) * 100)}%`} · 슬리피지 ${num(c.slippage_rate) === null ? "—" : `${fmt((c.slippage_rate as number) * 100)}%`}${c.charge_sell_tax ? " · 매도세" : ""}`],
      ]} />
      <p className="pg-note">아직 실행하지 않았습니다 — 설정 탭의 ‘백테스트 시작’을 누르면 백그라운드에서 실행됩니다.</p>
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
        <b>{done ? "백테스트가 완료됐습니다" : ended ? `백테스트가 ${STAGE_LABELS[st!.status] ?? st!.status}` : "백테스트가 실행 중입니다"}</b>
        <span className="pg-runprog-pct">{st ? `${pct.toFixed(0)}%` : "—"}</span>
      </div>
      <div className="pg-runprog-bar" aria-hidden="true"><span style={{ width: `${pct}%` }} /></div>
      <p className="pg-runprog-stage">
        {err ? `상태 읽기 실패 — ${err}. 잠시 후 다시 확인합니다.`
          : ended ? (st?.error_message ?? "사유 미상")
            : st ? `${STAGE_LABELS[st.status] ?? st.status}${st.status_message ? ` · ${st.status_message}` : ""}` : "상태 확인 중"}
      </p>
      <button type="button" className={`pg-btn${done ? " pg-btn--primary" : ""}`} disabled={!done} onClick={onReload}>
        결과 조회
      </button>
    </div>
  );
}

// ── 결과 ─────────────────────────────────────────────────────────────────────

/** 성과 그림 문법(2026-11-09) — 7번·전략 묶음과 같은 부품(`perf/PerfPanel`). 머리·그림·해마다·지표 묶음·표 쌍둥이는 뷰에서 옮기기만 한다. */
export function BacktestLoadResult({ v, prov, explain }: { v: Dict; prov: Dict; explain?: NodeExplain | null }) {
  return (
    <PerfPanel view={perfViewOfLoad(v, prov, explain)} fallbackTitle="저장된 백테스트 결과"
               after={<p className="pg-note">실행 {String(v.run_id)} · 조건 통과 {String(v.screened_count ?? "—")}종목</p>} />
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
                 ["팩터 기여 · 미설명 기여", `${signed(r.factor_contribution_pct, 2, "%")} · ${signed(r.alpha_contribution_pct, 2, "%")}`]]} />
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
      <p className="pg-note">동조 정도(상관)를 분해한 것입니다 — 인과를 뜻하지 않습니다.</p>
    </>
  );
}

/** 서버 비교 노드 뷰의 `compare` 블록 — 비교 화면의 `/perf/compare` 응답과 같은 `curves` 모양(같은 함수). */
type CompareBlock = { curves: CompareCurves; yearly: YearDiffRow[] | null; drawdowns: { a: DdEpisode[] | null; b: DdEpisode[] | null };
  labels: { a: string; b: string }; practice: boolean | null };

/** 둘 겹쳐 보기(2026-11-09 · 성과 그림 문법 ③) — 표 위에 같은 그림. 곡선이 없으면 서버 사유를 그대로. */
export function BacktestCompareResult({ v }: { v: Dict }) {
  const rows = (v.rows as Dict[]) ?? [];
  const diffs = (v.differences as Dict[]) ?? [];
  const cmp = (v.compare as CompareBlock | null | undefined) ?? null;
  const view = cmp ? compareViewOf({ curves: cmp.curves, yearly: cmp.yearly, rows: null },
    { unit: "x", labelA: "A", labelB: "B", question: "동일 조건에서 두 백테스트의 성과 차이",
      drawdownsA: cmp.drawdowns?.a ?? null, drawdownsB: cmp.drawdowns?.b ?? null, practice: cmp.practice ?? null }) : null;
  return (
    <>
      {view ? (
        <>
          <PerfCompare view={view} height={240} />
          <p className="pg-note">A {String(cmp?.labels?.a ?? v.a)} · B {String(cmp?.labels?.b ?? v.b)} — 각 시작값을 1로 정규화했습니다.</p>
          <h4 className="pg-h4">연도별 차이</h4>
          <CompareYearTable view={view} />
          <div className="pf-cmp-eps">
            <div><h4 className="pg-h4">A 의 주요 낙폭 구간</h4><DrawdownEpisodes episodes={view.drawdowns?.a ?? null} compact /></div>
            <div><h4 className="pg-h4">B 의 주요 낙폭 구간</h4><DrawdownEpisodes episodes={view.drawdowns?.b ?? null} compact /></div>
          </div>
        </>
      ) : (
        <p className="pg-note pf-cmp-none">{String(v.compare_reason ?? "두 실행의 곡선을 겹쳐 표시하지 못했습니다 — 서버가 사유를 제공하지 않았습니다.")}</p>
      )}
      {diffs.length > 0 && (
        <div className="pg-warn pg-cmp-warn" role="note">
          같은 조건이 아닙니다 — {diffs.map((d) => `${String(d.label)}(${String(d.a)} / ${String(d.b)})`).join(", ")}.
          차이의 원인이 규칙인지 조건인지 구분할 수 없습니다.
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
