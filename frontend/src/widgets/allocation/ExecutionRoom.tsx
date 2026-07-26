"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// ExecutionRoom — 실행 준비실 (Full Expansion P4)
//   목표 배분(Optimize 결과)으로의 리밸런싱 주문 차이·비용 추정·pre-trade 리스크·
//   승인 워크플로. v1은 준비실 — 실 주문·계좌 제어·자동매매 없음(지시서). 브로커
//   연결 전에는 paper_submitted 이후 자동 시뮬 없음(체결은 수동 입력).
//   한국 관례: 매수=빨강 · 매도=파랑 (bull/bear 손익색과 별개).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAllocation } from "./AllocationProvider";
import {
  executionApi, type CheckStatus, type ExecutionPlan, type OrderRow,
  type PlanStatus, type PreTrade, type SavedPlan,
} from "@/entities/execution/api";

const won = (n: number) => `₩${Math.round(n).toLocaleString("ko-KR")}`;
const eok = (n: number) => `${(n / 1e8).toFixed(2)}억`;

const STATUS_KO: Record<PlanStatus, string> = {
  draft: "초안", reviewed: "검토됨", approved: "승인됨", paper_submitted: "모의 제출",
  partially_filled: "부분 체결", filled: "체결 완료", cancelled: "취소됨",
  rejected: "반려됨", reconciled: "정산 완료",
};

// 버튼으로 노출하는 "전진" 전이(체결 driven인 partially_filled/filled 제외 — 그건 수동 체결 입력으로).
const FORWARD: Record<PlanStatus, PlanStatus[]> = {
  draft: ["reviewed", "cancelled"],
  reviewed: ["approved", "draft", "rejected", "cancelled"],
  approved: ["paper_submitted", "cancelled", "rejected"],
  paper_submitted: ["cancelled", "rejected"],
  partially_filled: ["reconciled", "cancelled"],
  filled: ["reconciled"],
  cancelled: [], rejected: [], reconciled: [],
};

function StatusBadge({ status }: { status: CheckStatus }) {
  return <span className={`as-exec-chk ${status}`}>{status === "pass" ? "통과" : status === "warning" ? "주의" : "차단"}</span>;
}

function CostChips({ o }: { o: OrderRow }) {
  const cb = o.cost_breakdown;
  return (
    <span className="as-exec-costchips num">
      <span title="수수료">수 {won(cb.commission)}</span>
      {cb.tax > 0 && <span title="증권거래세(매도)">세 {won(cb.tax)}</span>}
      <span title="스프레드">스 {won(cb.spread)}</span>
      {cb.impact > 0 && <span title="시장충격">충 {won(cb.impact)}</span>}
    </span>
  );
}

export function ExecutionRoom() {
  const { result, logEvent, markExecutionTouched, activeRunId } = useAllocation();
  const qc = useQueryClient();

  const [pv, setPv] = useState(100_000_000);              // 포트폴리오 평가액(원)
  const [turnoverCap, setTurnoverCap] = useState<string>("");   // 회전율 상한(%) — 비면 미적용
  const [costBudget, setCostBudget] = useState<string>("");     // 비용 예산(bp)
  const [partCap, setPartCap] = useState<string>("");           // 참여율 상한(%)
  const [restricted, setRestricted] = useState<string>("");     // 거래제한 종목(쉼표)
  const [preview, setPreview] = useState<{ plan: ExecutionPlan; pretrade: PreTrade } | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [planName, setPlanName] = useState("리밸런싱 실행 계획");

  const hasTarget = !!result && Object.keys(result.weights.optimized).length > 0;

  const reqBody = useMemo(() => {
    if (!result) return null;
    const limits: Record<string, number> = {};
    if (turnoverCap.trim()) limits.turnover_cap_pct = Number(turnoverCap);
    if (costBudget.trim()) limits.cost_budget_bp = Number(costBudget);
    if (partCap.trim()) limits.participation_cap_pct = Number(partCap);
    return {
      current_weights: result.weights.current,
      target_weights: result.weights.optimized,
      portfolio_value: pv,
      restricted: restricted.split(",").map((s) => s.trim()).filter(Boolean),
      limits,
    };
  }, [result, pv, turnoverCap, costBudget, partCap, restricted]);

  const previewMut = useMutation({
    mutationFn: () => executionApi.preview(reqBody!),
    onSuccess: (d) => {
      setPreview({ plan: d.plan, pretrade: d.pretrade });
      markExecutionTouched();
      logEvent(`실행 계획 산출 — 주문 ${d.plan.summary.n_orders}건 · 회전율 ${d.plan.summary.turnover_pct}%`);
    },
  });

  const saveMut = useMutation({
    mutationFn: () => executionApi.save({ ...reqBody!, name: planName, run_id: activeRunId }),
    onSuccess: (d) => {
      if (d.saved && d.plan_id) {
        setSavedId(d.plan_id);
        logEvent(`실행 계획 저장 — ${planName} (draft)`);
        qc.invalidateQueries({ queryKey: ["execution", "plans"] });
      } else {
        logEvent("실행 계획 저장 실패 — DB 미가용");
      }
    },
  });

  const planQ = useQuery({
    queryKey: ["execution", "plan", savedId],
    queryFn: () => executionApi.get(savedId!),
    enabled: !!savedId,
  });

  const transitionMut = useMutation({
    mutationFn: (to: PlanStatus) => executionApi.transition(savedId!, to),
    onSuccess: (r, to) => {
      if (r.ok) logEvent(`상태 전이 — ${STATUS_KO[to]}`);
      else logEvent(`전이 거부 — ${r.reason ?? ""}`);
      qc.invalidateQueries({ queryKey: ["execution", "plan", savedId] });
      qc.invalidateQueries({ queryKey: ["execution", "plans"] });
    },
  });

  const fillsMut = useMutation({
    mutationFn: () => {
      const plan = planQ.data?.plan;
      const fills = (plan?.orders ?? []).map((o) => ({
        stock_code: o.stock_code, filled_qty: o.quantity, avg_price: o.price_est,
      }));
      return executionApi.fills(savedId!, fills);
    },
    onSuccess: (r) => {
      logEvent(r.ok ? "수동 체결 입력 — 전량" : `체결 입력 거부 — ${r.reason ?? ""}`);
      qc.invalidateQueries({ queryKey: ["execution", "plan", savedId] });
    },
  });

  if (!hasTarget) {
    return (
      <section className="as-card">
        <div className="as-card-title">EXECUTION READINESS</div>
        <div className="as-empty">
          목표 배분이 필요합니다 — <b>05 OPTIMIZE</b>에서 최적 비중을 먼저 산출하세요.
          실행 준비실은 현재 보유 → 목표 배분의 <b>주문 차이·비용·pre-trade</b>를 점검하는 단계입니다.
        </div>
      </section>
    );
  }

  const plan = preview?.plan;
  const pretrade = preview?.pretrade;
  const saved: SavedPlan | undefined = planQ.data;

  return (
    <div className="as-exec">
      {/* ── 설정 + 산출 ── */}
      <section className="as-card">
        <div className="as-card-title">
          EXECUTION READINESS — 실행 준비실
          <span className="as-note-inline">v1: 오더 diff·비용·pre-trade·승인 — 실 주문·자동매매 없음</span>
        </div>
        <div className="as-exec-cfg">
          <label>포트폴리오 평가액
            <input className="num" type="number" min={1_000_000} step={1_000_000}
              value={pv} onChange={(e) => setPv(Math.max(1_000_000, Number(e.target.value) || 0))} />
            <span className="as-exec-hint num">{eok(pv)}</span>
          </label>
          <details className="aas-adv as-exec-limits">
            <summary>pre-trade 한도 (선택)</summary>
            <div className="as-exec-cfg">
              <label>회전율 상한 %<input className="num" type="number" placeholder="미적용" value={turnoverCap} onChange={(e) => setTurnoverCap(e.target.value)} /></label>
              <label>비용 예산 bp<input className="num" type="number" placeholder="미적용" value={costBudget} onChange={(e) => setCostBudget(e.target.value)} /></label>
              <label>참여율 상한 %<input className="num" type="number" placeholder="미적용" value={partCap} onChange={(e) => setPartCap(e.target.value)} /></label>
              <label className="as-exec-restr">거래제한 종목(쉼표)<input type="text" placeholder="예: 005930, 000660" value={restricted} onChange={(e) => setRestricted(e.target.value)} /></label>
            </div>
          </details>
          <button className="as-exec-run primary" disabled={previewMut.isPending} onClick={() => previewMut.mutate()}>
            {previewMut.isPending ? "산출 중…" : "실행 계획 산출"}
          </button>
        </div>
        <div className="as-note">
          현재 보유({Object.keys(result!.weights.current).length}종목) → 목표 배분({Object.keys(result!.weights.optimized).length}종목)
          의 리밸런싱 주문. 가격은 <b>최근 종가 추정</b>, 비용은 <b>사전 추정치</b> — 실 정산은 브로커 확정값.
        </div>
      </section>

      {plan && pretrade && (
        <>
          {/* ── 요약 KPI ── */}
          <section className="as-exec-kpis">
            <div className="as-exec-kpi"><span className="k">주문</span><b className="num">{plan.summary.n_orders}</b><em className="num">매수 {plan.summary.n_buy} · 매도 {plan.summary.n_sell}</em></div>
            <div className="as-exec-kpi"><span className="k">회전율</span><b className="num">{plan.summary.turnover_pct}%</b><em className="num">양방향 명목</em></div>
            <div className="as-exec-kpi"><span className="k">추정 비용</span><b className="num">{plan.summary.est_cost_bp}bp</b><em className="num">{won(plan.summary.est_cost)}</em></div>
            <div className="as-exec-kpi"><span className="k">순현금 변화</span><b className="num" style={{ color: plan.summary.net_cash_change >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{plan.summary.net_cash_change >= 0 ? "+" : ""}{eok(plan.summary.net_cash_change)}</b><em className="num">매도−매수(비용 별도)</em></div>
            <div className={`as-exec-kpi verdict ${pretrade.overall}`}><span className="k">PRE-TRADE</span><b>{pretrade.overall === "pass" ? "통과" : pretrade.overall === "warning" ? "주의" : "차단"}</b><em className="num">차단 {pretrade.n_block} · 주의 {pretrade.n_warning}</em></div>
          </section>

          <div className="as-exec-grid">
            {/* ── 오더 diff 테이블 ── */}
            <section className="as-card as-exec-orders">
              <div className="as-card-title">ORDER DIFF — 리밸런싱 주문 <span className="as-note-inline">매수 <span className="as-exec-buy">빨강</span> · 매도 <span className="as-exec-sell">파랑</span> (한국 관례)</span></div>
              {plan.orders.length === 0 ? (
                <div className="as-empty">주문 없음 — 현재 보유가 목표와 일치(수량 단위 내).</div>
              ) : (
                <div className="as-exec-tablewrap">
                  <table className="as-metrics as-exec-table">
                    <thead>
                      <tr>
                        <th>#</th><th>종목</th><th>구분</th><th>비중 변화</th><th>수량</th><th>추정가</th><th>금액</th><th>참여율</th><th>비용</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plan.orders.map((o) => (
                        <tr key={o.stock_code} className={o.warnings.length ? "as-exec-warn-row" : ""}>
                          <td className="num">{o.priority}<span className="as-exec-stage num" title={`단계 ${o.stage}`}>·{o.stage}</span></td>
                          <td>{o.corp_name}<span className="as-exec-code num">{o.stock_code}</span></td>
                          <td><span className={o.side === "buy" ? "as-exec-buy" : "as-exec-sell"}>{o.side === "buy" ? "매수" : "매도"}</span></td>
                          <td className="num">{o.cur_weight_pct}% → <b>{o.tgt_weight_pct}%</b></td>
                          <td className="num">{o.quantity.toLocaleString("ko-KR")}주</td>
                          <td className="num">{won(o.price_est)}<span className="as-exec-tick num" title="호가 단위">틱{o.tick_size}</span></td>
                          <td className="num">{won(o.notional)}</td>
                          <td className="num">{o.participation_pct != null ? `${o.participation_pct}%` : "—"}</td>
                          <td className="num">{o.cost_bp}bp<CostChips o={o} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {plan.orders.some((o) => o.warnings.length > 0) && (
                    <ul className="as-exec-warnlist">
                      {plan.orders.filter((o) => o.warnings.length).map((o) => (
                        <li key={o.stock_code}><b>{o.corp_name}</b>: {o.warnings.join(" · ")}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {plan.missing_price.length > 0 && (
                <div className="as-note">시세 미보유 {plan.missing_price.length}종목 — 주문 산출 제외(정직 결측): {plan.missing_price.join(", ")}</div>
              )}
            </section>

            {/* ── pre-trade + 비용 + 규칙 ── */}
            <aside className="as-exec-side">
              <section className="as-card">
                <div className="as-card-title">PRE-TRADE 리스크 <span className="as-note-inline">block 있으면 승인 불가 (§4)</span></div>
                <ul className="as-exec-checks">
                  {pretrade.checks.map((c) => (
                    <li key={c.name} className={c.status}>
                      <StatusBadge status={c.status} />
                      <span className="as-exec-chk-name">{c.name}</span>
                      <span className="as-exec-chk-detail num">{c.detail}</span>
                    </li>
                  ))}
                </ul>
                <div className="as-note">{pretrade.note}</div>
              </section>

              <section className="as-card">
                <div className="as-card-title">비용 분해 (사전 추정)</div>
                <table className="as-metrics">
                  <tbody>
                    <tr><td>수수료(양편)</td><td className="num">{won(plan.orders.reduce((a, o) => a + o.cost_breakdown.commission, 0))}</td></tr>
                    <tr><td>증권거래세(매도)</td><td className="num">{won(plan.orders.reduce((a, o) => a + o.cost_breakdown.tax, 0))}</td></tr>
                    <tr><td>스프레드</td><td className="num">{won(plan.orders.reduce((a, o) => a + o.cost_breakdown.spread, 0))}</td></tr>
                    <tr><td>시장충격(√참여율)</td><td className="num">{won(plan.orders.reduce((a, o) => a + o.cost_breakdown.impact, 0))}</td></tr>
                    <tr className="as-exec-total"><td><b>합계</b></td><td className="num"><b>{won(plan.summary.est_cost)}</b> · {plan.summary.est_cost_bp}bp</td></tr>
                  </tbody>
                </table>
              </section>

              <section className="as-card">
                <details className="aas-adv">
                  <summary>시장 규칙 스냅샷 (설정 계층)</summary>
                  <div className="as-note">{plan.rules.source}</div>
                  <table className="as-metrics">
                    <tbody>
                      <tr><td>수수료</td><td className="num">{plan.rules.commission_bp}bp</td></tr>
                      <tr><td>매도세</td><td className="num">{plan.rules.sell_tax_bp}bp</td></tr>
                      <tr><td>스프레드 기본</td><td className="num">{plan.rules.spread_bp}bp</td></tr>
                      <tr><td>매매 단위</td><td className="num">{plan.rules.board_lot}주</td></tr>
                      <tr><td>가격제한</td><td className="num">±{plan.rules.price_limit_pct}%</td></tr>
                    </tbody>
                  </table>
                </details>
              </section>
            </aside>
          </div>

          {/* ── 승인 워크플로 ── */}
          <section className="as-card as-exec-flow">
            <div className="as-card-title">승인 워크플로 <span className="as-note-inline">draft → reviewed → approved → paper_submitted → (수동 체결)</span></div>
            {!savedId ? (
              <div className="as-exec-save">
                <input type="text" value={planName} onChange={(e) => setPlanName(e.target.value)} placeholder="계획 이름" />
                <button className="primary" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>
                  {saveMut.isPending ? "저장 중…" : "계획 저장 (draft)"}
                </button>
                {saveMut.isSuccess && !saveMut.data.saved && <span className="as-exec-dbwarn">DB 미가용 — 저장되지 않음(미리보기만).</span>}
                {activeRunId && <span className="as-note-inline num">run: {activeRunId}</span>}
              </div>
            ) : saved ? (
              <div className="as-exec-wf">
                <div className="as-exec-wf-head">
                  <span className={`as-exec-status ${saved.status}`}>{STATUS_KO[saved.status]}</span>
                  <span className="num">{saved.name}</span>
                  {!(saved.pretrade?.can_approve ?? true) && <span className="as-exec-noapprove">pre-trade 차단 — 승인 불가</span>}
                </div>
                <div className="as-exec-wf-btns">
                  {FORWARD[saved.status].map((to) => {
                    const approveBlocked = to === "approved" && !(saved.pretrade?.can_approve ?? true);
                    return (
                      <button key={to} className={to === "approved" ? "primary" : ""}
                        disabled={transitionMut.isPending || approveBlocked}
                        title={approveBlocked ? "pre-trade block 항목을 해소해야 승인 가능 (§4)" : ""}
                        onClick={() => transitionMut.mutate(to)}>
                        {STATUS_KO[to]}로
                      </button>
                    );
                  })}
                  {(saved.status === "paper_submitted" || saved.status === "partially_filled") && (
                    <button disabled={fillsMut.isPending} onClick={() => fillsMut.mutate()}>수동 체결 입력 (전량)</button>
                  )}
                </div>
                <div className="as-note">모의 제출(paper_submitted) 이후 상태는 자동 진행되지 않습니다 — 체결은 수동 입력으로만 (브로커 미연결).</div>
                <details className="aas-adv as-exec-audit">
                  <summary>감사 로그 ({saved.audit.length})</summary>
                  <ul className="as-exec-auditlist">
                    {saved.audit.slice().reverse().map((a, i) => (
                      <li key={i}>
                        <span className="as-exec-audit-t num">{new Date(a.ts * 1000).toLocaleTimeString("ko-KR")}</span>
                        <span className="as-exec-audit-a">{a.action}{a.status ? ` → ${STATUS_KO[a.status as PlanStatus] ?? a.status}` : ""}</span>
                        {(a.note || a.detail) && <span className="as-exec-audit-d">{a.note || a.detail}</span>}
                      </li>
                    ))}
                  </ul>
                </details>
              </div>
            ) : (
              <div className="as-empty">계획 로드 중…</div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
