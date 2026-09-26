"use client";
/**
 * 신호·후보 노드의 결과 (BK W2) — 스크리너 · 점수 · 점수→비중 · 중립화 · 묶음 합치기
 * 수는 서버 view 그대로 — 다시 계산하지 않는다.
 */
import type { ReactNode } from "react";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: unknown, d = 2) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const fx = (v: unknown, d = 2) => (num(v) === null ? "—" : (v as number).toFixed(d));

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

function Bars({ values, labels, unit }: { values: Record<string, number>; labels?: Record<string, string>; unit: string }) {
  const rows = Object.entries(values);
  const max = Math.max(1e-9, ...rows.map(([, v]) => Math.abs(v)));
  return (
    <table className="pg-table"><tbody>
      {rows.map(([k, v]) => (
        <tr key={k}>
          <td className="pg-td-name" title={k}>{labels?.[k] ?? k}</td>
          <td className="pg-td-bar"><span className={`pg-bar${v < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(v) / max) * 100}%` }} /></td>
          <td className="pg-td-num">{unit === "%" ? pct(v) : fx(v, 3)}</td>
        </tr>
      ))}
    </tbody></table>
  );
}

export function ScreenerResult({ v }: { v: Dict }) {
  const items = (v.items as Dict[]) ?? [];
  const ds = (v.data_source as Dict) ?? {};
  return (
    <>
      <KV rows={[["후보 범위", String(v.universe ?? "—")], ["본 종목", String(v.total_evaluated ?? "—")],
                 ["통과", String(v.total_passed ?? "—")],
                 ["데이터", ds.fully_real ? "실데이터" : `합성 포함 (재무 ${String(ds.fundamentals ?? "?")} · 시세 ${String(ds.market_data ?? "?")})`]]} />
      <h4 className="pg-h4">넘긴 종목</h4>
      <table className="pg-table">
        <thead><tr><th>종목</th><th className="pg-td-num">종합</th><th className="pg-td-num">PER</th><th className="pg-td-num">ROE</th></tr></thead>
        <tbody>{items.map((it) => (
          <tr key={String(it.stock_code)}>
            <td className="pg-td-name">{String(it.corp_name ?? it.stock_code)}</td>
            <td className="pg-td-num">{fx(it.composite_score, 1)}</td>
            <td className="pg-td-num">{fx(it.per, 1)}</td>
            <td className="pg-td-num">{fx(it.roe, 1)}</td>
          </tr>
        ))}</tbody>
      </table>
    </>
  );
}

export function ScoresResult({ v }: { v: Dict }) {
  const scores = (v.scores as Record<string, number>) ?? {};
  const top = Object.fromEntries(Object.entries(scores).slice(0, 15));
  const factors = (v.factors as Dict[] | undefined) ?? null;
  return (
    <>
      {v.expr ? <KV rows={[["식", <code key="e" className="pg-code">{String(v.expr)}</code>], ["기준일", String(v.as_of_effective ?? "—")]]} /> : null}
      {factors && (
        <KV rows={factors.map((f) => [String(f.label), f.covered ? `${f.direction === 1 ? "높을수록" : "낮을수록"} · ${String(f.n)}종목` : "값 부족 — 빠짐"] as [string, ReactNode])} />
      )}
      <h4 className="pg-h4">점수 상위 {Object.keys(top).length}</h4>
      <Bars values={top} labels={v.labels as Record<string, string>} unit="score" />
    </>
  );
}

export function ScoresToWeightsResult({ v }: { v: Dict }) {
  return (
    <>
      {!v.has_sigma && <p className="pg-warn">공분산이 없어 ‘흔들림 나눠 보기’에는 쓸 수 없어요 — 수익률을 이어 주세요.</p>}
      <h4 className="pg-h4">비중</h4>
      <Bars values={(v.weights as Record<string, number>) ?? {}} labels={v.labels as Record<string, string>} unit="%" />
    </>
  );
}

export function NeutralizeResult({ v }: { v: Dict }) {
  const before = (v.before as Record<string, number>) ?? {};
  const after = (v.after as Record<string, number>) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const names = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return (
    <>
      <p className="pg-note">연구용 비중이에요 — 중립화는 사후 변환이라 실행 목표로 쓰지 않아요.</p>
      <table className="pg-table">
        <thead><tr><th>종목</th><th className="pg-td-num">전</th><th className="pg-td-num">후</th></tr></thead>
        <tbody>{names.map((n) => (
          <tr key={n}><td className="pg-td-name">{labels[n] ?? n}</td><td className="pg-td-num">{pct(before[n])}</td>
            <td className={`pg-td-num${(after[n] ?? 0) < 0 ? " pg-neg" : ""}`}>{pct(after[n])}</td></tr>
        ))}</tbody>
      </table>
    </>
  );
}

export function SleeveResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <h4 className="pg-h4">묶음 비중</h4>
      <Bars values={(r.sleeve_allocation as Record<string, number>) ?? {}} unit="%" />
      <KV rows={Object.entries((r.risk_contribution_pct as Record<string, number>) ?? {}).map(([k, x]) => [`${k} 위험 기여`, pct(x)] as [string, ReactNode])} />
      <h4 className="pg-h4">합친 종목 비중</h4>
      <Bars values={(r.combined_weights_pct as Record<string, number>) ?? {}} labels={v.labels as Record<string, string>} unit="%" />
    </>
  );
}
