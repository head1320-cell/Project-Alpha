"use client";
// 02 ALPHA LAB — 알파 표현식 작성·lint·IC/ICIR 검증·레지스트리 (Full Expansion P2).
// 좌: 표현식 에디터(필드/함수 칩 + lint) + 슬리브 템플릿·레지스트리(상태 배지·승격)
// 우: 검증 리포트(IC·ICIR·t·Hit·Decay + 분위 막대 + 롱숏 곡선 + IS/OOS + 정직 노트)
//    + "상위 종목 → 포트폴리오" 브릿지(01 Construct와 연결).
import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  alphaApi, type AlphaDef, type AlphaStatus, type AlphaValidationReport, type LintResult,
} from "@/lib/alphaApi";
import { equalize } from "@/components/allocation/PortfolioBuilder";
import { useAllocation } from "@/components/allocation/AllocationProvider";
import { AutoAlphaLab } from "@/components/allocation/AutoAlphaLab";

const STATUS_LABEL: Record<AlphaStatus, string> = {
  draft: "초안", experimental: "실험", validated: "검증됨", approved: "승인", retired: "폐기",
};
const STATUS_NEXT: Partial<Record<AlphaStatus, AlphaStatus>> = {
  draft: "experimental", experimental: "validated", validated: "approved",
};
const UNIVERSES: [string, string][] = [
  ["kospi50", "KOSPI 50"], ["kospi200", "KOSPI 200"], ["kosdaq150", "KOSDAQ 150"],
];

function LintBadges({ lint }: { lint: LintResult | null }) {
  if (!lint) return null;
  if (!lint.issues.length) return <div className="as-note" style={{ color: "var(--color-bull)" }}>✓ lint 통과 — 이슈 없음</div>;
  return (
    <div className="as-al-lint">
      {lint.issues.map((i, k) => (
        <div key={k} className={`as-al-lint-item ${i.level}`}>
          <b>{i.level.toUpperCase()}</b> {i.message}
        </div>
      ))}
    </div>
  );
}

function QuantileBars({ q }: { q: { n: number; ann_return_pct: (number | null)[]; monotonicity: number | null } }) {
  const vals = q.ann_return_pct.map((v) => v ?? 0);
  const maxAbs = Math.max(...vals.map(Math.abs), 1);
  return (
    <div>
      <div className="as-al-qbars">
        {vals.map((v, i) => (
          <div key={i} className="as-al-qcol" title={`Q${i + 1}: 연 ${v}%`}>
            <div className="as-al-qbar" style={{
              height: `${Math.abs(v) / maxAbs * 64}px`,
              background: v >= 0 ? "var(--color-bull)" : "var(--color-bear)",
              alignSelf: v >= 0 ? "flex-end" : "flex-start",
            }} />
            <span className="num">Q{i + 1}</span>
          </div>
        ))}
      </div>
      <div className="as-note num">분위별 연수익(저→고) · 모노토닉 {q.monotonicity ?? "—"}</div>
    </div>
  );
}

function LsCurve({ curve }: { curve: number[] }) {
  if (curve.length < 3) return null;
  const W = 560, H = 120;
  const min = Math.min(...curve), max = Math.max(...curve);
  const rng = max - min || 1;
  const pts = curve.map((v, i) =>
    `${(i / (curve.length - 1)) * W},${H - ((v - min) / rng) * H}`).join(" ");
  const up = curve[curve.length - 1] >= curve[0];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 120, borderBottom: "1px solid var(--t-border)", borderLeft: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={up ? "var(--color-bull)" : "var(--color-bear)"} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function AlphaLabStage() {
  const router = useRouter();
  const { setHoldingsReset, markAlphaTouched, logEvent } = useAllocation();
  const [expr, setExpr] = useState("zscore(mom_6m) - zscore(vol_60d)");
  const [universe, setUniverse] = useState("kospi50");
  const [months, setMonths] = useState(24);
  const [lint, setLint] = useState<LintResult | null>(null);
  const [report, setReport] = useState<AlphaValidationReport | null>(null);
  const [alphaName, setAlphaName] = useState("");
  const [selAlpha, setSelAlpha] = useState<string | null>(null);
  const [promoteNote, setPromoteNote] = useState("");
  const [regMsg, setRegMsg] = useState<string | null>(null);

  const fieldsQ = useQuery({ queryKey: ["alpha", "fields"], queryFn: () => alphaApi.fields().catch(() => null) });
  const regQ = useQuery({ queryKey: ["alpha", "registry"], queryFn: () => alphaApi.registry().catch(() => null) });
  const alphas: AlphaDef[] = regQ.data?.alphas ?? [];

  const lintMut = useMutation({
    mutationFn: () => alphaApi.lint(expr),
    onSuccess: (d) => setLint(d),
  });
  const valMut = useMutation({
    mutationFn: () => alphaApi.validate({
      expr, universe, months, alpha_id: selAlpha ?? undefined, record_run: true,
    }),
    onSuccess: (d) => {
      setReport(d);
      if (!d.error) {
        markAlphaTouched();
        logEvent(`알파 검증 — IC ${d.ic?.mean ?? "—"} · ${expr.slice(0, 40)}`);
        if (selAlpha) regQ.refetch();
      }
    },
  });
  const saveMut = useMutation({
    mutationFn: () => alphaApi.upsert({
      alpha_id: selAlpha ?? undefined, name: alphaName.trim() || expr.slice(0, 40), expr, universe,
    }),
    onSuccess: (d) => {
      if (d.error) { setRegMsg(d.message ?? "저장 실패"); setLint(d.lint ?? null); return; }
      setRegMsg(null);
      setSelAlpha(d.alpha?.alpha_id ?? null);
      markAlphaTouched();
      logEvent(`알파 저장 — ${d.alpha?.name}`);
      regQ.refetch();
    },
  });

  const pickAlpha = (a: AlphaDef) => {
    setSelAlpha(a.alpha_id);
    setAlphaName(a.name);
    if (a.expr) setExpr(a.expr);
    setLint(null);
    setReport(null);
  };
  const doPromote = async (a: AlphaDef) => {
    const next = STATUS_NEXT[a.status];
    if (!next) return;
    const res = await alphaApi.promote(a.alpha_id, next, promoteNote).catch(() => null);
    if (!res) { setRegMsg("승격 요청 실패"); return; }
    setRegMsg(res.ok ? null : res.reason ?? "승격 불가");
    if (res.ok) { setPromoteNote(""); regQ.refetch(); }
  };

  const applyTop = () => {
    const top = (report?.latest_scores_top ?? []).slice(0, 10);
    if (top.length < 2) return;
    setHoldingsReset(equalize(top.map((t) => ({ code: t.ticker, name: t.name, weight: 0 }))));
    logEvent(`알파 상위 ${top.length}종목 → 포트폴리오`);
    router.push("/allocation/construct");
  };

  const ic = report && !report.error ? report.ic : null;

  return (
    <div className="as-ws2">
      {/* ── 좌: 에디터 + 레지스트리 ── */}
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">ALPHA EXPRESSION <span className="as-note-inline">크로스섹션 결합 — rank/zscore/sector_neutralize</span></div>
          <textarea className="as-input as-al-expr" rows={3} value={expr}
            onChange={(e) => { setExpr(e.target.value); setLint(null); }} spellCheck={false} />
          <div className="as-al-chips">
            {(fieldsQ.data?.fields ?? []).map((f) => (
              <button key={f.id} className={`as-chip sm${f.family === "fund" ? " as-al-fund" : ""}`}
                title={`${f.label} — ${f.desc}`} onClick={() => setExpr((x) => x + (x.trim() ? " + " : "") + f.id)}>
                {f.id}
              </button>
            ))}
          </div>
          <div className="as-al-chips">
            {(fieldsQ.data?.functions ?? []).map((f) => (
              <button key={f.id} className="as-chip sm" title={f.desc}
                onClick={() => setExpr((x) => `${f.id}(${x.trim() || "mom_6m"})`)}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="as-wl-row">
            <select className="as-fb-add" value={universe} onChange={(e) => setUniverse(e.target.value)}>
              {UNIVERSES.map(([id, l]) => <option key={id} value={id}>{l}</option>)}
            </select>
            <select className="as-fb-add" value={months} onChange={(e) => setMonths(parseInt(e.target.value))}>
              {[12, 24, 36].map((m) => <option key={m} value={m}>{m}개월</option>)}
            </select>
            <button className="as-chip" onClick={() => lintMut.mutate()} disabled={lintMut.isPending}>Lint</button>
            <button className="as-fb-apply" onClick={() => valMut.mutate()} disabled={valMut.isPending || !expr.trim()}>
              {valMut.isPending ? "검증 중…" : "검증 실행 →"}
            </button>
          </div>
          <LintBadges lint={lint} />
        </section>

        <section className="as-card">
          <div className="as-card-title">ALPHA REGISTRY <span className="as-note-inline">{alphas.length}개 · 슬리브 템플릿 포함 · draft→…→approved</span></div>
          <div className="as-rr-record">
            <input className="as-input" placeholder="알파 이름 (저장/수정)" value={alphaName}
              onChange={(e) => setAlphaName(e.target.value)} />
            <button className="as-fb-apply" onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !expr.trim()}>
              {selAlpha ? "수정 저장" : "레지스트리에 저장"}
            </button>
          </div>
          {selAlpha && (
            <div className="as-note">
              선택: <b>{alphas.find((a) => a.alpha_id === selAlpha)?.name ?? selAlpha}</b>
              <button className="as-chip sm" style={{ marginLeft: 6 }} onClick={() => { setSelAlpha(null); setAlphaName(""); }}>선택 해제</button>
            </div>
          )}
          {regMsg && <div className="as-err">{regMsg}</div>}
          {alphas.map((a) => (
            <div key={a.alpha_id} className={`as-al-item${selAlpha === a.alpha_id ? " on" : ""}`}>
              <button className="as-al-pick" onClick={() => pickAlpha(a)} title={a.description || a.expr}>
                <span className="as-al-name">
                  {a.name}
                  {a.is_template && <em className="as-al-tpl">TPL</em>}
                  <em className="num as-al-ver">v{a.version}</em>
                </span>
                <span className={`as-al-status s-${a.status}`}>{STATUS_LABEL[a.status]}</span>
              </button>
              {STATUS_NEXT[a.status] && !a.is_template && (
                <button className="as-chip sm" title={`→ ${STATUS_LABEL[STATUS_NEXT[a.status]!]} 승격`}
                  onClick={() => doPromote(a)}>↑ {STATUS_LABEL[STATUS_NEXT[a.status]!]}</button>
              )}
              {!a.is_template && (
                <button className="as-x" title="삭제"
                  onClick={() => alphaApi.remove(a.alpha_id).then(() => regQ.refetch()).catch(() => {})}>×</button>
              )}
            </div>
          ))}
          <input className="as-input" placeholder="승인 노트 (approved 승격 시 필수)" value={promoteNote}
            onChange={(e) => setPromoteNote(e.target.value)} style={{ marginTop: 6 }} />
          <div className="as-note">템플릿 6종은 정직 라벨(데이터 미보유·프록시)을 설명에 명시. validated 승격은 검증 run 필수.</div>
        </section>
      </aside>

      {/* ── 우: 검증 리포트 ── */}
      <main className="as-center">
        <section className={`as-card${valMut.isPending ? " as-loading" : ""}`}>
          <div className="as-card-title">VALIDATION REPORT
            {report?.run_id && <span className="as-note-inline num">run: {report.run_id}</span>}
          </div>
          {!report && !valMut.isPending && (
            <div className="as-empty">표현식을 작성하고 <b>검증 실행</b>을 누르면 IC/ICIR·분위·롱숏 리포트가 표시됩니다.</div>
          )}
          {valMut.isPending && <div className="as-empty">월간 리밸런스 시뮬레이션 중… (유니버스·기간에 따라 수십 초)</div>}
          {report?.error && <div className="as-err">{report.message}</div>}
          {report && !report.error && ic && (
            <>
              <div className="as-al-kpis">
                <div className="as-al-kpi"><em>Rank IC</em><b className="num" style={{ color: (ic.mean ?? 0) > 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{ic.mean}</b></div>
                <div className="as-al-kpi"><em>ICIR</em><b className="num">{ic.icir ?? "—"}</b></div>
                <div className="as-al-kpi"><em>t-stat</em><b className="num">{ic.t_stat ?? "—"}</b></div>
                <div className="as-al-kpi"><em>Hit</em><b className="num">{ic.hit_rate ?? "—"}%</b></div>
                <div className="as-al-kpi"><em>회전율</em><b className="num">{report.turnover_proxy ?? "—"}</b></div>
                <div className="as-al-kpi"><em>기간</em><b className="num">{report.n_periods}M</b></div>
              </div>
              <table className="as-metrics">
                <thead><tr><th>Decay</th><th className="num">1M</th><th className="num">2M</th><th className="num">3M</th><th>IS/OOS ({report.is_oos?.split})</th><th className="num">IS</th><th className="num">OOS</th></tr></thead>
                <tbody><tr>
                  <td>IC</td>
                  <td className="num">{report.decay?.["1m"] ?? "—"}</td>
                  <td className="num">{report.decay?.["2m"] ?? "—"}</td>
                  <td className="num">{report.decay?.["3m"] ?? "—"}</td>
                  <td>IC</td>
                  <td className="num">{report.is_oos?.is_ic ?? "—"}</td>
                  <td className="num">{report.is_oos?.oos_ic ?? "—"}</td>
                </tr></tbody>
              </table>
              {report.quantiles && <QuantileBars q={report.quantiles} />}
              <div className="as-card-title" style={{ marginTop: 10 }}>LONG-SHORT (Q{report.quantiles?.n}−Q1)
                <span className="as-note-inline num">
                  {report.long_short?.total_return_pct}% · Sharpe {report.long_short?.sharpe ?? "—"} · MDD {report.long_short?.mdd_pct}%
                </span>
              </div>
              {report.long_short && <LsCurve curve={report.long_short.curve} />}
              <div className="as-note num">
                유니버스 {report.universe_size} · 평균 커버리지 {report.avg_coverage} · {report.period_start} ~ {report.period_end}
              </div>
              {(report.notes ?? []).map((n, i) => <div key={i} className="as-note">• {n}</div>)}
            </>
          )}
        </section>

        {report && !report.error && (report.latest_scores_top?.length ?? 0) > 0 && (
          <section className="as-card">
            <div className="as-card-title">최신 시점 상위 종목
              <button className="as-fb-apply" onClick={applyTop}>상위 10종목 → 포트폴리오</button>
            </div>
            <div className="as-sl-holds">
              {(report.latest_scores_top ?? []).slice(0, 12).map((t) => (
                <span key={t.ticker} className="as-sl-hold" title={`score ${t.score}`}>
                  {t.name}<b className="num"> {t.score}</b>
                </span>
              ))}
            </div>
            <div className="as-note">알파 점수 상위 종목을 균등가중으로 01 Construct에 적재 — 이후 최적화·스트레스는 동일 파이프라인.</div>
          </section>
        )}

        {/* P6 실험 — AutoAlpha 후보 생성 샌드박스 (자동 채택 금지) */}
        <AutoAlphaLab onUseExpr={(e) => { setExpr(e); setLint(null); markAlphaTouched(); }} />
      </main>
    </div>
  );
}
