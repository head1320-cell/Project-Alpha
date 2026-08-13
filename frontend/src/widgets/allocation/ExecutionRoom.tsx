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
import { targetVersionApi, type TargetVersion } from "@/entities/allocation/targetVersion";
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

// ★한 글자 + 툴팁은 근거를 숨기는 것이다 (A6)★
// 예전에는 `수 / 세 / 스 / 충` 네 글자만 찍고 뜻은 전부 `title=` 에 있었다. 호버는
// 키보드·터치 사용자에게 존재하지 않으므로, 이 화면에서 비용의 **구성**은 사실상
// 읽을 수 없었다 — P3 가 ContextStrip 의 title 16개에서 고친 것과 같은 결함이고,
// 여기 있는 것이 주문을 승인할지 판단하는 근거라는 점에서 더 나쁘다.
// 8px 이던 글자는 §56 이 11px 로 올린다. 줄이 길어지므로 wrap 을 허용한다.
const COST_PARTS: [key: keyof OrderRow["cost_breakdown"], label: string][] = [
  ["commission", "수수료"], ["tax", "거래세"], ["spread", "스프레드"], ["impact", "시장충격"],
];

function CostChips({ o }: { o: OrderRow }) {
  const cb = o.cost_breakdown;
  return (
    <span className="as-exec-costchips num">
      {COST_PARTS.map(([k, label]) => {
        const v = cb[k];
        // 수수료·스프레드는 0 이어도 보여 준다(항상 부과된다). 세금·충격은 조건부라
        // 0 이면 "해당 없음" 이지 "0원을 냈다" 가 아니므로 줄 자체를 만들지 않는다.
        if ((k === "tax" || k === "impact") && !(v > 0)) return null;
        return <span key={k}>{label} {won(v)}</span>;
      })}
    </span>
  );
}

export function ExecutionRoom() {
  const { result, logEvent, markExecutionTouched, activeRunId, timingOverlay } = useAllocation();
  const qc = useQueryClient();

  const [pv, setPv] = useState(100_000_000);              // 포트폴리오 평가액(원)
  const [turnoverCap, setTurnoverCap] = useState<string>("");   // 회전율 상한(%) — 비면 미적용
  const [costBudget, setCostBudget] = useState<string>("");     // 비용 예산(bp)
  const [partCap, setPartCap] = useState<string>("");           // 참여율 상한(%)
  const [restricted, setRestricted] = useState<string>("");     // 거래제한 종목(쉼표)
  const [preview, setPreview] = useState<{ plan: ExecutionPlan; pretrade: PreTrade } | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);
  const [planName, setPlanName] = useState("리밸런싱 실행 계획");
  const [targetVersion, setTargetVersion] = useState<TargetVersion | null>(null);

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

  // ★R0: 주문 목표는 서버가 컴파일한 TargetPortfolioVersion 에서 나온다★
  // 예전에는 `result.weights.optimized` 를 그대로 보냈다. 그래서 04 TIMING 에서 노출을
  // 줄여도 **주문은 완전투자 그대로**였다 — 화면과 주문이 다른 목표를 향했다.
  // 이제 최적화 비중 + 오버레이를 서버에 보내 목표를 컴파일하고, 그 `tpv_id` 로 계획을
  // 만든다. 저장소가 죽어 `saved:false` 여도 **컴파일 결과(final_weights)는 돌아오므로**
  // 오버레이는 반영된다 — 목표가 옳은 것과 기록된 것은 다른 사실이다.
  const compileTarget = async () => {
    const tv = await targetVersionApi.create({
      base_weights: result!.weights.optimized,
      overlay: timingOverlay
        ? { exposure: timingOverlay.exposure, source: timingOverlay.source }
        : null,
      run_id: activeRunId ?? null,
    });
    return tv;
  };

  const previewMut = useMutation({
    mutationFn: async () => {
      const tv = await compileTarget();
      setTargetVersion(tv);
      return executionApi.preview(
        tv.tpv_id
          ? { ...reqBody!, tpv_id: tv.tpv_id, target_weights: tv.final_weights }
          : { ...reqBody!, target_weights: tv.final_weights },   // 미기록 — 목표는 그대로 옳다
      );
    },
    onSuccess: (d) => {
      setPreview({ plan: d.plan, pretrade: d.pretrade });
      markExecutionTouched();
      logEvent(`실행 계획 산출 — 주문 ${d.plan.summary.n_orders}건 · 회전율 ${d.plan.summary.turnover_pct}%`);
    },
  });

  const saveMut = useMutation({
    // 저장도 같은 목표를 쓴다 — 미리보기만 버전을 쓰고 저장이 원래 비중을 쓰면
    // 감사 기록과 실제 주문이 갈라진다(서버도 그 조합을 거부한다).
    mutationFn: async () => {
      const tv = targetVersion ?? (await compileTarget());
      return executionApi.save({
        ...reqBody!, target_weights: tv.final_weights,
        ...(tv.tpv_id ? { tpv_id: tv.tpv_id } : {}),
        name: planName, run_id: activeRunId,
      });
    },
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
  const approveBlocked = !!saved && !(saved.pretrade?.can_approve ?? true);

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
          <details className="as-adv as-exec-limits">
            <summary className="as-adv-s">pre-trade 한도 (선택)</summary>
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
        {/* ★무엇을 향해 주문하는지 화면이 말한다★ 오버레이가 걸렸는데 화면이 그 사실을
            말하지 않으면 사용자는 완전투자로 주문하는 줄 안다 — 그것이 R0 이 고친 결함이다. */}
        {targetVersion && (
          <div className="as-note as-exec-target">
            목표 버전{targetVersion.tpv_id ? ` ${targetVersion.tpv_id}` : " (미기록 — 저장소 미가용)"}
            {targetVersion.overlay
              ? ` · 타이밍 오버레이 노출 ${(targetVersion.overlay.exposure * 100).toFixed(0)}%`
              : " · 오버레이 없음"}
            {targetVersion.cash_weight > 0.01 && ` · 현금 ${targetVersion.cash_weight.toFixed(1)}%`}
          </div>
        )}
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
                    {/* `<th>` 에 scope 가 없었다 — 스크린리더가 9열 표에서 어떤 헤더가
                        어떤 셀에 붙는지 알 수 없다. A4-L2 가 alphalab 에서 한 것과 같다. */}
                    <thead>
                      <tr>
                        <th scope="col">#</th><th scope="col">종목</th><th scope="col">구분</th>
                        <th scope="col">비중 변화</th><th scope="col">수량</th><th scope="col">추정가</th>
                        <th scope="col">금액</th><th scope="col">참여율</th><th scope="col">비용</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plan.orders.map((o) => (
                        <tr key={o.stock_code} className={o.warnings.length ? "as-exec-warn-row" : ""}>
                          {/* `단계 N` · `호가 단위` 는 title= 안에 있었다. 뜻을 셀에 적는다. */}
                          <td className="num">{o.priority}<span className="as-exec-stage num">단계 {o.stage}</span></td>
                          {/* 종목 셀은 `<th scope="row">` 가 의미상 맞지만 `.as-metrics th`
                              가 우측정렬·muted 라 이름 열이 헤더처럼 보이게 된다. 표시를
                              위해 의미를 바꾸느니 `<td>` 로 두고 열 헤더만 정확히 한다. */}
                          <td>{o.corp_name}<span className="as-exec-code num">{o.stock_code}</span></td>
                          <td><span className={o.side === "buy" ? "as-exec-buy" : "as-exec-sell"}>{o.side === "buy" ? "매수" : "매도"}</span></td>
                          <td className="num">{o.cur_weight_pct}% → <b>{o.tgt_weight_pct}%</b></td>
                          <td className="num">{o.quantity.toLocaleString("ko-KR")}주</td>
                          <td className="num">{won(o.price_est)}<span className="as-exec-tick num">호가단위 {o.tick_size}</span></td>
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
                <details className="as-adv">
                  <summary className="as-adv-s">시장 규칙 스냅샷 (설정 계층)</summary>
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
                  {approveBlocked && <span className="as-exec-noapprove">pre-trade 차단 — 승인 불가</span>}
                </div>
                {/* ★비활성 버튼의 title 은 아무도 못 읽는다 (A6)★ 승인이 막힌 이유가
                    `disabled` 버튼의 `title` 에 있었다 — 브라우저 대부분이 비활성 요소에
                    호버 툴팁을 띄우지 않고, 키보드 포커스도 가지 않는다. 승인을 막는
                    사유는 이 화면에서 가장 중요한 문장이므로 보이는 줄로 내린다. */}
                {approveBlocked && (
                  <div className="as-exec-blockwhy" role="status">
                    pre-trade <b>block</b> 항목을 해소해야 승인할 수 있습니다 (§4) —
                    위 PRE-TRADE 리스크에서 <b>차단</b> 표시된 항목을 확인하세요.
                  </div>
                )}
                <div className="as-exec-wf-btns">
                  {FORWARD[saved.status].map((to) => (
                    <button key={to} className={to === "approved" ? "primary" : ""}
                      disabled={transitionMut.isPending || (to === "approved" && approveBlocked)}
                      onClick={() => transitionMut.mutate(to)}>
                      {STATUS_KO[to]}로
                    </button>
                  ))}
                  {(saved.status === "paper_submitted" || saved.status === "partially_filled") && (
                    <button disabled={fillsMut.isPending} onClick={() => fillsMut.mutate()}>수동 체결 입력 (전량)</button>
                  )}
                </div>
                <div className="as-note">모의 제출(paper_submitted) 이후 상태는 자동 진행되지 않습니다 — 체결은 수동 입력으로만 (브로커 미연결).</div>
                <details className="as-adv as-exec-audit">
                  <summary className="as-adv-s">감사 로그 ({saved.audit.length})</summary>
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
