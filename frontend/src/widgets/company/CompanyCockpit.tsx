"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// CompanyCockpit — Company Analysis 프로덕션 (실데이터). 좌측 기업패널 + 7탭.
//   코어는 props.company(실API 조립). Network/Risk/AI/Signal/Macro는 lazy.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard, Calculator, BarChart3, Boxes, Users, ShieldAlert, Sparkles } from "lucide-react";
import type { CompanyData, SignalInfo, RiskInfo, NetworkInfo, NarrativeInfo } from "@/entities/company/insightsModel";
import { won, eok, pct, toneColor, pctColor } from "@/entities/company/insightsModel";
import { PriceChart, KpiBars, ValueBand, FactorBar, Gauge, ScoreRing, Spark, Radar, ScenarioCards, VerdictBadge } from "./parts";
import ValuationTab from "./ValuationTab";
import FinancialsDeepTab from "./FinancialsDeepTab";
import RiskDeepTab from "./RiskDeepTab";
import { loadSignal, regimeToMacroInfo } from "@/entities/company/data";
import { macroApi } from "@/entities/macro/api";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "valuation", label: "Valuation", icon: Calculator },
  { id: "financials", label: "Financials", icon: BarChart3 },
  { id: "factors", label: "Factors", icon: Boxes },
  { id: "peers", label: "Peers · Network", icon: Users },
  { id: "risk", label: "Risk", icon: ShieldAlert },
  { id: "ai", label: "AI", icon: Sparkles },
] as const;
type TabId = typeof TABS[number]["id"];

export interface LazyLoaders {
  network: () => Promise<NetworkInfo>;
  risk: () => Promise<RiskInfo>;
  narrative: () => Promise<NarrativeInfo>;
}

const dash = (n: number, f: (x: number) => string = (x) => String(x)) => (n && Number.isFinite(n) ? f(n) : "—");

export default function CompanyCockpit({ company, onPick, lazy }: { company: CompanyData; onPick?: (code: string) => void; lazy: LazyLoaders }) {
  const [tab, setTab] = useState<TabId>("overview");
  const c = company;
  // signal: 종목코드별 캐시. macro: 매크로 탭(macro/page.tsx)과 동일한 queryKey(["macro","regime"])
  // 로 캐시를 공유 — 두 탭을 오가도 /api/v1/macro/regime을 중복 호출하지 않는다.
  const { data: signal } = useQuery({
    queryKey: ["company", "signal", c.code],
    queryFn: () => loadSignal(c.code, c.name),
  });
  const { data: regimeRaw } = useQuery({
    queryKey: ["macro", "regime"],
    queryFn: () => macroApi.regime().catch(() => null),
  });
  const macro = regimeToMacroInfo(regimeRaw);
  const [network, setNetwork] = useState<NetworkInfo | undefined>();
  const [risk, setRisk] = useState<RiskInfo | undefined>();
  const [narr, setNarr] = useState<NarrativeInfo | undefined>();
  const [narrLoading, setNarrLoading] = useState(false);
  const [finMode, setFinMode] = useState<"annual" | "quarter">("annual");

  // 종목 변경 시 탭별 lazy 상태 리셋 (signal/macro는 useQuery가 종목코드/공유키로 자체 관리)
  useEffect(() => { setNetwork(undefined); setRisk(undefined); setNarr(undefined); }, [c.code]);
  // 탭별 lazy
  useEffect(() => { if (tab === "peers" && network === undefined) lazy.network().then(setNetwork).catch(() => setNetwork({ groups: [], note: "불러오기 실패" })); }, [tab, network, lazy]);
  useEffect(() => { if (tab === "risk" && risk === undefined) lazy.risk().then(setRisk).catch(() => setRisk({ varPct: null, esAmount: null, vol: null, sharpe: null, mdd: null, note: "불러오기 실패" })); }, [tab, risk, lazy]);

  const runNarrative = () => { setNarrLoading(true); lazy.narrative().then(setNarr).finally(() => setNarrLoading(false)); };

  const signalTone = (a?: string) => a?.includes("buy") || a?.includes("BUY") ? "var(--color-bull)" : a?.includes("sell") || a?.includes("SELL") ? "var(--color-bear)" : "var(--t-muted)";

  return (
    <div className="ca-cp">
      {/* 좌측 기업 패널 */}
      <aside className="ca-cp-panel">
        <div className="ca-cp-id">
          <div className="ca-cp-name">{c.name}</div>
          <div className="ca-cp-code">{c.code} · {c.sector}{c.market ? ` · ${c.market}` : ""}</div>
        </div>
        <div className="ca-cp-px">
          <span className="ca-cp-price">{won(c.price)}</span>
          {!!c.changePct && <span className="ca-cp-chg" style={{ color: c.changePct >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(c.changePct, 2)}</span>}
        </div>
        <div className="ca-cp-verdict">
          <VerdictBadge verdict={c.verdict} tone={c.tone} big />
          <span className="ca-cp-gap" style={{ color: toneColor(c.tone) }}>괴리율 {pct(c.gapPct)}</span>
        </div>
        <div className="ca-cp-ring"><ScoreRing score={c.score.composite} size={96} /><span className="ca-cp-ring-lbl">종합점수</span></div>
        <div className="ca-cp-metrics">
          {[["PER", dash(c.summary.per, (x) => `${x}배`)], ["PBR", dash(c.summary.pbr, (x) => `${x}배`)], ["ROE", dash(c.summary.roe, (x) => `${x}%`)], ["배당", dash(c.summary.divYield, (x) => `${x}%`)], ["부채비율", dash(c.summary.debt, (x) => `${x}%`)], ["시총", dash(c.mktcap, eok)]].map(([k, v]) => (
            <div key={k} className="ca-cp-metric"><span>{k}</span><b>{v}</b></div>
          ))}
        </div>
        {signal && (
          <div className="ca-cp-signal">
            <span className="ca-cp-signal-lbl">기술 시그널</span>
            <span className="ca-cp-signal-act" style={{ color: signalTone(signal.action) }}>{signal.action.toUpperCase()}</span>
            <span className="ca-cp-signal-rsn">{signal.reason}</span>
          </div>
        )}
        {macro && <div className="ca-cp-macro">시장 국면 <b>{macro.regime}</b>{macro.riskFree != null ? ` · Rf ${(macro.riskFree * 100).toFixed(1)}%` : ""}</div>}
        <div className="ca-cp-peers-h">동종 피어</div>
        {c.peers.map((p) => (
          <button key={p.code} className={`ca-cp-peer${p.self ? " self" : ""}`} disabled={p.self} onClick={() => onPick?.(p.code)}>
            <span className="ca-cp-peer-nm">{p.name}</span>
            <span className="ca-cp-peer-gap" style={{ color: p.gap < 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(p.gap)}</span>
          </button>
        ))}
      </aside>

      {/* 메인 */}
      <div className="ca-cp-main">
        <div className="ca-cp-tabs">
          {TABS.map((t) => { const I = t.icon; return (
            <button key={t.id} className={`ca-cp-tab${tab === t.id ? " on" : ""}`} onClick={() => setTab(t.id)}><I size={14} />{t.label}</button>
          ); })}
        </div>

        {tab === "overview" && (
          <div className="ca-cp-dash">
            <div className="ca-cp-card span2">
              <div className="ca-cp-card-h">주가 · 내재가치{c.priceIsSynthetic && <span className="ca-mockbadge">합성</span>}</div>
              <PriceChart data={c.price1y} tone={c.tone} height={200} intrinsic={c.intrinsic} />
            </div>
            <div className="ca-cp-card">
              <div className="ca-cp-card-h">종합 판정</div>
              <div className="ca-cp-judge">
                <Gauge value={c.score.composite} sub={c.verdict} color={toneColor(c.tone)} size={150} />
                <div className="ca-cp-judge-rows">
                  {[["밸류", c.score.gap], ["수익성", c.score.roe], ["안정성", c.score.stability]].map(([k, v]) => (
                    <div key={k as string} className="ca-cp-judge-row"><span>{k}</span><i><b style={{ width: `${v}%`, background: pctColor(v as number) }} /></i><em>{v}</em></div>
                  ))}
                </div>
              </div>
            </div>
            <div className="ca-cp-card span3">
              <div className="ca-cp-card-h">내재가치 밴드 — 현재가 vs RIM·DCF·DDM</div>
              <ValueBand price={c.price} models={c.models} intrinsic={c.intrinsic} />
            </div>
            <div className="ca-cp-card">
              <div className="ca-cp-card-h">핵심 KPI 추세</div>
              {c.years.length ? (
                <div className="ca-cp-kpis">
                  {[["매출", c.years.map((y) => y.revenue)], ["영업익", c.years.map((y) => y.op)], ["순익", c.years.map((y) => y.ni)], ["ROE", c.years.map((y) => y.roe)]].map(([k, vals]) => (
                    <div key={k as string} className="ca-cp-kpi"><span className="ca-cp-kpi-k">{k}</span><Spark values={vals as number[]} w={84} h={28} /><span className="ca-cp-kpi-v">{k === "ROE" ? `${(vals as number[]).slice(-1)[0]}%` : eok((vals as number[]).slice(-1)[0])}</span></div>
                  ))}
                </div>
              ) : <div className="ca-cp-empty">재무 시계열 데이터 없음</div>}
            </div>
            <div className="ca-cp-card">
              <div className="ca-cp-card-h">강점 · 약점</div>
              <div className="ca-cp-sw">
                {c.strengths.slice(0, 3).map((fac) => <FactorBar key={fac.id} fac={fac} />)}
                <div className="ca-cp-sw-div" />
                {c.weaknesses.slice(0, 2).map((fac) => <FactorBar key={fac.id} fac={fac} />)}
              </div>
            </div>
            <div className="ca-cp-card">
              <div className="ca-cp-card-h">내재가치 목표 · 시그널</div>
              <div className="ca-cp-ev">
                <div><span>내재가치</span><b>{won(c.intrinsic)}</b></div>
                <div><span>상승여력</span><b style={{ color: c.consensus.targetUpside >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(c.consensus.targetUpside)}</b></div>
                <div><span>시그널</span><b style={{ color: signalTone(signal?.action) }}>{signal ? signal.action.toUpperCase() : "—"}</b></div>
                <div><span>전략</span><b>{signal?.strategy ?? "—"}</b></div>
              </div>
            </div>
          </div>
        )}

        {tab === "valuation" && (
          <div className="ca-cp-pad">
            <ValuationTab code={c.code} price={c.price} />
            {c.models.length ? (
              <div className="ca-cp-models">
                {c.models.map((m) => (
                  <div key={m.key} className="ca-cp-model">
                    <div className="ca-cp-model-h"><b>{m.key}</b><span>{m.label}</span><em>가중 {(m.weight * 100).toFixed(0)}%</em></div>
                    <div className="ca-cp-model-v">{won(m.value)}</div>
                    <div className="ca-cp-model-g" style={{ color: m.value >= c.price ? "var(--color-bull)" : "var(--color-bear)" }}>현재가 대비 {pct((m.value / c.price - 1) * 100)}</div>
                    <table className="ca-cp-kv"><tbody>{m.assumptions.map((a, i) => <tr key={i}><td>{a.k}</td><td>{a.v}</td></tr>)}</tbody></table>
                    <div className="ca-cp-comp">{m.components.map((cp, i) => <div key={i}><span>{cp.k}</span><b>{cp.v}</b></div>)}</div>
                  </div>
                ))}
              </div>
            ) : <div className="ca-cp-empty">가치평가 모델 산출 불가 (재무 데이터 부족)</div>}
            {c.scenarios.length >= 2 && (
              <div className="ca-cp-card" style={{ marginTop: 18 }}>
                <div className="ca-cp-card-h">Bull · Base · Bear (가정 시프트 — 우리 엔진 재계산)</div>
                <ScenarioCards scenarios={c.scenarios} price={c.price} />
              </div>
            )}
          </div>
        )}

        {tab === "financials" && (
          <div className="ca-cp-pad">
            <FinancialsDeepTab code={c.code} />
            {c.years.length ? (
              <>
                <div className="ca-cp-fintabs">
                  <button className={finMode === "annual" ? "on" : ""} onClick={() => setFinMode("annual")}>연도</button>
                  <button className={finMode === "quarter" ? "on" : ""} disabled={!c.quarters.length} onClick={() => c.quarters.length && setFinMode("quarter")} title={c.quarters.length ? "단일분기 (DART 누적보고서 차분)" : "분기 데이터 없음 — 실데이터(DART 분기보고서)에서 활성"}>분기{!c.quarters.length && <span className="ca-mockbadge">없음</span>}</button>
                </div>
                {finMode === "quarter" && c.quarters.length ? (
                  <>
                  <table className="ca-cp-fin">
                    <thead><tr><th>항목 (억원)</th>{c.quarters.map((q) => <th key={q.q}>{q.q}</th>)}<th>추세</th></tr></thead>
                    <tbody>
                      {([["매출액", (q: CompanyData["quarters"][0]) => q.revenue, eok], ["영업이익", (q: CompanyData["quarters"][0]) => q.op, eok], ["순이익", (q: CompanyData["quarters"][0]) => q.ni, eok], ["자기자본", (q: CompanyData["quarters"][0]) => q.equity, eok], ["ROE %", (q: CompanyData["quarters"][0]) => q.roe, (n: number) => `${n}%`], ["부채비율 %", (q: CompanyData["quarters"][0]) => q.debt, (n: number) => `${n}%`], ["영업이익률 %", (q: CompanyData["quarters"][0]) => q.opMargin, (n: number) => `${n}%`], ["EPS", (q: CompanyData["quarters"][0]) => q.eps, won], ["BPS", (q: CompanyData["quarters"][0]) => q.bps, won], ["DPS", (q: CompanyData["quarters"][0]) => q.dps, won]] as [string, (q: CompanyData["quarters"][0]) => number, (n: number) => string][]).map(([lbl, get, fmt]) => (
                        <tr key={lbl}><td className="lbl">{lbl}</td>{c.quarters.map((q) => <td key={q.q}>{dash(get(q), fmt)}</td>)}<td className="spark"><Spark values={c.quarters.map(get)} /></td></tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="ca-cp-kpibars">
                    <div className="ca-cp-card"><div className="ca-cp-card-h">매출액</div><KpiBars data={c.quarters} dataKey="revenue" xKey="q" /></div>
                    <div className="ca-cp-card"><div className="ca-cp-card-h">영업이익</div><KpiBars data={c.quarters} dataKey="op" color="#16a34a" xKey="q" /></div>
                    <div className="ca-cp-card"><div className="ca-cp-card-h">순이익</div><KpiBars data={c.quarters} dataKey="ni" color="#1200ff" xKey="q" /></div>
                  </div>
                  </>
                ) : (
                  <>
                    <table className="ca-cp-fin">
                      <thead><tr><th>항목 (억원)</th>{c.years.map((y) => <th key={y.year}>{y.year}</th>)}<th>추세</th></tr></thead>
                      <tbody>
                        {([["매출액", (y: CompanyData["years"][0]) => y.revenue, eok], ["영업이익", (y: CompanyData["years"][0]) => y.op, eok], ["순이익", (y: CompanyData["years"][0]) => y.ni, eok], ["자기자본", (y: CompanyData["years"][0]) => y.equity, eok], ["ROE %", (y: CompanyData["years"][0]) => y.roe, (n: number) => `${n}%`], ["부채비율 %", (y: CompanyData["years"][0]) => y.debt, (n: number) => `${n}%`], ["EPS", (y: CompanyData["years"][0]) => y.eps, won], ["BPS", (y: CompanyData["years"][0]) => y.bps, won], ["DPS", (y: CompanyData["years"][0]) => y.dps, won]] as [string, (y: CompanyData["years"][0]) => number, (n: number) => string][]).map(([lbl, get, fmt]) => (
                          <tr key={lbl}><td className="lbl">{lbl}</td>{c.years.map((y) => <td key={y.year}>{dash(get(y), fmt)}</td>)}<td className="spark"><Spark values={c.years.map(get)} /></td></tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="ca-cp-kpibars">
                      <div className="ca-cp-card"><div className="ca-cp-card-h">매출액</div><KpiBars data={c.years} dataKey="revenue" /></div>
                      <div className="ca-cp-card"><div className="ca-cp-card-h">영업이익</div><KpiBars data={c.years} dataKey="op" color="#16a34a" /></div>
                      <div className="ca-cp-card"><div className="ca-cp-card-h">순이익</div><KpiBars data={c.years} dataKey="ni" color="#1200ff" /></div>
                    </div>
                  </>
                )}
              </>
            ) : <div className="ca-cp-empty">재무 시계열을 불러올 수 없습니다 (DART 미등록 종목이거나 데이터 없음).</div>}
          </div>
        )}

        {tab === "factors" && (
          <div className="ca-cp-pad">
            <div className="ca-cp-factop">
              <div className="ca-cp-card"><div className="ca-cp-card-h">카테고리 프로파일 (백분위)</div><div className="ca-cp-radar"><Radar groups={c.fundamentals} size={260} /></div></div>
              <div className="ca-cp-card">
                <div className="ca-cp-card-h">팩터 백분위 — 펀더멘털 {c.fundamentals.reduce((s, g) => s + g.factors.length, 0)} + 가격·수급 {c.priceFactors.reduce((s, g) => s + g.factors.length, 0)}</div>
                <div className="ca-cp-catbars">
                  {[...c.fundamentals, ...c.priceFactors].map((g) => { const avg = Math.round(g.factors.reduce((s, x) => s + x.pct, 0) / (g.factors.length || 1)); return (
                    <div key={g.id} className="ca-cp-catbar"><span>{g.label}</span><i><b style={{ width: `${avg}%`, background: pctColor(avg) }} /></i><em style={{ color: pctColor(avg) }}>{avg}</em></div>
                  ); })}
                </div>
              </div>
            </div>
            <div className="ca-cp-facgrid">
              {[...c.fundamentals, ...c.priceFactors].map((g) => (
                <div key={g.id} className="ca-cp-facgroup">
                  <div className="ca-cp-facgroup-h">{g.label}<span>{g.factors.length}</span></div>
                  {g.factors.map((fac) => <FactorBar key={fac.id} fac={fac} />)}
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "peers" && (
          <div className="ca-cp-pad">
            <div className="ca-cp-card-h plain">섹터 피어 비교 — {c.sector}</div>
            <table className="ca-cp-peertbl">
              <thead><tr><th>종목</th><th className="n">현재가</th><th className="n">PER</th><th className="n">PBR</th><th className="n">ROE</th><th className="n">괴리율</th><th className="n">시가총액</th></tr></thead>
              <tbody>{c.peers.map((p) => (
                <tr key={p.code} className={p.self ? "self" : ""} onClick={() => !p.self && onPick?.(p.code)}>
                  <td>{p.name}{p.self && <span className="ca-cp-self">현재</span>}</td>
                  <td className="n">{won(p.price)}</td><td className="n">{dash(p.per)}</td><td className="n">{dash(p.pbr)}</td><td className="n">{dash(p.roe, (x) => `${x}%`)}</td>
                  <td className="n" style={{ color: p.gap < 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(p.gap)}</td><td className="n">{dash(p.mktcap, eok)}</td>
                </tr>
              ))}</tbody>
            </table>
            <div className="ca-cp-card-h plain" style={{ marginTop: 22 }}>밸류체인 네트워크</div>
            {network === undefined ? <div className="ca-cp-empty">관계도 불러오는 중…</div>
              : network.groups.length ? (
                <div className="ca-cp-net">
                  {network.groups.map((grp) => (
                    <div key={grp.relation} className="ca-cp-net-grp">
                      <div className="ca-cp-net-h">{grp.label} <span>{grp.nodes.length}</span></div>
                      <div className="ca-cp-net-nodes">{grp.nodes.map((nd, i) => <button key={i} className="ca-cp-net-node" onClick={() => nd.code && onPick?.(nd.code)}>{nd.name}</button>)}</div>
                    </div>
                  ))}
                </div>
              ) : <div className="ca-cp-empty">{network.note ?? "등록된 관계가 없습니다."}</div>}
          </div>
        )}

        {tab === "risk" && (
          <div className="ca-cp-pad">
            <RiskDeepTab code={c.code} price={c.price} />
            <div className="ca-cp-card-h plain">리스크 지표 (VaR / 변동성)</div>
            {risk === undefined ? <div className="ca-cp-empty">리스크 지표 계산 중…</div>
              : risk.note ? <div className="ca-cp-empty">{risk.note}</div>
              : (
                <div className="ca-cp-riskgrid">
                  {[
                    ["VaR (99%, 1일)", risk.varPct != null ? `-${Math.abs(risk.varPct).toFixed(2)}%` : "—"],
                    ["기대손실 ES (1억)", risk.esAmount != null ? `-${won(Math.abs(risk.esAmount))}` : "—"],
                    ["연환산 변동성", risk.vol != null ? `${risk.vol.toFixed(1)}%` : "—"],
                    ["Sharpe (rf=0)", risk.sharpe != null ? risk.sharpe.toFixed(2) : "—"],
                    ["최대낙폭 (MDD)", risk.mdd != null ? `${risk.mdd.toFixed(1)}%` : "—"],
                  ].map(([k, v]) => (
                    <div key={k} className="ca-cp-riskcard"><span>{k}</span><b>{v}</b></div>
                  ))}
                </div>
              )}
            <div className="ca-cp-empty" style={{ marginTop: 8, fontSize: 11 }}>※ 종목 일별 시세(최근 ~400봉)에서 역사적 VaR·ES·변동성·MDD·Sharpe를 직접 산출합니다. 시세가 적재되지 않은 종목은 표본 부족으로 표시되지 않을 수 있습니다.</div>
          </div>
        )}

        {tab === "ai" && (
          <div className="ca-cp-pad">
            <div className="ca-cp-ai-head">
              <div className="ca-cp-card-h plain">AI 기업 분석 <span className="ca-mockbadge">Claude</span></div>
              <button className="ca-cp-ai-btn" onClick={runNarrative} disabled={narrLoading}>{narrLoading ? "생성 중…" : narr ? "다시 생성" : "AI 분석 생성"}</button>
            </div>
            {!narr && !narrLoading && <div className="ca-cp-empty">버튼을 눌러 가치평가·재무·팩터를 종합한 AI 내러티브를 생성합니다. (ANTHROPIC_API_KEY 필요 · 토큰 비용 발생)</div>}
            {narr?.error && <div className="ca-cp-empty">AI 생성 실패: {narr.error}</div>}
            {narr && !narr.error && (
              <div className="ca-cp-ai-body">
                <div className="ca-cp-ai-content">{narr.content}</div>
                <div className="ca-cp-ai-meta">{narr.tokens.toLocaleString()} 토큰 · ₩{narr.costKrw.toFixed(1)}{narr.cached ? " · 캐시" : ""}</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
