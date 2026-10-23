"use client";
/**
 * 실행실 서랍 (BL2 · 마법사 08 EXECUTION 에서 옮김) — ★계획은 저장된 실행 목표에서만 만든다★
 * ==========================================================================
 * 순서: 저장된 실행 목표 고르기 → 계획 미리보기(주문·비용·사전 점검) → 계획 저장(초안) → 검토·승인·반려 → 모의 제출 →
 * 수동 체결 입력. 모든 판단은 서버가 한다 — 목표가 실행 가능한지(`_resolve_target`, R0 차단선) · 사전 점검 차단이면 승인
 * 불가 · 상태 전이 규칙. 이 화면은 서버의 거절 사유를 그대로 보인다. ★실제 주문은 없다★ — 모의 제출 뒤 체결은 사람이
 * 입력한다(브로커 미연결). 6중 안전장치·주문 실행기는 이 화면과 무관하다.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { targetVersionApi, type TargetVersion } from "@/entities/allocation/targetVersion";
import { executionApi, type ExecutionPlan, type PlanStatus, type PreTrade } from "@/entities/execution/api";

const won = (n: number) => `${Math.round(n).toLocaleString("ko-KR")}원`;
const STATUS_KO: Record<PlanStatus, string> = {
  draft: "초안", reviewed: "검토됨", approved: "승인됨", paper_submitted: "모의 제출",
  partially_filled: "부분 체결", filled: "체결 완료", cancelled: "취소됨", rejected: "반려됨", reconciled: "정산 완료",
};
/** 버튼으로 여는 전이 — 체결로 가는 전이는 수동 체결 입력으로만(마법사와 같은 표). */
const FORWARD: Record<PlanStatus, PlanStatus[]> = {
  draft: ["reviewed", "cancelled"], reviewed: ["approved", "draft", "rejected", "cancelled"],
  approved: ["paper_submitted", "cancelled", "rejected"], paper_submitted: ["cancelled", "rejected"],
  partially_filled: ["reconciled", "cancelled"], filled: ["reconciled"], cancelled: [], rejected: [], reconciled: [],
};
const CHECK = { pass: "통과", warning: "주의", block: "막힘" } as const;
const TAG = { pass: "confirmed", warning: "assumed", block: "failed" } as const;
const when = (t: number) => new Date(t * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

function Checks({ pre }: { pre: PreTrade }) {
  return (
    <ul className="pg-checks">{pre.checks.map((c) => (
      <li key={c.name}><span className={`pg-tag pg-tag--${TAG[c.status]}`}>{CHECK[c.status]}</span><span>{c.name} — {c.detail}</span></li>
    ))}</ul>
  );
}

function PlanSummary({ plan, pre }: { plan: ExecutionPlan; pre: PreTrade }) {
  const s = plan.summary;
  return (
    <>
      <dl className="pg-kv">
        <div><dt>주문</dt><dd>{s.n_orders}건 (사기 {s.n_buy} · 팔기 {s.n_sell})</dd></div>
        <div><dt>회전율</dt><dd>{s.turnover_pct}%</dd></div>
        <div><dt>예상 비용</dt><dd>{won(s.est_cost)} · {s.est_cost_bp}bp</dd></div>
        <div><dt>사전 점검</dt><dd>{pre.can_approve ? "승인할 수 있어요" : "막힌 항목이 있어 승인할 수 없어요"}</dd></div>
      </dl>
      <Checks pre={pre} />
      {plan.missing_price.length > 0 && <p className="pg-warn">시세가 없어 주문에서 뺀 종목: {plan.missing_price.join(", ")}</p>}
    </>
  );
}

function NewPlan({ onSaved }: { onSaved: (id: string) => void }) {
  const [tv, setTv] = useState<TargetVersion | null>(null);
  const [pv, setPv] = useState(100_000_000);
  const [name, setName] = useState("리밸런싱 실행 계획");
  const [shown, setShown] = useState(8);
  const targets = useQuery({ queryKey: ["target-versions"], queryFn: () => targetVersionApi.list() });
  // ★목표 비중은 서버가 tpv_id 로 다시 읽어 대조한다★ 단위는 목표 버전의 관례(퍼센트)를 선언한다 — 모호 구간을 추측하지 않는다.
  const req = tv ? { tpv_id: tv.tpv_id, target_weights: tv.final_weights, current_weights: {}, weight_unit: "percent" as const,
                     portfolio_value: pv } : null;
  const preview = useMutation({ mutationFn: () => executionApi.preview(req!) });
  const save = useMutation({
    mutationFn: () => executionApi.save({ ...req!, name }),
    onSuccess: (r) => { if (r.saved && r.plan_id) onSaved(r.plan_id); },
  });

  if (targets.isLoading) return <p className="pg-help" role="status">실행 목표를 불러오는 중이에요.</p>;
  if (targets.isError) return <p className="pg-field-err">실행 목표를 불러오지 못했어요 — {(targets.error as Error).message}</p>;
  if (targets.data && !targets.data.available) return <p className="pg-warn">{targets.data.reason}</p>;
  const list = targets.data?.versions ?? [];
  return (
    <section className="pg-rec-sec" aria-label="새 실행 계획">
      <h3 className="pg-h4">1. 실행 목표 고르기</h3>
      {list.length === 0 && <p className="pg-help">저장된 실행 목표가 없어요 — 캔버스의 ‘실행 목표 만들기’ 노드에서 저장하면 여기에 나와요.</p>}
      {tv && (
        <button type="button" className="pg-btn pg-btn--ghost pg-rec-change" onClick={() => { setTv(null); preview.reset(); save.reset(); }}>
          다른 목표 고르기
        </button>
      )}
      <div className="pg-pick" role="radiogroup" aria-label="실행 목표">
        {(tv ? list.filter((t) => t.tpv_id === tv.tpv_id) : list.slice(0, shown)).map((t) => {
          const ok = t.status === "executable";
          return (
            <button key={t.tpv_id} type="button" role="radio" aria-checked={tv?.tpv_id === t.tpv_id} disabled={!ok}
                    className={`pg-pick-row${tv?.tpv_id === t.tpv_id ? " on" : ""}`} data-tpv={t.tpv_id}
                    onClick={() => { setTv(t); preview.reset(); save.reset(); }}>
              <span className="pg-pick-box" aria-hidden="true" />
              <span className="pg-pick-main">
                <b>{Object.keys(t.final_weights).length}종목{t.cash_weight ? ` · 현금 ${t.cash_weight.toFixed(1)}%` : ""}</b>
                <span className="pg-pick-sub">{t.tpv_id}{t.created_at ? ` · ${when(t.created_at)}` : ""}</span>
                {!ok && <span className="pg-pick-sub">{t.status_reason ?? "실행할 수 없는 목표예요."}</span>}
              </span>
              <span className={`pg-tag pg-tag--${ok ? "confirmed" : "assumed"}`}>{ok ? "실행 가능" : "연구용"}</span>
            </button>
          );
        })}
      </div>
      {!tv && list.length > shown && (
        <button type="button" className="pg-btn pg-btn--ghost" onClick={() => setShown((n) => n + 10)}>
          이전 목표 더 보기 ({list.length - shown}개 남음)
        </button>
      )}
      {tv && (
        <>
          <h3 className="pg-h4">2. 계획 미리보기</h3>
          <label className="pg-rec-field">평가 금액(원)
            <input className="pg-field-input" type="number" min={1_000_000} step={1_000_000} value={pv}
                   onChange={(e) => setPv(Math.max(1_000_000, Number(e.target.value) || 0))} />
          </label>
          <button type="button" className="pg-btn" disabled={preview.isPending} onClick={() => preview.mutate()}>
            {preview.isPending ? "계산하는 중" : "주문 목록 미리 보기"}
          </button>
          {preview.isError && <p className="pg-field-err">미리보기가 실패했어요 — {(preview.error as Error).message}</p>}
          {preview.data?.blocked && <p className="pg-warn" role="status">계획을 만들지 않았어요 — {preview.data.reason ?? "사유 미상"}</p>}
          {preview.data && !preview.data.blocked && (
            <>
              <p className="pg-note">현재 보유는 비워 두고 계산해요 — 전부 현금에서 시작한다고 가정한 주문이에요.</p>
              <PlanSummary plan={preview.data.plan} pre={preview.data.pretrade} />
            </>
          )}
          {preview.data && !preview.data.blocked && (
            <>
              <h3 className="pg-h4">3. 초안으로 저장</h3>
              <div className="pg-rec-row">
                <input className="pg-field-input" value={name} aria-label="계획 이름" onChange={(e) => setName(e.target.value)} />
                <button type="button" className="pg-btn pg-btn--primary" disabled={save.isPending} onClick={() => save.mutate()}>
                  {save.isPending ? "저장하는 중" : "계획 저장"}
                </button>
              </div>
              {save.data && !save.data.saved && (
                <p className="pg-warn" role="status">저장하지 않았어요 — {save.data.reason ?? save.data.message ?? "사유 미상"}</p>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

function PlanFlow({ planId }: { planId: string }) {
  const qc = useQueryClient();
  const plan = useQuery({ queryKey: ["execution", "plan", planId], queryFn: () => executionApi.get(planId) });
  const [msg, setMsg] = useState<string | null>(null);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["execution", "plan", planId] }); qc.invalidateQueries({ queryKey: ["execution", "plans"] }); };
  const move = useMutation({
    mutationFn: (to: PlanStatus) => executionApi.transition(planId, to),
    onSuccess: (r, to) => { setMsg(r.ok ? `‘${STATUS_KO[to]}’로 바꿨어요.` : `바꾸지 못했어요 — ${r.reason ?? "사유 미상"}`); refresh(); },
  });
  const fills = useMutation({
    mutationFn: () => executionApi.fills(planId, (plan.data?.plan?.orders ?? []).map((o) => ({
      stock_code: o.stock_code, filled_qty: o.quantity, avg_price: o.price_est }))),
    onSuccess: (r) => { setMsg(r.ok ? "체결을 전량으로 입력했어요." : `체결을 입력하지 못했어요 — ${r.reason ?? "사유 미상"}`); refresh(); },
  });
  if (plan.isLoading) return <p className="pg-help" role="status">계획을 불러오는 중이에요.</p>;
  if (plan.isError || !plan.data) return <p className="pg-field-err">계획을 불러오지 못했어요.</p>;
  const p = plan.data;
  const blocked = p.pretrade ? !p.pretrade.can_approve : false;
  return (
    <section className="pg-rec-sec" aria-label="계획 진행" data-plan={p.plan_id}>
      <div className="pg-rec-row">
        <span className={`pg-tag pg-tag--${p.status === "approved" ? "confirmed" : "unknown"}`}>{STATUS_KO[p.status]}</span>
        <b>{p.name}</b>
      </div>
      {p.plan && p.pretrade && <PlanSummary plan={p.plan} pre={p.pretrade} />}
      {blocked && <p className="pg-warn" role="status">사전 점검에 막힌 항목이 있어 승인할 수 없어요 — 위 ‘막힘’ 항목을 풀어야 해요.</p>}
      <div className="pg-rec-actions">
        {FORWARD[p.status].map((to) => (
          <button key={to} type="button" className={`pg-btn${to === "approved" ? " pg-btn--primary" : ""}`}
                  disabled={move.isPending || (to === "approved" && blocked)} data-to={to} onClick={() => move.mutate(to)}>
            {STATUS_KO[to]}{to === "draft" ? "으로" : "로"}
          </button>
        ))}
        {(p.status === "paper_submitted" || p.status === "partially_filled") && (
          <button type="button" className="pg-btn" disabled={fills.isPending} onClick={() => fills.mutate()}>체결 전량 입력</button>
        )}
      </div>
      {msg && <p className="pg-save-msg" role="status">{msg}</p>}
      <p className="pg-note">실제 주문은 나가지 않아요 — 모의 제출 뒤 체결은 사람이 입력해요(브로커 미연결).</p>
      <details className="pg-rec-audit">
        <summary>기록 {p.audit.length}줄</summary>
        <ul className="pg-list">{p.audit.slice().reverse().map((a, i) => (
          <li key={i}>{when(a.ts)} · {a.action}{a.status ? ` → ${STATUS_KO[a.status as PlanStatus] ?? a.status}` : ""}{a.note || a.detail ? ` — ${a.note || a.detail}` : ""}</li>
        ))}</ul>
      </details>
    </section>
  );
}

export function ExecutionSheetBody() {
  const [picked, setPicked] = useState<string | null>(null);
  const [mode, setMode] = useState<"new" | "list">("list");
  const qc = useQueryClient();
  const plans = useQuery({ queryKey: ["execution", "plans"], queryFn: () => executionApi.list() });
  return (
    <>
      <div className="pg-chips" role="tablist" aria-label="실행실">
        <button type="button" role="tab" aria-selected={mode === "list"} className={`pg-chip${mode === "list" ? " on" : ""}`}
                onClick={() => setMode("list")}>저장된 계획</button>
        <button type="button" role="tab" aria-selected={mode === "new"} className={`pg-chip${mode === "new" ? " on" : ""}`}
                onClick={() => setMode("new")}>새 계획 만들기</button>
      </div>
      {mode === "new" && <NewPlan onSaved={(id) => { qc.invalidateQueries({ queryKey: ["execution", "plans"] }); setPicked(id); setMode("list"); }} />}
      {mode === "list" && (
        <section className="pg-rec-sec" aria-label="저장된 계획">
          {plans.isLoading && <p className="pg-help" role="status">계획을 불러오는 중이에요.</p>}
          {plans.isError && <p className="pg-field-err">계획 목록을 불러오지 못했어요 — {(plans.error as Error).message}</p>}
          {plans.data && plans.data.plans.length === 0 && <p className="pg-help">저장된 계획이 없어요 — ‘새 계획 만들기’에서 실행 목표로 만들어요.</p>}
          <div className="pg-pick" role="radiogroup">
            {(plans.data?.plans ?? []).map((p) => (
              <button key={p.plan_id} type="button" role="radio" aria-checked={picked === p.plan_id}
                      className={`pg-pick-row${picked === p.plan_id ? " on" : ""}`} onClick={() => setPicked(p.plan_id)}>
                <span className="pg-pick-box" aria-hidden="true" />
                <span className="pg-pick-main"><b>{p.name}</b><span className="pg-pick-sub">{when(p.created_at)} · {p.plan_id}</span></span>
                <span className="pg-tag pg-tag--unknown">{STATUS_KO[p.status]}</span>
              </button>
            ))}
          </div>
          {picked && <PlanFlow planId={picked} />}
        </section>
      )}
    </>
  );
}
