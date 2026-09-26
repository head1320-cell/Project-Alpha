"use client";
/**
 * 실행·기록 노드의 결과 (BK W4) — 주문 목록 · 실행 목표 · 결정 기록 미리보기
 * ★여기에는 주문 버튼이 없다★ 승인·주문·체결 입력은 기존 실행실(마법사)의 6중 안전장치 뒤에만 있다.
 */
import type { ReactNode } from "react";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const won = (v: unknown) => (num(v) === null ? "—" : `${Math.round(v as number).toLocaleString("ko-KR")}원`);
const pct = (v: unknown, d = 1) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const CHECK = { pass: "통과", warning: "주의", block: "막힘" } as Record<string, string>;
const TAG = { pass: "confirmed", warning: "assumed", block: "failed" } as Record<string, string>;

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

export function OrdersResult({ v }: { v: Dict }) {
  const plan = (v.plan as Dict) ?? {};
  const s = (plan.summary as Dict) ?? {};
  const orders = (plan.orders as Dict[]) ?? [];
  const pre = (v.pretrade as Dict) ?? {};
  return (
    <>
      <p className="pg-note">주문은 나가지 않아요 — 무엇을 사고팔지 미리 본 목록이에요.</p>
      <KV rows={[["평가 금액", won(v.portfolio_value)], ["사는 금액", won(s.buy_notional)], ["파는 금액", won(s.sell_notional)],
                 ["예상 비용", won(s.est_cost)], ["사전 점검", pre.can_approve ? "승인 가능" : "승인 불가"]]} />
      <h4 className="pg-h4">주문</h4>
      <table className="pg-table">
        <thead><tr><th>종목</th><th>방향</th><th className="pg-td-num">수량</th><th className="pg-td-num">금액</th></tr></thead>
        <tbody>{orders.map((o) => (
          <tr key={String(o.stock_code)}>
            <td className="pg-td-name">{String(o.corp_name ?? o.stock_code)}</td>
            <td className={o.side === "sell" ? "pg-neg" : ""}>{o.side === "buy" ? "사기" : o.side === "sell" ? "팔기" : String(o.side ?? "—")}</td>
            <td className="pg-td-num">{num(o.quantity)?.toLocaleString("ko-KR") ?? "—"}</td>
            <td className="pg-td-num">{won(o.notional)}</td>
          </tr>
        ))}</tbody>
      </table>
      <h4 className="pg-h4">사전 점검</h4>
      <ul className="pg-checks">{((pre.checks as Dict[]) ?? []).map((c, i) => (
        <li key={i}><span className={`pg-tag pg-tag--${TAG[String(c.status)] ?? "unknown"}`}>{CHECK[String(c.status)] ?? String(c.status)}</span>
          <span>{String(c.name)} — {String(c.detail)}</span></li>
      ))}</ul>
    </>
  );
}

export function TargetResult({ v }: { v: Dict }) {
  const tv = (v.target as Dict) ?? {};
  const fw = (tv.final_weights as Record<string, number>) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const ok = tv.status === "executable";
  const rows = Object.entries(fw).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...rows.map(([, w]) => Math.abs(w)));
  return (
    <>
      <p className={`pg-model-type pg-model-type--${ok ? "hist" : "hypo"}`}>{ok ? "실행할 수 있는 목표" : "연구용 목표"}</p>
      {!ok && tv.status_reason ? <p className="pg-warn">{String(tv.status_reason)}</p> : null}
      <table className="pg-table"><tbody>
        {rows.map(([k, w]) => (
          <tr key={k}><td className="pg-td-name">{labels[k] ?? k}</td>
            <td className="pg-td-bar"><span className={`pg-bar${w < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(w) / max) * 100}%` }} /></td>
            <td className="pg-td-num">{pct(w, 2)}</td></tr>
        ))}
        {num(tv.cash_weight) ? <tr><td className="pg-td-name">현금</td><td /><td className="pg-td-num">{pct(tv.cash_weight, 2)}</td></tr> : null}
      </tbody></table>
      {(tv.overlay as Dict | null)?.source ? <p className="pg-note">노출 조절 근거: {String((tv.overlay as Dict).source)}</p> : null}
    </>
  );
}

export function JournalResult({ v }: { v: Dict }) {
  const rec = (v.record as Dict) ?? {};
  const links = (v.links as Dict) ?? {};
  const t = (links.target as Dict) ?? {};
  return (
    <>
      <KV rows={[["제목", String(v.title ?? "")], ["결정", String(rec.decision ?? "")],
                 ["목표 상태", t.status === "executable" ? "실행 가능" : "연구용"],
                 ["주문 요약", links.orders ? "함께 남겨요" : "없어요"], ["충격 점검", links.stress ? "함께 남겨요" : "없어요"]]} />
      {rec.thesis ? <p className="pg-note">이유: {String(rec.thesis)}</p> : <p className="pg-warn">이유를 적지 않았어요.</p>}
    </>
  );
}
