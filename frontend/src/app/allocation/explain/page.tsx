"use client";
// Attribution Workspace (Full Expansion P5) — Explain을 Attribution으로 재정의.
//   "왜 좋아 보이나"가 아니라 결정 시점 사전 기대 vs 사후 실측 비교.
//   런(ResearchRun) 기록이 있어야 결정 시점이 고정됨 → 없으면 기록 유도.
//   기존 ex-ante 비중 분해(Market→BL→Optimizer)는 보조 섹션으로 보존.
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { attributionApi, type AttributionReport, type Basis } from "@/entities/attribution/api";
import { researchApi, type ResearchRunSummary } from "@/entities/research/api";
import { CorrelationMini, RiskContribDonut, fmtSign } from "@/widgets/allocation/parts";
import { EvidenceBadge } from "@/shared/ui/evidence";

function BasisTag({ b }: { b: Basis }) {
  const ko = b === "real" ? "실측" : b === "mock" ? "합성" : "미측정";
  return <span className={`as-attr-basis ${b}`}>{ko}</span>;
}
const pct = (v: number | null | undefined, d = 2) => (v == null ? "—" : `${fmtSign(v, d)}%`);

const DAY = 86_400;
const iso = (d: Date) => d.toISOString().slice(0, 10);

/** 런의 결정일과, 선택된 기준일까지의 경과일. 경과 0일이면 잴 구간이 없다. */
function runMeta(r: ResearchRunSummary, asOf: string) {
  const decided = new Date(r.created_at * 1000);
  const end = asOf ? new Date(`${asOf}T00:00:00Z`) : new Date();
  const days = Math.max(0, Math.floor((end.getTime() / 1000 - r.created_at) / DAY));
  return { date: iso(decided), days };
}

// ═══════════════════════════════════════════════════════════════════════════════
// RunPicker — 무엇을, 어느 시점까지 재는가 (A7-4)
// ─────────────────────────────────────────────────────────────────────────────
// ★07 은 정직했지만 닿을 수 있는 것도 못 닿고 있었다★
// `compute_attribution(run, as_of=...)` 은 처음부터 기준일을 받았다. 그런데 라우트가
// 넘기지 않았고, 화면은 늘 `activeRunId` — **오늘 만든 런** — 만 봤다. 그래서
// `2026-08-07 → 2026-08-07 · 0일` 이 되고, 0일 구간의 실현수익은 계산할 수 없으니
// 모든 사후 항목이 미측정으로 보였다. 데이터가 없어서가 아니라 **고를 방법이
// 없어서** 였다. 경과일이 있는 런을 고르면 수익·초과수익·사후 변동성·종목별 기여가
// 그 자리에서 실측이 된다.
//
// 여전히 구조적으로 막힌 것은 그대로 미측정이다 — Brinson 은 벤치마크 구성종목
// 가중이 저장소에 없고, 슬리피지·비용은 연결된 실체결이 없다. 프록시로 채우지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════
function RunPicker({
  runs, runId, asOf, onRun, onAsOf,
}: {
  runs: ResearchRunSummary[];
  runId: string | null;
  asOf: string;
  onRun: (id: string) => void;
  onAsOf: (v: string) => void;
}) {
  const today = iso(new Date());
  // 활성 런이 목록 밖일 수 있다(최근 30건만 받는다) — 그러면 select 가 빈 칸이 되어
  // "아무것도 안 골랐다" 로 보인다. 없는 항목은 만들어서 채운다.
  const known = runs.some((r) => r.run_id === runId);
  const picked = runs.find((r) => r.run_id === runId);

  return (
    <section className="as-card as-attr-pick">
      <div className="as-card-title">
        측정 대상 — 결정(런)과 기준일
        <span className="as-note-inline">
          결정일부터 기준일까지가 사후 구간입니다 — 경과 0일이면 잴 구간이 없습니다
        </span>
      </div>
      <div className="as-attr-pick-row">
        <label className="as-attr-pick-l" htmlFor="as-attr-run">결정(런)</label>
        <select id="as-attr-run" className="as-attr-pick-run" value={runId ?? ""}
          onChange={(e) => onRun(e.target.value)}>
          {!runId && <option value="">— 런을 고르세요 —</option>}
          {!known && runId && <option value={runId}>{runId} (현재 세션)</option>}
          {runs.map((r) => {
            const m = runMeta(r, asOf);
            return (
              <option key={r.run_id} value={r.run_id}>
                {m.date} · 경과 {m.days}일 · {r.kind}{r.name ? ` · ${r.name}` : ""}
              </option>
            );
          })}
        </select>

        <label className="as-attr-pick-l" htmlFor="as-attr-asof">기준일 (as-of)</label>
        <input id="as-attr-asof" type="date" className="as-attr-pick-asof num"
          value={asOf} max={today} onChange={(e) => onAsOf(e.target.value)} />
        {asOf
          ? <button type="button" className="as-attr-pick-reset" onClick={() => onAsOf("")}>오늘로</button>
          : <span className="as-note-inline">비우면 오늘</span>}
      </div>

      {/* 목록의 `경과 N일` 은 **고르기 위한 라벨**이지 측정값이 아니다. 실제 구간은
          서버가 재고(`rep.elapsed_days`), 0일일 때의 설명도 거기서 나온다 — 같은 것을
          두 곳에서 계산하면 언젠가 갈라진다. */}
      {picked && <div className="as-attr-pick-sel num">{picked.run_id}</div>}
    </section>
  );
}
const col = (v: number | null | undefined) => (v == null ? undefined : v >= 0 ? "var(--color-bull)" : "var(--color-bear)");

function AttributionView({ rep }: { rep: AttributionReport }) {
  const d = rep.decomposition;
  const rc = rep.risk_compare;
  return (
    <div className="as-attr">
      <div className="as-attr-head">
        <span className="as-attr-run num">{rep.run_id}</span>
        <span className="num">{rep.decision_date} → {rep.as_of} · {rep.elapsed_days}일</span>
        {rep.coverage.source === "mock" && <span className="as-wiz-mock">MOCK</span>}
        {!rep.coverage.has_expost && <span className="as-attr-warn">사후 데이터 없음 — 경과 시간·시세 부족(정직)</span>}
      </div>

      {/* ★0일이면 왜 미측정인지 그 자리에서 말한다 (A7-4)★
          표를 미측정으로 채워 놓고 침묵하면 사용자는 데이터가 없는 줄 안다 — 사실은
          잴 구간이 없는 것이다. 둘은 전혀 다른 상태이고, 뒤쪽은 런만 바꾸면 풀린다.
          경과일은 **서버가 잰 값**(`elapsed_days`)을 그대로 쓴다. */}
      {rep.elapsed_days === 0 && (
        <div className="as-note as-attr-zero" role="status">
          결정일과 기준일이 같습니다(<b className="num">경과 0일</b>). <b>실현수익을 계산할
          구간이 없어</b> 사후 항목이 전부 미측정입니다 — 데이터가 없어서가 아닙니다.
          위에서 경과일이 있는 런을 고르거나 기준일을 뒤로 옮기면 그대로 실측이 됩니다.
        </div>
      )}

      {/* 수익 / 초과수익 */}
      <div className="as-attr-cards">
        <div className="as-attr-card"><span className="k">포트폴리오 수익 <BasisTag b={rep.returns.basis} /></span>
          <b className="num" style={{ color: col(rep.returns.portfolio_pct) }}>{pct(rep.returns.portfolio_pct)}</b></div>
        <div className="as-attr-card"><span className="k">벤치({rep.returns.benchmark_label})</span>
          <b className="num" style={{ color: col(rep.returns.benchmark_pct) }}>{pct(rep.returns.benchmark_pct)}</b></div>
        <div className="as-attr-card"><span className="k">초과수익</span>
          <b className="num" style={{ color: col(rep.returns.excess_pct) }}>{pct(rep.returns.excess_pct)}</b></div>
      </div>

      {/* 사전 기대 vs 사후 실측 */}
      <section className="as-card">
        <div className="as-card-title">사전 기대 vs 사후 실측 <BasisTag b={rep.expected_vs_actual.basis} /></div>
        <table className="as-metrics">
          <tbody>
            <tr><td>기대수익 (기간환산, 연 {rep.expected_vs_actual.expected_return_annual_pct ?? "—"}%)</td>
              <td className="num">{pct(rep.expected_vs_actual.expected_return_pct)}</td></tr>
            <tr><td>실현수익</td><td className="num" style={{ color: col(rep.expected_vs_actual.actual_return_pct) }}>{pct(rep.expected_vs_actual.actual_return_pct)}</td></tr>
            <tr className="as-exec-total"><td><b>기대−실현 갭</b></td>
              <td className="num" style={{ color: col(rep.expected_vs_actual.gap_pct) }}><b>{pct(rep.expected_vs_actual.gap_pct)}</b></td></tr>
          </tbody>
        </table>
      </section>

      {/* 수익 분해 */}
      <section className="as-card">
        <div className="as-card-title">수익 분해 — 모델 알파·슬리피지·비용·잔차</div>
        <table className="as-metrics">
          <tbody>
            <tr><td>모델 알파 (사전 기대) <BasisTag b={d.basis.model_alpha} /></td><td className="num">{pct(d.model_alpha_pct)}</td></tr>
            <tr><td>실행 슬리피지 <BasisTag b={d.basis.slippage} /></td><td className="num">{pct(d.execution_slippage_pct, 3)}</td></tr>
            <tr><td>거래 비용 <BasisTag b={d.basis.cost} /></td><td className="num">{pct(d.cost_pct, 3)}</td></tr>
            <tr className="as-exec-total"><td><b>잔차 (설명 안 된 P&L)</b> <BasisTag b={d.basis.residual} /></td>
              <td className="num" style={{ color: col(d.residual_pct) }}><b>{pct(d.residual_pct)}</b></td></tr>
          </tbody>
        </table>
        <div className="as-note">{d.note}</div>
      </section>

      {/* 리스크 사전 vs 사후 */}
      <section className="as-card">
        <div className="as-card-title">리스크 — 사전 vs 사후 <BasisTag b={rc.basis} /></div>
        <table className="as-metrics">
          <thead><tr><th>지표</th><th>사전(ex-ante)</th><th>사후(ex-post)</th></tr></thead>
          <tbody>
            <tr><td>변동성(연)</td><td className="num">{rc.ex_ante.vol_pct ?? "—"}%</td><td className="num">{rc.ex_post.vol_pct ?? "—"}%</td></tr>
            <tr><td>VaR / 실현 베타</td><td className="num">{rc.ex_ante.var_pct ?? "—"}%</td><td className="num">{rc.ex_post.beta ?? "—"}</td></tr>
            <tr><td>CVaR</td><td className="num">{rc.ex_ante.cvar_pct ?? "—"}%</td><td className="num">—</td></tr>
          </tbody>
        </table>
        {rc.vol_gap_pct != null && <div className="as-note">변동성 갭(사후−사전): {fmtSign(rc.vol_gap_pct, 2)}%p</div>}
      </section>

      {/* 종목별 기여 */}
      {rep.contribution.assets.length > 0 && (
        <section className="as-card">
          <div className="as-card-title">종목별 기여 <BasisTag b={rep.contribution.basis} /></div>
          <table className="as-metrics">
            <thead><tr><th>종목</th><th>비중</th><th>수익</th><th>기여</th></tr></thead>
            <tbody>
              {rep.contribution.assets.map((a) => (
                <tr key={a.code}><td>{a.code}</td><td className="num">{a.weight_pct}%</td>
                  <td className="num" style={{ color: col(a.return_pct) }}>{pct(a.return_pct)}</td>
                  <td className="num" style={{ color: col(a.contribution_pct) }}>{pct(a.contribution_pct)}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* 의존도 + 체결품질 + Brinson(미측정) */}
      <div className="as-attr-cards2">
        <section className="as-card">
          <div className="as-card-title">과의존 분석 <BasisTag b={rep.dependency.basis} /></div>
          {rep.dependency.basis === "real" ? (
            <>
              <div className="num as-attr-dep">HHI {rep.dependency.hhi} · 유효종목수 {rep.dependency.effective_n}</div>
              <div className="num">최대기여 {rep.dependency.top_name} {rep.dependency.top_name_share_pct}%
                {rep.dependency.concentrated && <span className="as-attr-warn"> 과집중</span>}</div>
              <div className="as-note">{rep.dependency.note}</div>
            </>
          ) : <div className="as-empty">사후 데이터 필요</div>}
        </section>
        <section className="as-card">
          <div className="as-card-title">체결 품질 <BasisTag b={rep.fill_quality.basis} /></div>
          {rep.fill_quality.basis === "real" && rep.fill_quality.rows ? (
            <table className="as-metrics">
              <thead><tr><th>종목</th><th>체결가</th><th>목표가</th><th>슬리피지</th></tr></thead>
              <tbody>{rep.fill_quality.rows.map((r) => (
                <tr key={r.stock_code}><td>{r.stock_code}</td><td className="num">{r.avg_price.toLocaleString()}</td>
                  <td className="num">{r.target_price.toLocaleString()}</td>
                  <td className="num" style={{ color: col(r.slippage_bp == null ? null : -r.slippage_bp) }}>{r.slippage_bp ?? "—"}bp</td></tr>
              ))}</tbody>
            </table>
          ) : <div className="as-note">{rep.fill_quality.note}</div>}
        </section>
      </div>

      {/* ★Brinson 은 정직했지만 어휘가 달랐다 (A6)★ 사유를 note 로만 적어서
          "설명이 붙은 빈 카드" 로 읽혔다. 스튜디오의 나머지가 쓰는 unavailable 처리를
          쓰면 **측정할 수 없다** 는 뜻이 형태로 전달된다. 문구는 백엔드의 note 그대로 —
          여기서 사유를 새로 쓰면 서버가 아는 이유와 화면이 말하는 이유가 갈라진다. */}
      <section className="as-card">
        <div className="as-card-title">Brinson 효과 분해 (선택/배분/팩터/타이밍/헤지) <BasisTag b={rep.brinson_effects.basis} /></div>
        {rep.brinson_effects.basis === "real"
          ? <div className="as-note">{rep.brinson_effects.note}</div>
          : <EvidenceBadge kind="unavailable" reason={rep.brinson_effects.note}>산출 불가</EvidenceBadge>}
      </section>

      <div className="as-attr-link">
        {rep.journal_entry_id
          ? <span>연결된 저널: <b className="num">{rep.journal_entry_id}</b> (같은 run_id) — 09 JOURNAL에서 확인</span>
          : <span>이 결정에 연결된 저널 없음 — 09 JOURNAL에서 run_id {rep.run_id}로 기록하세요.</span>}
      </div>
    </div>
  );
}

export default function AttributionWorkspace() {
  const { result, activeRunId, recordRun, pending } = useAllocation();
  // 고른 런은 세션 상태다 — 이 화면에서 무엇을 보는지일 뿐, 리서치 컨텍스트의
  // 활성 런(`activeRunId`)을 바꾸지 않는다. 과거 결정을 들여다본다고 해서 지금
  // 작업 중인 런이 바뀌면 안 된다.
  const [picked, setPicked] = useState<string | null>(null);
  const [asOf, setAsOf] = useState("");

  const runsQ = useQuery({
    queryKey: ["research-runs", "attribution-picker"],
    // ★`catch` 로 빈 목록을 만들지 않는다 (R0-S)★ 저장소 장애를 "런 없음"으로 바꾸면
    // 07 은 "귀인할 런이 없다" 고 말하게 된다 — 기록은 멀쩡한데.
    queryFn: () => researchApi.list(undefined, 30),
  });
  const runs = runsQ.data?.runs ?? [];

  const runId = picked ?? activeRunId;
  const attrQ = useQuery({
    // 런이나 기준일이 바뀌면 리페치한다 — 페이지 리로드도 이동도 없다.
    queryKey: ["allocation", "attribution", runId, asOf],
    queryFn: () => attributionApi.get(runId!, asOf || undefined).catch(() => null),
    enabled: !!runId,
  });

  const picker = (
    <RunPicker runs={runs} runId={runId} asOf={asOf}
      onRun={(id) => setPicked(id || null)} onAsOf={setAsOf} />
  );

  // ★귀인은 현재 세션의 산물이 아니다 (A7-4)★ 예전에는 세 분기 모두 `activeRunId`
  // 하나만 봤다 — 즉 **이 세션에서 방금 기록한 런**만. 그래서 서버에 2주 전 런이
  // 있어도 화면에서 고를 수 없었고, 늘 경과 0일이라 전부 미측정이었다. 피커는
  // 결과 유무와 무관하게 런이 하나라도 있으면 나온다.
  const attrBody = (
    <>
      {(runs.length > 0 || runId) && picker}
      {runId && attrQ.isLoading && <div className="as-empty">Attribution 계산 중…</div>}
      {runId && attrQ.data && <AttributionView rep={attrQ.data} />}
      {runId && !attrQ.isLoading && !attrQ.data && (
        <div className="as-empty">Attribution을 불러오지 못했습니다 (DB 미가용일 수 있음).</div>
      )}
    </>
  );

  // ★세 분기가 서로 다른 모양이었다 (A6)★ 결과가 없을 때만 그리드 래퍼 없이
  // 벌거벗은 `.as-card` 를 반환하고 있었다. 그러면 이 스테이지는 상태에 따라 레이아웃이
  // 바뀌고, `.as-ws2` 에 걸린 스코프(§51·§55)도 이 분기에서만 적용되지 않는다.
  // 세 분기 모두 같은 껍데기를 쓴다.
  if (!result) {
    return (
      <div className="as-ws2 as-ws-exp">
        <main className="as-center">
          <section className="as-card">
            <div className="as-card-title">ATTRIBUTION</div>
            <div className="as-empty">먼저 <b>05 OPTIMIZE</b>에서 배분을 산출하세요. Attribution은 결정 시점(런)의 사전 기대와 사후 실측을 대조합니다.</div>
            {runs.length > 0 && (
              <div className="as-note">
                다만 <b>과거에 기록된 런</b>은 지금 바로 귀인할 수 있습니다 — 아래에서 고르세요.
              </div>
            )}
          </section>
          {attrBody}
        </main>
      </div>
    );
  }

  if (!activeRunId) {
    return (
      <div className="as-ws2 as-ws-exp">
        <main className="as-center">
          <section className="as-card">
            <div className="as-card-title">ATTRIBUTION — 결정 시점 고정 필요</div>
            <div className="as-empty">Attribution은 <b>결정 시점(ResearchRun)</b>을 기준으로 이후 실제 결과를 귀인합니다.
              현재 최적화 결과를 런으로 기록하면 결정일이 고정되고, 시간이 지나며 사후 실측이 채워집니다.</div>
            <button className="as-run" disabled={pending} onClick={() => recordRun("Attribution 결정 기록")}>
              {pending ? "기록 중…" : "이 결정을 런으로 기록 →"}
            </button>
            <div className="as-note">런 기록은 재현성 단위(run_id·데이터 스냅샷·코드 버전)를 서버에 영속합니다. DB 미가용 시 정직하게 실패 보고.</div>
          </section>
          {attrBody}
          <ExanteDecomp />
        </main>
      </div>
    );
  }

  return (
    <div className="as-ws2 as-ws-exp">
      <main className="as-center">{attrBody}</main>
      <aside className="as-center">
        <ExanteDecomp />
      </aside>
    </div>
  );
}

// 보조: 기존 ex-ante 비중 분해(Market Prior → BL → Optimizer) — 결정 "구성" 근거 보존
function ExanteDecomp() {
  const { result } = useAllocation();
  if (!result) return null;
  const rows = Object.entries(result.weights.optimized).sort((a, b) => b[1] - a[1]);
  return (
    <>
      <section className="as-card">
        <details className="as-adv">
          <summary className="as-adv-s">사전 비중 분해 (Market Prior → User View(BL) → Optimizer)</summary>
          <table className="as-metrics">
            <thead><tr><th>자산</th><th>① Market</th><th>② View(BL)</th><th>③ Optimized</th><th>리스크 기여</th></tr></thead>
            <tbody>
              {/* ★① Market / ② View(BL) 의 `?? 0` 을 걷어냈다 (A6-Z)★
                  A5 가 03 THESIS 의 VIEW EFFECT 에서 고친 것과 같은 쌍이다. 시장 사전분포나
                  BL 사후분포가 이 자산에 대해 없을 때 `0.0%` 를 찍으면, "시장이 이 자산을
                  0% 로 본다" 로 읽힌다. 없는 것은 없다고 쓴다 — WeightComparison·ViewEffect
                  가 쓰는 `.aas-cmp-na` 와 같은 처리다(세 번째 어휘를 만들지 않는다). */}
              {rows.map(([c, w]) => {
                const mkt = result.flow.market[c];
                const vw = result.flow.view_applied[c];
                const rcv = result.risk_contributions[c];
                const pctCell = (v: number | null | undefined) =>
                  v == null || !Number.isFinite(v)
                    ? <span className="aas-cmp-na">미계산</span>
                    : `${v.toFixed(1)}%`;
                return (
                  <tr key={c}><td>{result.labels[c] || c}</td>
                    <td className="num">{pctCell(mkt)}</td><td className="num">{pctCell(vw)}</td>
                    <td className="num"><b>{w.toFixed(1)}%</b></td>
                    <td className="num">{rcv != null ? `${rcv.toFixed(1)}%` : <span className="aas-cmp-na">미계산</span>}</td></tr>
                );
              })}
            </tbody>
          </table>
        </details>
      </section>
      <section className="as-card">
        <div className="as-card-title">RISK CONTRIBUTION</div>
        <RiskContribDonut contributions={result.risk_contributions} labels={result.labels} />
        <details className="as-adv">
          <summary className="as-adv-s">상관 구조 보기</summary>
          <CorrelationMini correlation={result.correlation} names={result.names} labels={result.labels} />
        </details>
      </section>
    </>
  );
}
