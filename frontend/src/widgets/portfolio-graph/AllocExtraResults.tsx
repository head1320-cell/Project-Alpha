"use client";
/**
 * 배분 추가 노드의 결과 (BL3 W5) — 리밸런싱 판단 · 노출 → 상품 · 페어 · 시장 충격 · 현금 수익 · 전략 용량 · 멀티전략 반사실
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 이 웨이브에서 눈에 띄게 그리는 것은 **리밸런싱 저울** 하나다 —
 * 효용 개선(막대)이 비용 × (1 + 머뭇거림 폭)(문턱선)을 넘는지가 곧 결론이다. 편익을 모르면 저울 대신 '판단할 수 없어요'.
 * 나머지는 조용한 표·한 줄.
 */
import type { ReactNode } from "react";

import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";

import { InputsTable } from "./CompanyModelResults";
import { krw } from "./RiskResults";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pc = (v: unknown, d = 1) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([a, b]) => (<div key={a}><dt>{a}</dt><dd>{b}</dd></div>))}</dl>;
}

const VERDICT: Record<string, string> = { trade: "거래할 가치가 있어요", hold: "그대로 두는 게 나아요", undetermined: "판단할 수 없어요" };

/** ★이 웨이브의 한 곳★ 저울 — 막대 = 보유 기간 동안의 효용 개선, 선 = 비용 × (1 + 머뭇거림 폭). */
function Scale({ gain, cost, mult, over }: { gain: number; cost: number; mult: number; over: boolean }) {
  const bar = cost * (1 + mult);
  const mx = Math.max(gain, bar, 1e-9) * 1.15;
  const W = 340, H = 44, pad = 4;
  const X = (v: number) => pad + (Math.max(0, v) / mx) * (W - 2 * pad);
  // 넘었는지는 서버 판정(decision)이 말한다 — 화면이 부등식을 다시 풀지 않는다.
  return (
    <svg className="pg-scale" viewBox={`0 0 ${W} ${H + 18}`} role="img"
         aria-label={`효용 개선 ${gain.toFixed(3)}% 가 문턱 ${bar.toFixed(3)}% 를 ${over ? "넘어요" : "넘지 못해요"}`}>
      <rect x={pad} y={14} width={W - 2 * pad} height={16} rx={8} className="pg-scale-track" />
      <rect x={pad} y={14} width={Math.max(2, X(gain) - pad)} height={16} rx={8}
            className={over ? "pg-scale-gain pg-scale-gain--over" : "pg-scale-gain"} />
      <line x1={X(cost)} x2={X(cost)} y1={10} y2={34} className="pg-scale-cost" />
      <line x1={X(bar)} x2={X(bar)} y1={10} y2={40} className="pg-scale-bar" />
      <text x={Math.max(X(bar), 40)} y={H + 14} textAnchor="middle" className="pg-floors-t">문턱 {bar.toFixed(2)}%</text>
      <text x={Math.min(X(gain), W - pad)} y={9} textAnchor="end" className="pg-floors-t pg-floors-t--price">효용 개선 {gain.toFixed(2)}%</text>
    </svg>
  );
}

export function RebalanceResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const b = (r.benefit as Dict) ?? {}, c = (r.cost as Dict) ?? {};
  const band = ((r.band as Dict)?.by_asset as Record<string, Dict>) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const d = String(r.decision ?? "");
  const gain = num(b.gain_pct), cost = num(c.cost_pct);
  const mult = num(((r as Dict).hysteresis_mult as number)) ?? 0.5;
  return (
    <>
      <div className="pg-risk-lead">
        <span className={`pg-risk-big pg-verdict pg-verdict--${d}`}>{VERDICT[d] ?? d}</span>
        <span className="pg-risk-say">{String(r.reason ?? b.reason ?? "")}</span>
      </div>
      {d !== "undetermined" && gain !== null && cost !== null
        ? <Scale gain={gain} cost={cost} mult={mult} over={d === "trade"} />
        : <p className="pg-warn">편익을 몰라 저울을 그리지 않아요 — {String(b.reason ?? "사유 미상")}</p>}
      <KV rows={[
        ["거래비용", `${krw(c.cost_krw)} (${pc(c.cost_pct, 3)} · ${String(c.cost_bp ?? "—")}bp)`],
        ["회전율 · 주문", `${pc(c.turnover_pct)} · ${String(c.n_orders ?? "—")}건`],
        ["보유 기간", `${String(b.horizon_days ?? "—")}영업일`],
      ]} />
      {(b.provenance as Dict)?.self_referential ? (
        <p className="pg-note">편익을 잰 기대수익이 이 목표를 고른 바로 그 추정이에요 — 이득은 구조적으로 보장되고, 전망이 맞았다는 증거가 아니에요.</p>
      ) : null}
      {Object.keys(band).length > 0 && (
        <table className="pg-table pg-scen">
          <caption className="pg-muted" style={{ textAlign: "left", fontSize: 12 }}>종목마다 다른 무거래 밴드</caption>
          <thead><tr><th>종목</th><th className="pg-td-num">목표</th><th className="pg-td-num">밴드</th></tr></thead>
          <tbody>{Object.entries(band).map(([code, x]) => (
            <tr key={code}>
              <td className="pg-td-name">{labels[code] ?? code}</td>
              <td className="pg-td-num">{pc((x.inputs as Dict)?.target_weight_pct)}</td>
              <td className="pg-td-num">{x.available ? `${pc(x.low_pct)} ~ ${pc(x.high_pct)}` : "모름"}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <InputsTable r={r} />
    </>
  );
}

const EXPO: Record<string, string> = { equity: "국내 주식", equity_us: "미국 주식", equity_small: "중소형주", duration: "장기 금리",
  credit: "크레딧", commodity: "원자재", real_estate: "리츠", em: "신흥국" };

export function ImplementResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const lines = (r.lines as Dict[]) ?? [];
  const labels = (v.labels as Record<string, string>) ?? {};
  return (
    <>
      <table className="pg-table pg-scen">
        <thead><tr><th>노출</th><th>상품</th><th className="pg-td-num">비중</th></tr></thead>
        <tbody>{lines.map((x) => (
          <tr key={String(x.exposure)}>
            <td className="pg-td-name">{EXPO[String(x.exposure)] ?? String(x.exposure)}</td>
            <td>{labels[String(x.instrument)] ?? String(x.instrument)}{x.foreign_listing ? <span className="pg-muted"> · 해외 상장</span> : null}</td>
            <td className="pg-td-num">{pc(x.weight_pct, 0)}</td>
          </tr>
        ))}</tbody>
      </table>
      <KV rows={[["놓은 비중", pc(r.placed_pct, 0)], ["놓지 못한 비중", pc(r.unplaced_pct, 0)]]} />
      {Object.entries((r.unresolved as Record<string, string>) ?? {}).map(([k, why]) => <p key={k} className="pg-warn">{why}</p>)}
      <p className="pg-note">{String(r.note ?? "")}</p>
    </>
  );
}

export function PairResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const w = (r.weights as Record<string, number>) ?? {};
  return (
    <>
      <KV rows={[
        ...Object.entries(w).map(([k, x]) => [`${x >= 0 ? "사기" : "팔기"} · ${labels[k] ?? k}`, `${Math.abs(x).toFixed(1)}`] as [string, ReactNode]),
        ["순 β", r.net_beta === null ? "모름" : String(r.net_beta)],
      ]} />
      {r.beta_reason ? <p className="pg-warn">{String(r.beta_reason)}</p> : null}
      <InputsTable r={r} />
    </>
  );
}

export function ImpactResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <div className="pg-risk-lead">
        <span className="pg-risk-big">{num(r.total_impact_bps) === null ? "—" : `${(r.total_impact_bps as number).toFixed(1)}bp`}</span>
        <span className="pg-risk-say">주문이 가격을 이만큼 밀 것으로 봐요 — 예상 비용 {krw(r.estimated_cost_krw)}</span>
      </div>
      <KV rows={[["영구 · 일시", `${String(r.permanent_impact_bps ?? "—")} · ${String(r.temporary_impact_bps ?? "—")}bp`],
                 ["거래대금 대비", pc(num(r.participation_rate) === null ? null : (r.participation_rate as number) * 100, 2)]]} />
      <InputsTable r={r} />
    </>
  );
}

export function CashResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <div className="pg-risk-lead">
        <span className="pg-risk-big">{num(r.annual_cash_return) === null ? "—" : `연 ${((r.annual_cash_return as number) * 100).toFixed(2)}%`}</span>
        <span className="pg-risk-say">놀고 있는 현금 {pc(num(r.cash_ratio) === null ? null : (r.cash_ratio as number) * 100)} 가 더하는 수익</span>
      </div>
      <p className="pg-co-head">
        금리 {pc(num(r.rf_annual) === null ? null : (r.rf_annual as number) * 100, 2)}{" "}
        <span className={`pg-tag pg-tag--${r.rf_is_assumed ? "assumed" : "confirmed"}`}>{r.rf_is_assumed ? "기본값(가정)" : String(r.rf_source)}</span>
      </p>
      <InputsTable r={r} />
    </>
  );
}

export function CapacityResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const caps = (r.capacities as Record<string, Dict>) ?? {};
  return (
    <>
      <table className="pg-table pg-scen">
        <thead><tr><th>전략</th><th className="pg-td-num">용량</th><th className="pg-td-num">종목</th></tr></thead>
        <tbody>{Object.entries(caps).map(([sid, x]) => (
          <tr key={sid}>
            <td className="pg-td-name">{sid}</td>
            <td className="pg-td-num">{x.available ? krw(x.capacity_krw) : <span className="pg-tag pg-tag--unknown">모름</span>}</td>
            <td className="pg-td-num">{String(x.n_universe_tickers ?? "—")}</td>
          </tr>
        ))}</tbody>
      </table>
      {Object.values(caps).filter((x) => !x.available).map((x) => (
        <p key={String(x.strategy_id)} className="pg-note">전략 {String(x.strategy_id)}: {String(x.reason ?? x.message)}</p>
      ))}
      <InputsTable r={r} />
    </>
  );
}

export function CounterfactualResult({ v, prov }: { v: Dict; prov: Dict }) {
  const r = (v.result as Dict) ?? {};
  const scen = (r.scenarios as Dict[]) ?? [];
  const table = (r.comparison_table as Dict[]) ?? [];
  const cols = table.length ? Object.keys(table[0]) : [];
  return (
    <>
      {/* 반사실도 시뮬레이션 — 숫자 옆에 그것이 무엇인지(서버의 성과 라벨)를 먼저 */}
      {prov.perf_label ? <div className="pg-perf"><PerfLabel value={prov.perf_label as PerfLabelValue} /></div> : null}
      <ul className="pg-list">{scen.map((x) => (
        <li key={String(x.name)}>{String(x.label ?? x.name)}{x.success ? "" : <span className="pg-muted"> — {String(x.error ?? "실패")}</span>}</li>
      ))}</ul>
      {table.length > 0 && (
        <table className="pg-table pg-scen">
          <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{table.map((row, i) => (
            <tr key={i}>{cols.map((c) => <td key={c}>{typeof row[c] === "number" ? (row[c] as number).toLocaleString("ko-KR", { maximumFractionDigits: 3 }) : String(row[c] ?? "—")}</td>)}</tr>
          ))}</tbody>
        </table>
      )}
    </>
  );
}
