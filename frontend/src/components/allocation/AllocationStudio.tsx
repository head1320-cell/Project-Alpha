"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AllocationStudio — 3-존 콕핏 오케스트레이터 (Two Sigma Venn 벤치마킹)
//   좌: 포트폴리오 빌더(검색·관심그룹·비중·저장 스터디)
//   중앙: 스테퍼 → INVESTMENT THESIS(뷰) + VIEW CONFIDENCE + OPTIMIZATION ENGINE
//         → EFFICIENT FRONTIER + ALLOCATION FLOW → 분석 탭(시나리오·MC·지표)
//   우: FACTOR X-RAY + RISK CONTRIBUTION + STRESS TEST
// 인터랙션 원칙(Gemini 리뷰 ②): 슬라이더 드래그 중 로컬만, 릴리스 시 재최적화.
// λ(위험회피)는 이미 받은 프론티어 30점에서 클라이언트 argmax — 백엔드 호출 0.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  allocationApi, type AllocationModel, type AllocationViewInput, type AnalyzeResult,
} from "@/lib/allocationApi";
import { saveStudy, type AllocationStudy } from "@/lib/allocationStorage";
import { PortfolioBuilder, equalize, type Holding } from "./PortfolioBuilder";
import { ViewBuilder, overallConfidence } from "./ViewBuilder";
import { ContextStrip } from "./ContextStrip";
import { ResearchTimeline, type TimelineEvent } from "./ResearchTimeline";
import {
  AllocationSankey, ConfidenceGauge, FactorXRayBars, FrontierChart,
  McHistogram, MetricsTable, RiskContribDonut, StressChart, fmtSign, lambdaOptimalIdx,
} from "./parts";

const MODELS: { id: AllocationModel; label: string }[] = [
  { id: "mvo", label: "MVO" },
  { id: "bl", label: "Black-Litterman" },
  { id: "risk_parity", label: "Risk Parity" },
  { id: "hrp", label: "HRP" },
  { id: "min_var", label: "Min Var" },
];

const COV_ONLY: AllocationModel[] = ["risk_parity", "hrp", "min_var"];

export default function AllocationStudio() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [views, setViews] = useState<AllocationViewInput[]>([]);
  const [model, setModel] = useState<AllocationModel>("bl");
  const [delta, setDelta] = useState(2.5);   // λ — 클라이언트 사이드 프론티어 선택에도 사용
  const [tau, setTau] = useState(0.05);
  const [result, setResult] = useState<AnalyzeResult | null>(null);
  const [scenario, setScenario] = useState<string>("rate_hike_200bp");
  const [bottomTab, setBottomTab] = useState<"scenario" | "mc" | "metrics">("scenario");
  const [studiesVersion, setStudiesVersion] = useState(0);
  const [saveName, setSaveName] = useState("");
  const [saveNote, setSaveNote] = useState("");
  const [showSave, setShowSave] = useState(false);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [explainCode, setExplainCode] = useState<string | null>(null);
  const lastReqRef = useRef<string>("");

  // Research Memory 1단계 — 실제 액션의 세션 로그 (영속화는 R2 로드맵)
  const logEvent = (msg: string) =>
    setTimeline((l) => [{ t: new Date().toTimeString().slice(0, 5), msg }, ...l].slice(0, 40));

  const holdingsMap = useMemo(() => {
    const m: Record<string, number> = {};
    holdings.forEach((h) => { m[h.code] = h.weight; });
    return m;
  }, [holdings]);
  const holdingsKey = useMemo(() => JSON.stringify(holdingsMap), [holdingsMap]);

  const analyzeMut = useMutation({
    mutationFn: allocationApi.analyze,
    onSuccess: (data) => { if (!data.error) setResult(data); },
  });

  const canRun = holdings.length >= 2;

  const runAnalyze = (over?: { model?: AllocationModel; tau?: number; views?: AllocationViewInput[] }) => {
    if (!canRun || analyzeMut.isPending) return;
    const req = {
      tickers: holdings.map((h) => h.code),
      weights: holdingsMap,
      views: (over?.views ?? views).filter((v) => v.assets.length > 0 && v.magnitude_pct > 0),
      model: over?.model ?? model,
      delta,
      tau: over?.tau ?? tau,
    };
    const key = JSON.stringify(req);
    if (key === lastReqRef.current) return; // 동일 요청 중복 방지
    lastReqRef.current = key;
    analyzeMut.mutate(req);
    logEvent(`재최적화 — ${req.model.toUpperCase()} · λ ${delta.toFixed(1)} · τ ${req.tau} · 뷰 ${req.views.length}개`);
  };

  // 팩터 X-ray / 스트레스 — holdings 기반 (analyze와 독립 lazy 로드)
  const xrayQ = useQuery({
    queryKey: ["allocation", "xray", holdingsKey],
    queryFn: () => allocationApi.factorXray(holdingsMap).catch(() => null),
    enabled: holdings.length >= 1,
  });
  const catalogQ = useQuery({
    queryKey: ["allocation", "stress-catalog"],
    queryFn: () => allocationApi.stressCatalog().catch(() => null),
  });
  const stressQ = useQuery({
    queryKey: ["allocation", "stress", holdingsKey, scenario],
    queryFn: () => allocationApi.stress(holdingsMap, scenario).catch(() => null),
    enabled: holdings.length >= 1 && !!scenario,
  });

  const conf = overallConfidence(views);
  const lamIdx = result ? lambdaOptimalIdx(result.frontier.curve, delta) : -1;
  const lamWeights = useMemo(() => {
    if (!result || lamIdx < 0) return null;
    const pt = result.frontier.curve[lamIdx];
    if (!pt) return null;
    const w: Record<string, number> = {};
    result.names.forEach((n) => { const v = pt[`w_${n}`]; if (typeof v === "number" && v > 0.05) w[n] = v; });
    return w;
  }, [result, lamIdx]);

  const loadStudy = (s: AllocationStudy) => {
    setHoldings(Object.entries(s.holdings).map(([code, weight]) => ({
      code, weight, name: s.names?.[code] || result?.labels?.[code] || code,
    })));
    setViews(s.views || []);
    setModel(s.model);
    setDelta(s.delta);
    setTau(s.tau);
    setResult(null);
    lastReqRef.current = "";
  };

  const doSave = () => {
    const names: Record<string, string> = {};
    holdings.forEach((h) => { names[h.code] = h.name; });
    saveStudy(saveName, { holdings: holdingsMap, names, views, model, delta, tau, note: saveNote });
    logEvent(`스터디 저장 — ${saveName.trim() || "이름 없음"}`);
    setStudiesVersion((v) => v + 1);
    setShowSave(false); setSaveName(""); setSaveNote("");
  };

  const scenarios = catalogQ.data?.scenarios || [];
  const pending = analyzeMut.isPending;
  const pickScenario = (id: string) => {
    setScenario(id);
    const label = scenarios.find((x) => x.id === id)?.label || id;
    logEvent(`시나리오 전환 — ${label}`);
  };

  return (
    <div className="as-root">
      {/* ── 컨텍스트: Current Regime + Canary (Research OS — 포지션의 '왜') ── */}
      <ContextStrip />

      {/* ── 스테퍼 ── */}
      <div className="as-stepper">
        {[["01", "Thesis & Views", "as-sec-views"], ["02", "Build Portfolio", "as-sec-build"], ["03", "Analysis", "as-sec-analysis"]].map(([n, label, anchor]) => (
          <button key={n} className="as-step" onClick={() => document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
            <span className="as-step-n num">{n}</span>{label}
          </button>
        ))}
        <div className="as-stepper-right">
          {result && (
            <span className="as-coverage num" title="수익률 행렬 커버리지">
              {(result.coverage as { source?: string }).source === "mock" && (
                <span className="as-badge" style={{ color: "#a16207", borderColor: "#a16207", marginRight: 6 }}>MOCK 데이터</span>
              )}
              {result.coverage.start} ~ {result.coverage.end} · {result.coverage.n_obs}일
              {result.excluded.length > 0 && ` · 제외 ${result.excluded.length}`}
            </span>
          )}
          <button className="as-save-btn" disabled={!canRun} onClick={() => setShowSave((s) => !s)}>스터디 저장</button>
        </div>
      </div>

      {showSave && (
        <div className="as-save-panel">
          <input className="as-input" placeholder="스터디 이름" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
          <input className="as-input" placeholder="의사결정 메모 (선택)" value={saveNote} onChange={(e) => setSaveNote(e.target.value)} />
          <button className="as-chip on" onClick={doSave}>저장</button>
          <button className="as-chip" onClick={() => setShowSave(false)}>취소</button>
        </div>
      )}

      <div className="as-grid">
        {/* ── 좌측 레일 ── */}
        <aside id="as-sec-build">
          <PortfolioBuilder holdings={holdings} studiesVersion={studiesVersion}
            onChange={(next) => { setHoldings(next); setResult(null); lastReqRef.current = ""; }}
            onLoadStudy={loadStudy} />
        </aside>

        {/* ── 중앙 ── */}
        <main className="as-center">
          {/* 상단 3패널: Thesis / Confidence / Engine */}
          <div className="as-top3" id="as-sec-views">
            <section className="as-card as-thesis">
              <div className="as-card-title">INVESTMENT THESIS <span className="as-note-inline">Black-Litterman 뷰</span></div>
              <ViewBuilder views={views} holdings={holdings}
                onChange={(next) => {
                  if (next.length > views.length) logEvent("테제(뷰) 추가");
                  else if (next.length < views.length) logEvent("테제(뷰) 삭제");
                  setViews(next);
                }} onCommit={() => runAnalyze()} />
              {result && !result.views_applied && views.length > 0 && (
                <div className="as-note">유효한 뷰 없음(대상 자산·크기 확인) — 시장균형으로 계산됨</div>
              )}
              {result && COV_ONLY.includes(result.model) && views.length > 0 && (
                <div className="as-note">뷰는 Black-Litterman 모델에서만 기대수익에 반영됩니다 (현재: 공분산 전용 모델)</div>
              )}
            </section>
            <section className="as-card">
              <div className="as-card-title">VIEW CONFIDENCE</div>
              <ConfidenceGauge value={conf} height={100} />
            </section>
            <section className="as-card">
              <div className="as-card-title">OPTIMIZATION ENGINE</div>
              <div className="as-seg as-models">
                {MODELS.map((m) => (
                  <button key={m.id} className={model === m.id ? "on" : ""}
                    onClick={() => { setModel(m.id); runAnalyze({ model: m.id }); }}>{m.label}</button>
                ))}
              </div>
              <label className="as-param">
                <span>Risk Aversion (λ) <b className="num">{delta.toFixed(1)}</b></span>
                <input type="range" min={0.5} max={8} step={0.1} value={delta}
                  onChange={(e) => setDelta(parseFloat(e.target.value))} />
                <em className="as-note-inline">드래그 = 프론티어 위 선택점 이동 (재계산 없음)</em>
              </label>
              <label className="as-param">
                <span>Uncertainty (τ) <b className="num">{tau.toFixed(3)}</b></span>
                <input type="range" min={0.01} max={0.2} step={0.005} value={tau}
                  onChange={(e) => setTau(parseFloat(e.target.value))}
                  onMouseUp={() => runAnalyze()} onTouchEnd={() => runAnalyze()} onKeyUp={() => runAnalyze()} />
              </label>
              <button className="as-run" disabled={!canRun || pending} onClick={() => { lastReqRef.current = ""; runAnalyze(); }}>
                {pending ? "최적화 중…" : "Re-optimize"}
              </button>
              {!canRun && <div className="as-note">자산 2개 이상 추가 시 실행 가능</div>}
              {analyzeMut.data?.error && <div className="as-err">{analyzeMut.data.message}</div>}
              {result && result.cap_missing.length > 0 && (
                <div className="as-note">시총 미보유 {result.cap_missing.length}자산은 중앙값 대체(캡가중 prior)</div>
              )}
            </section>
          </div>

          {/* 중단: 프론티어 + Sankey */}
          <div className="as-mid2">
            <section className={`as-card${pending ? " as-loading" : ""}`}>
              <div className="as-card-title">EFFICIENT FRONTIER
                {result?.views_applied && <span className="as-badge">BL 뷰 적용</span>}
              </div>
              {result ? <FrontierChart result={result} lam={delta} /> : <EmptyChart label="Re-optimize 실행 시 표시" h={280} />}
              {lamWeights && (
                <div className="as-lam-w">
                  <span className="as-note-inline">λ 선택점 비중:</span>
                  {Object.entries(lamWeights).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([c, w]) => (
                    <span key={c} className="as-chip sm">{result?.labels[c] || c} <b className="num">{w.toFixed(1)}%</b></span>
                  ))}
                </div>
              )}
            </section>
            <section className={`as-card${pending ? " as-loading" : ""}`}>
              <div className="as-card-title">ALLOCATION FLOW <span className="as-note-inline">시장 → 뷰 반영 → 최적화</span></div>
              {result ? <AllocationSankey result={result} /> : <EmptyChart label="가중치 흐름" h={220} />}
            </section>
          </div>

          {/* 하단: 분석 탭 */}
          <section className="as-card" id="as-sec-analysis">
            <div className="as-tabs">
              <button className={bottomTab === "scenario" ? "on" : ""} onClick={() => setBottomTab("scenario")}>SCENARIO ANALYSIS</button>
              <button className={bottomTab === "mc" ? "on" : ""} onClick={() => setBottomTab("mc")}>RETURN DISTRIBUTION</button>
              <button className={bottomTab === "metrics" ? "on" : ""} onClick={() => setBottomTab("metrics")}>SUMMARY METRICS</button>
            </div>
            {bottomTab === "scenario" && (
              <div className="as-scenario">
                <div className="as-scenario-list">
                  {scenarios.map((s) => (
                    <button key={s.id} disabled={!s.available} title={s.reason || s.description}
                      className={`as-scen${scenario === s.id ? " on" : ""}${!s.available ? " off" : ""}`}
                      onClick={() => pickScenario(s.id)}>
                      <span>{s.label}</span>
                      <em>{s.mode === "historical" ? (s.available ? "역사 리플레이" : "데이터 미보유") : "가상"}</em>
                    </button>
                  ))}
                </div>
                <div className="as-scenario-body">
                  {!holdings.length && <div className="as-empty">포트폴리오 구성 후 표시</div>}
                  {holdings.length > 0 && stressQ.isLoading && <div className="as-empty">시나리오 계산 중…</div>}
                  {stressQ.data && stressQ.data.mode === "hypothetical" && stressQ.data.available && (
                    <div>
                      <div className="as-shock-head">
                        포트폴리오 추정 충격 <b className="num" style={{ color: (stressQ.data.portfolio_shock_pct ?? 0) >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>
                          {fmtSign(stressQ.data.portfolio_shock_pct ?? 0, 1)}%</b>
                      </div>
                      <table className="as-metrics">
                        <thead><tr><th>종목</th><th>비중</th><th>충격</th><th>기여</th></tr></thead>
                        <tbody>
                          {(stressQ.data.rows || []).map((r) => (
                            <tr key={r.stock_code}>
                              <td>{r.corp_name}</td>
                              <td className="num">{r.weight_pct.toFixed(1)}%</td>
                              <td className="num" style={{ color: r.shock_pct >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(r.shock_pct, 1)}%</td>
                              <td className="num">{fmtSign(r.contribution_pct, 2)}%p</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <div className="as-note">{stressQ.data.note}</div>
                    </div>
                  )}
                  {stressQ.data && stressQ.data.mode === "historical" && stressQ.data.available && (
                    <StressChart result={stressQ.data} />
                  )}
                  {stressQ.data && !stressQ.data.available && (
                    <div className="as-empty">{stressQ.data.reason || "해당 시나리오 데이터 미보유"}</div>
                  )}
                </div>
              </div>
            )}
            {bottomTab === "mc" && (result ? <McHistogram mc={result.mc} /> : <EmptyChart label="Re-optimize 실행 시 표시" h={150} />)}
            {bottomTab === "metrics" && (result ? (
              <div>
                <MetricsTable summary={result.summary} />
                {result.summary.extra?.var_pct != null && (
                  <div className="as-note">히스토리컬 일간 VaR95 {result.summary.extra.var_pct}% · CVaR95 {result.summary.extra.cvar_pct}%
                    {result.summary.extra.information_ratio != null && ` · IR ${result.summary.extra.information_ratio}`}</div>
                )}
              </div>
            ) : <EmptyChart label="Re-optimize 실행 시 표시" h={150} />)}
          </section>
        </main>

        {/* ── 우측 레일 ── */}
        <aside className="as-right">
          <section className="as-card">
            <div className="as-card-title">FACTOR EXPOSURE <span className="as-note-inline">{xrayQ.data?.benchmark_label || "vs 유니버스"}</span></div>
            {xrayQ.data?.factors?.length ? <FactorXRayBars factors={xrayQ.data.factors} />
              : <div className="as-empty">{holdings.length ? (xrayQ.isLoading ? "계산 중…" : "팩터 데이터 부족") : "포트폴리오 구성 후 표시"}</div>}
            {xrayQ.data?.note && <div className="as-note">{xrayQ.data.note}</div>}
          </section>
          <section className="as-card">
            <div className="as-card-title">ROBUSTNESS <span className="as-note-inline">상시 스트레스</span></div>
            <select className="as-scen-mini" value={scenario} onChange={(e) => pickScenario(e.target.value)}>
              {scenarios.map((sc) => (
                <option key={sc.id} value={sc.id} disabled={!sc.available}>
                  {sc.label}{!sc.available ? " (데이터 미보유)" : ""}
                </option>
              ))}
            </select>
            {!holdings.length && <div className="as-empty">포트폴리오 구성 후 표시</div>}
            {holdings.length > 0 && stressQ.isLoading && <div className="as-empty">계산 중…</div>}
            {stressQ.data?.available && stressQ.data.mode === "hypothetical" && (
              <div className="as-robust-row">
                <span>추정 충격 <b className="num" style={{ color: (stressQ.data.portfolio_shock_pct ?? 0) >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(stressQ.data.portfolio_shock_pct ?? 0, 1)}%</b></span>
                <span className="as-note-inline">상세: 하단 SCENARIO ANALYSIS</span>
              </div>
            )}
            {stressQ.data?.available && stressQ.data.mode === "historical" && (
              <div className="as-robust-row">
                <span>최대낙폭 <b className="num" style={{ color: "var(--color-bear)" }}>{stressQ.data.max_dd_pct?.toFixed(1)}%</b></span>
                {stressQ.data.benchmark_max_dd_pct != null && <span>벤치 <b className="num">{stressQ.data.benchmark_max_dd_pct.toFixed(1)}%</b></span>}
                {stressQ.data.total_return_pct != null && <span>기간수익 <b className="num">{fmtSign(stressQ.data.total_return_pct, 1)}%</b></span>}
              </div>
            )}
            {stressQ.data && !stressQ.data.available && (
              <div className="as-note">{stressQ.data.reason || "데이터 미보유"}</div>
            )}
          </section>
          <section className="as-card">
            <div className="as-card-title">RISK CONTRIBUTION</div>
            {result ? <RiskContribDonut contributions={result.risk_contributions} labels={result.labels} />
              : <div className="as-empty">Re-optimize 실행 시 표시</div>}
          </section>
          <section className="as-card">
            <div className="as-card-title">OPTIMIZED WEIGHTS</div>
            {result ? (
              <div className="as-weights">
                {Object.entries(result.weights.optimized).sort((a, b) => b[1] - a[1]).map(([c, w]) => {
                  const mkt = result.flow.market[c] ?? 0;
                  const vw = result.flow.view_applied[c] ?? 0;
                  const open = explainCode === c;
                  return (
                    <React.Fragment key={c}>
                      <button className="as-wrow-btn" title="왜 이 비중인가 — 단계 분해"
                        onClick={() => setExplainCode(open ? null : c)}>
                        <span className="as-wrow-nm">{open ? "▾ " : "▸ "}{result.labels[c] || c}</span>
                        <div className="as-wrow-bar"><i style={{ width: `${Math.min(w, 100)}%` }} /></div>
                        <span className="num">{w.toFixed(1)}%</span>
                      </button>
                      {open && (
                        <div className="as-explain">
                          <div className="as-explain-step"><em>① Market Prior(캡가중)</em><b className="num">{mkt.toFixed(1)}%</b></div>
                          <div className="as-explain-step"><em>② User View(BL)</em><b className="num">{vw.toFixed(1)}%</b>
                            <span className="delta num" style={{ color: vw - mkt >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(vw - mkt, 1)}%p</span></div>
                          <div className="as-explain-step"><em>③ Optimizer·제약(long-only)</em><b className="num">{w.toFixed(1)}%</b>
                            <span className="delta num" style={{ color: w - vw >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{fmtSign(w - vw, 1)}%p</span></div>
                          <div className="as-explain-road">Regime·Factor 단계 분해는 R2(레짐 연동 prior) 로드맵</div>
                        </div>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            ) : <div className="as-empty">Re-optimize 실행 시 표시</div>}
          </section>
          <section className="as-card">
            <div className="as-card-title">RESEARCH TIMELINE <span className="as-note-inline">세션 기록</span></div>
            <ResearchTimeline events={timeline} />
          </section>
        </aside>
      </div>
    </div>
  );
}

function EmptyChart({ label, h }: { label: string; h: number }) {
  return <div className="as-empty" style={{ height: h, display: "flex", alignItems: "center", justifyContent: "center" }}>{label}</div>;
}
