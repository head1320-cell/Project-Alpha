"use client";
/**
 * 마법사에서 옮긴 계산 노드의 결과 (BL2b) — 프런티어 · 국면 앙상블/설명 · 세 갈래 · 전략 건강 · 묶음 분석 · 알파 둘
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 계산하지 못한 칸은 비워 두지 않고 "—" 와 사유를 적는다.
 */
import type { ReactNode } from "react";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: unknown, d = 1) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const sgn = (v: unknown, d = 3) => (num(v) === null ? "—" : `${(v as number) >= 0 ? "+" : "−"}${Math.abs(v as number).toFixed(d)}`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

const REGIME_KO: Record<string, string> = {
  Goldilocks: "골디락스(성장↑·물가↓)", Reflation: "리플레이션(성장↑·물가↑)",
  Stagflation: "스태그플레이션(성장↓·물가↑)", Disinflation: "디스인플레이션(성장↓·물가↓)",
};
const rk = (r: unknown) => REGIME_KO[String(r)] ?? String(r ?? "—");

// ── 효율적 프런티어 ─────────────────────────────────────────────────────────

export function FrontierResult({ v }: { v: Dict }) {
  const curve = ((v.curve as Dict[]) ?? []).map((r) => ({ x: num(r.volatility), y: num(r.return) }));
  const cloud = v.cloud as { returns?: number[]; volatilities?: number[] } | null;
  // 구름 좌표는 서버가 이미 % 로 준다(곡선과 같은 단위) — 다시 곱하지 않는다.
  const dots = (cloud?.volatilities ?? []).map((x, i) => ({ x, y: (cloud?.returns ?? [])[i] }))
    .filter((_, i) => i % 3 === 0);
  const pt = v.point as { return: number; volatility: number } | null;
  const best = ((v.curve as Dict[]) ?? []).reduce<Dict | null>((b, r) => (b && (num(b.sharpe) ?? -1e9) >= (num(r.sharpe) ?? -1e9) ? b : r), null);
  return (
    <>
      <div className="pg-chart pg-frontier" role="img"
           aria-label={`흔들림 대비 수익 경계 ${curve.length}점${pt ? ` · 이은 비중 연 ${pt.return}% · 흔들림 ${pt.volatility}%` : ""}`}>
        <ResponsiveContainer width="100%" height={220}>
          <ScatterChart margin={{ top: 8, right: 12, bottom: 18, left: 0 }}>
            <CartesianGrid stroke="var(--pg-line)" strokeDasharray="2 4" />
            <XAxis type="number" dataKey="x" name="흔들림" unit="%" tick={{ fontSize: 11 }} domain={["auto", "auto"]}
                   label={{ value: "흔들림(연)", position: "insideBottom", offset: -8, fontSize: 11, fill: "var(--pg-body)" }} />
            <YAxis type="number" dataKey="y" name="수익" unit="%" width={44} tick={{ fontSize: 11 }} domain={["auto", "auto"]} />
            <ZAxis range={[14, 14]} />
            <Tooltip cursor={false} formatter={(x: number) => `${x?.toFixed?.(1)}%`} />
            {dots.length > 0 && <Scatter name="무작위 조합" data={dots} fill="var(--pg-line)" isAnimationActive={false} />}
            <Scatter name="경계" data={curve} fill="var(--pg-blue)" line={{ stroke: "var(--pg-blue)", strokeWidth: 2 }}
                     shape={() => <g />} isAnimationActive={false} />
            {pt && <Scatter name="이은 비중" data={[{ x: pt.volatility, y: pt.return }]} isAnimationActive={false}
                            shape={(props: { cx?: number; cy?: number }) => (
                              <circle cx={props.cx} cy={props.cy} r={7} fill="var(--pg-assume)" stroke="var(--pg-paper)" strokeWidth={2.5} />
                            )} />}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <KV rows={[
        ["곡선", `${curve.length}점`],
        ["가장 좋은 점", best ? `연 ${pct(best.return)} · 흔들림 ${pct(best.volatility)}` : "—"],
        ["이은 비중", pt ? <><span className="pg-dot-point" aria-hidden="true" />연 {pct(pt.return)} · 흔들림 {pct(pt.volatility)}</>
                       : "비중을 이으면 곡선 위에 찍어요"],
      ]} />
      {cloud === null && <p className="pg-warn">무작위 조합 구름은 그리지 못했어요 — {String(v.cloud_reason ?? "사유 미상")}</p>}
    </>
  );
}

// ── 국면 앙상블 · 국면 설명 ─────────────────────────────────────────────────

const TOOL_KO: Record<string, string> = { axis: "성장·물가 축", markov: "상태 전환", cluster: "군집" };

export function EnsembleResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const regimes = (r.regimes as string[]) ?? [];
  const tools = (r.tools as Record<string, Dict>) ?? {};
  const agree = (r.agreement as Dict) ?? {};
  return (
    <>
      <p className={`pg-model-type pg-model-type--${agree.unanimous ? "hist" : "hypo"}`}>{String(agree.note ?? "")}</p>
      {/* 국면이 행, 방법이 열 — 국면 이름이 길어 열 머리에 두면 뭉개진다. 각 방법이 고른 칸은 굵게. */}
      <table className="pg-table pg-ensemble">
        <thead><tr><th>국면</th>{Object.keys(tools).map((k) => <th key={k} className="pg-td-num">{TOOL_KO[k] ?? k}</th>)}</tr></thead>
        <tbody>
          {regimes.map((g) => (
            <tr key={g}>
              <td className="pg-td-name">{rk(g)}</td>
              {Object.entries(tools).map(([k, t]) => {
                const p = t.available ? num((t.probs as Dict)?.[g]) : null;
                return <td key={k} className={`pg-td-num${t.available && t.argmax === g ? " pg-strong" : ""}`}>{p === null ? "—" : `${(p * 100).toFixed(0)}%`}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {Object.entries(tools).filter(([, t]) => !t.available).map(([k, t]) => (
        <p key={k} className="pg-warn">{TOOL_KO[k] ?? k}은 계산하지 못했어요 — {String(t.reason ?? "사유 미상")}</p>
      ))}
      <p className="pg-note">{String(r.note ?? "")} 관측 {String(r.n_obs ?? "—")}개월.</p>
    </>
  );
}

export function RegimeExplainResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const tr = (r.transitions as Dict) ?? {};
  const dr = (r.drivers as Dict) ?? {};
  const span = (r.span as Dict) ?? {};
  const fc = (tr.forecast as Dict) ?? {};
  const drivers = ((dr.drivers as Dict[]) ?? []).slice().sort((a, b) => Math.abs(num(b.phi) ?? 0) - Math.abs(num(a.phi) ?? 0)).slice(0, 6);
  const mean = (fc.mean as Record<string, number>) ?? {};
  return (
    <>
      <KV rows={[
        ["지금 국면", tr.available ? rk(tr.current) : `— ${String(tr.reason ?? "")}`],
        ["이어진 기간", num(tr.run_length_months) === null ? "—" : `${String(tr.run_length_months)}개월`],
        ["분류한 기간", `${String(span.first ?? "?")} ~ ${String(span.last ?? "?")} · ${String(span.n_months ?? "—")}개월${span.truncated ? " (요청보다 짧아요)" : ""}`],
      ]} />
      {drivers.length > 0 && (
        <>
          <h4 className="pg-h4">이 국면을 만든 지표 (확률 {pct((num(dr.probability) ?? 0) * 100, 0)} · 기준 {pct((num(dr.baseline) ?? 0) * 100, 0)})</h4>
          <table className="pg-table">
            <tbody>{drivers.map((d, i) => (
              <tr key={i}><td className="pg-td-name">{String(d.label ?? d.feature ?? d.name ?? "—")}</td>
                <td className={`pg-td-num${(num(d.phi) ?? 0) < 0 ? " pg-neg" : ""}`}>{sgn((num(d.phi) ?? 0) * 100, 1)}%p</td></tr>
            ))}</tbody>
          </table>
        </>
      )}
      {fc.available ? (
        <>
          <h4 className="pg-h4">{String(fc.k ?? "")}개월 뒤 국면 확률</h4>
          <table className="pg-table"><tbody>{Object.entries(mean).sort((a, b) => b[1] - a[1]).map(([g, p]) => (
            <tr key={g}><td className="pg-td-name">{rk(g)}</td><td className="pg-td-num">{pct(p * 100, 0)}</td></tr>
          ))}</tbody></table>
        </>
      ) : <p className="pg-warn">전환 예측을 하지 못했어요 — {String(fc.reason ?? "사유 미상")}</p>}
    </>
  );
}

// ── 세 갈래 시나리오 ────────────────────────────────────────────────────────

const LEG_KO: Record<string, string> = { baseline: "그대로 두기", timing_only: "타이밍만", timing_macro: "타이밍 + 국면" };
const STATE_KO: Record<string, string> = { risk_on: "위험-온", risk_off: "위험-오프", unavailable: "판단 불가", partial: "일부" };

export function ThreeWayResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const sc = (r.scenario as Dict) ?? {};
  const legs = (r.legs as Record<string, Dict>) ?? {};
  return (
    <>
      <p className="pg-model-type pg-model-type--hypo">{String(sc.label ?? "")} · {String(sc.shock_basis ?? "")}</p>
      <table className="pg-table pg-threeway">
        <thead><tr><th>갈래</th><th>판정</th><th className="pg-td-num">노출</th><th className="pg-td-num">손실</th></tr></thead>
        <tbody>{Object.entries(legs).map(([k, g]) => (
          <tr key={k}>
            <td className="pg-td-name">{LEG_KO[k] ?? k}</td>
            <td>{STATE_KO[String(g.state)] ?? String(g.state)}</td>
            <td className="pg-td-num">{pct((num(g.exposure) ?? 0) * 100, 0)}</td>
            <td className={`pg-td-num${(num(g.shock_pct) ?? 0) < 0 ? " pg-neg" : ""}`}>{num(g.shock_pct) === null ? "미계산" : pct(g.shock_pct, 2)}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="pg-note">{String(r.composition_note ?? "")}</p>
    </>
  );
}

// ── 전략 건강 · 묶음 분석 ───────────────────────────────────────────────────

const HEALTH_KO: Record<string, string> = { healthy: "건강", watch: "지켜보기", de_risk: "줄이기", paused: "멈춤", retired: "폐기" };

export function HealthResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const items = (r.items as Dict[]) ?? [];
  if (!items.length) return <p className="pg-help">등록된 알파가 없어요 — 상단 ‘알파’ 서랍에서 등록하면 여기서 상태를 봐요.</p>;
  return (
    <>
      <table className="pg-table">
        <thead><tr><th>알파</th><th>상태</th><th className="pg-td-num">못 잰 신호</th></tr></thead>
        <tbody>{items.map((it) => (
          <tr key={String(it.alpha_id)}>
            <td className="pg-td-name">{String(it.name)}</td>
            <td>{HEALTH_KO[String(it.status)] ?? String(it.status)}</td>
            <td className="pg-td-num">{((it.signals as Dict[]) ?? []).filter((s) => s.status === "unmeasured").length}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="pg-note">{String(r.note ?? "")}</p>
    </>
  );
}

export function SleeveAnalyticsResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const names = (r.sleeves as string[]) ?? Object.keys((r.correlation as Dict) ?? {});
  const corr = (r.correlation as Record<string, Record<string, number>>) ?? {};
  const rc = (r.risk_contribution_pct as Record<string, number>) ?? {};
  const tail = (r.tail_dependency as Dict) ?? {};
  return (
    <>
      <KV rows={[["평균 상관", num(r.avg_correlation) === null ? "—" : (r.avg_correlation as number).toFixed(2)],
                 ["군집", `${String(r.n_clusters ?? "—")}개`],
                 ["함께 빠지는 정도", num(tail.lower_tail_coexceedance) === null ? "—" : `${(tail.lower_tail_coexceedance as number).toFixed(2)} (1 = 서로 무관)`]]} />
      <table className="pg-table pg-corr">
        <thead><tr><th />{names.map((n) => <th key={n} className="pg-td-num">{n}</th>)}<th className="pg-td-num">위험 몫</th></tr></thead>
        <tbody>{names.map((a) => (
          <tr key={a}><td className="pg-td-name">{a}</td>
            {names.map((b) => <td key={b} className="pg-td-num">{num(corr[a]?.[b]) === null ? "—" : corr[a][b].toFixed(2)}</td>)}
            <td className="pg-td-num">{pct(rc[a])}</td></tr>
        ))}</tbody>
      </table>
    </>
  );
}

// ── 알파 검증 · 알파 포트폴리오 ─────────────────────────────────────────────

export function AlphaValidateResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const ic = (r.ic as Dict) ?? {};
  const oos = (r.is_oos as Dict) ?? {};
  const ls = (r.long_short as Dict) ?? {};
  const q = ((r.quantiles as Dict)?.ann_return_pct as number[]) ?? [];
  const max = Math.max(1, ...q.map((x) => Math.abs(x)));
  const src = v.expr_source as Dict | null;
  return (
    <>
      <p className="pg-model-type pg-model-type--hypo">{src ? `등록된 알파 ‘${String(src.name)}’ v${String(src.version)}` : "식으로 검증"} · {String(r.expr ?? "")}</p>
      <KV rows={[
        ["평균 IC", sgn(ic.mean)], ["ICIR", sgn(ic.icir, 2)], ["t 값", sgn(ic.t_stat, 2)], ["적중률", pct(ic.hit_rate, 0)],
        ["앞 절반 / 뒤 절반 IC", `${sgn(oos.is_ic)} / ${sgn(oos.oos_ic)} (${String(oos.split ?? "?")})`],
        ["롱숏", `총 ${pct(ls.total_return_pct)} · 샤프 ${sgn(ls.sharpe, 2)} · 최대 낙폭 ${pct(ls.mdd_pct)}`],
        ["기간", `${String(r.period_start ?? "?")} ~ ${String(r.period_end ?? "?")} · ${String(r.n_periods ?? "—")}번`],
      ]} />
      {q.length > 0 && (
        <>
          <h4 className="pg-h4">점수 분위별 연 수익 (낮은 점수 → 높은 점수)</h4>
          <table className="pg-table"><tbody>{q.map((x, i) => (
            <tr key={i}><td className="pg-td-name">{i + 1}분위</td>
              <td className="pg-td-bar"><span className={`pg-bar${x < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(x) / max) * 100}%` }} /></td>
              <td className={`pg-td-num${x < 0 ? " pg-neg" : ""}`}>{pct(x)}</td></tr>
          ))}</tbody></table>
        </>
      )}
      <p className="pg-note">과거 표본의 순위 상관이에요 — 거래 비용을 빼지 않았고, 앞으로의 예측력을 말해 주지 않아요.</p>
    </>
  );
}

export function AlphaPortfolioResult({ v, bars }: { v: Dict; bars: ReactNode }) {
  const excluded = (v.excluded as Dict[]) ?? [];
  return (
    <>
      <KV rows={[["실질 알파 수", num(v.effective_n) === null ? "—" : (v.effective_n as number).toFixed(1)],
                 ["기준일", String(v.as_of_effective ?? "오늘")]]} />
      {bars}
      {excluded.length > 0 && <p className="pg-warn">뺀 알파: {excluded.map((e) => `${String(e.alpha_id)}(${String(e.reason)})`).join(", ")}</p>}
      <p className="pg-note">{String(v.note ?? "")}</p>
    </>
  );
}
