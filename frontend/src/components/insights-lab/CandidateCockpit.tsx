"use client";
// 후보 C — "Cockpit"(추천): sticky 좌측 기업 패널 + 메인 탭 워크스페이스. 버틀러+에픽+밸리 결합.
import React, { useState } from "react";
import { LayoutDashboard, Calculator, BarChart3, Boxes, Users } from "lucide-react";
import type { CompanyData } from "./sampleData";
import { COMPANIES, won, eok, pct, toneColor, pctColor } from "./sampleData";
import { PriceChart, KpiBars, ValueBand, FactorBar, Gauge, ScoreRing, Spark, Radar, ScenarioCards, VerdictBadge } from "./parts";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "valuation", label: "Valuation", icon: Calculator },
  { id: "financials", label: "Financials", icon: BarChart3 },
  { id: "factors", label: "Factors", icon: Boxes },
  { id: "peers", label: "Peers", icon: Users },
] as const;
type TabId = typeof TABS[number]["id"];

export default function CandidateCockpit({ company, onPick }: { company: CompanyData; onPick?: (code: string) => void }) {
  const [tab, setTab] = useState<TabId>("overview");
  const c = company;

  return (
    <div className="ca-cp">
      {/* 좌측 기업 패널 (sticky) */}
      <aside className="ca-cp-panel">
        <div className="ca-cp-id">
          <div className="ca-cp-name">{c.name}</div>
          <div className="ca-cp-code">{c.code} · {c.sector}</div>
        </div>
        <div className="ca-cp-px">
          <span className="ca-cp-price">{won(c.price)}</span>
          <span className="ca-cp-chg" style={{ color: c.changePct >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(c.changePct, 2)}</span>
        </div>
        <div className="ca-cp-verdict">
          <VerdictBadge verdict={c.verdict} tone={c.tone} big />
          <span className="ca-cp-gap" style={{ color: toneColor(c.tone) }}>괴리율 {pct(c.gapPct)}</span>
        </div>
        <div className="ca-cp-ring"><ScoreRing score={c.score.composite} size={96} /><span className="ca-cp-ring-lbl">종합점수</span></div>
        <div className="ca-cp-metrics">
          {[["PER", `${c.summary.per}배`], ["PBR", `${c.summary.pbr}배`], ["ROE", `${c.summary.roe}%`], ["배당", `${c.summary.divYield}%`], ["부채비율", `${c.summary.debt}%`], ["시총", eok(c.mktcap)]].map(([k, v]) => (
            <div key={k} className="ca-cp-metric"><span>{k}</span><b>{v}</b></div>
          ))}
        </div>
        <div className="ca-cp-peers-h">동종 피어</div>
        {c.peers.map((p) => (
          <button key={p.code} className={`ca-cp-peer${p.self ? " self" : ""}`} disabled={p.self} onClick={() => onPick?.(p.code)}>
            <span className="ca-cp-peer-nm">{p.name}</span>
            <span className="ca-cp-peer-gap" style={{ color: p.gap < 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(p.gap)}</span>
          </button>
        ))}
        <div className="ca-cp-switch">
          <div className="ca-cp-switch-h">다른 종목</div>
          {COMPANIES.filter((x) => x.code !== c.code).map((x) => (
            <button key={x.code} className="ca-cp-switch-item" onClick={() => onPick?.(x.code)}>{x.name} ›</button>
          ))}
        </div>
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
              <div className="ca-cp-card-h">주가 · 내재가치 (14M)</div>
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
              <div className="ca-cp-kpis">
                {[["매출", c.years.map((y) => y.revenue)], ["영업익", c.years.map((y) => y.op)], ["순익", c.years.map((y) => y.ni)], ["ROE", c.years.map((y) => y.roe)]].map(([k, vals]) => (
                  <div key={k as string} className="ca-cp-kpi">
                    <span className="ca-cp-kpi-k">{k}</span>
                    <Spark values={vals as number[]} w={84} h={28} />
                    <span className="ca-cp-kpi-v">{k === "ROE" ? `${(vals as number[])[4]}%` : eok((vals as number[])[4])}</span>
                  </div>
                ))}
              </div>
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
              <div className="ca-cp-card-h">다음 이벤트 · 컨센서스 <span className="ca-mockbadge">mock</span></div>
              <div className="ca-cp-ev">
                <div><span>실적발표</span><b>D-{c.events.earningsDays}</b></div>
                <div><span>배당락</span><b>D-{c.events.exDivDays}</b></div>
                <div><span>목표주가</span><b>{won(c.consensus.targetPrice)}</b></div>
                <div><span>상승여력</span><b style={{ color: "var(--color-bull)" }}>{pct(c.consensus.targetUpside)}</b></div>
              </div>
            </div>
          </div>
        )}

        {tab === "valuation" && (
          <div className="ca-cp-pad">
            <div className="ca-cp-models">
              {c.models.map((m) => (
                <div key={m.key} className="ca-cp-model">
                  <div className="ca-cp-model-h"><b>{m.key}</b><span>{m.label}</span><em>가중 {(m.weight * 100).toFixed(0)}%</em></div>
                  <div className="ca-cp-model-v">{won(m.value)}</div>
                  <div className="ca-cp-model-g" style={{ color: m.value >= c.price ? "var(--color-bull)" : "var(--color-bear)" }}>현재가 대비 {pct((m.value / c.price - 1) * 100)}</div>
                  <table className="ca-cp-kv"><tbody>{m.assumptions.map((a) => <tr key={a.k}><td>{a.k}</td><td>{a.v}</td></tr>)}</tbody></table>
                  <div className="ca-cp-comp">{m.components.map((cp) => <div key={cp.k}><span>{cp.k}</span><b>{cp.v}</b></div>)}</div>
                </div>
              ))}
            </div>
            <div className="ca-cp-card" style={{ marginTop: 18 }}>
              <div className="ca-cp-card-h">Bull · Base · Bear (가정 시프트 재계산)</div>
              <ScenarioCards scenarios={c.scenarios} price={c.price} />
            </div>
          </div>
        )}

        {tab === "financials" && (
          <div className="ca-cp-pad">
            <table className="ca-cp-fin">
              <thead><tr><th>항목 (억원)</th>{c.years.map((y) => <th key={y.year}>{y.year}</th>)}<th>추세</th></tr></thead>
              <tbody>
                {([["매출액", (y: CompanyData["years"][0]) => y.revenue, eok], ["영업이익", (y: CompanyData["years"][0]) => y.op, eok], ["순이익", (y: CompanyData["years"][0]) => y.ni, eok], ["ROE %", (y: CompanyData["years"][0]) => y.roe, (n: number) => `${n}%`], ["부채비율 %", (y: CompanyData["years"][0]) => y.debt, (n: number) => `${n}%`], ["EPS", (y: CompanyData["years"][0]) => y.eps, won], ["DPS", (y: CompanyData["years"][0]) => y.dps, won]] as [string, (y: CompanyData["years"][0]) => number, (n: number) => string][]).map(([lbl, get, fmt]) => (
                  <tr key={lbl}><td className="lbl">{lbl}</td>{c.years.map((y) => <td key={y.year}>{fmt(get(y))}</td>)}<td className="spark"><Spark values={c.years.map(get)} /></td></tr>
                ))}
              </tbody>
            </table>
            <div className="ca-cp-kpibars">
              <div className="ca-cp-card"><div className="ca-cp-card-h">매출액</div><KpiBars data={c.years} dataKey="revenue" /></div>
              <div className="ca-cp-card"><div className="ca-cp-card-h">영업이익</div><KpiBars data={c.years} dataKey="op" color="#16a34a" /></div>
              <div className="ca-cp-card"><div className="ca-cp-card-h">순이익</div><KpiBars data={c.years} dataKey="ni" color="#1200ff" /></div>
            </div>
          </div>
        )}

        {tab === "factors" && (
          <div className="ca-cp-pad">
            <div className="ca-cp-factop">
              <div className="ca-cp-card"><div className="ca-cp-card-h">카테고리 프로파일 (백분위)</div><div className="ca-cp-radar"><Radar groups={c.fundamentals} size={260} /></div></div>
              <div className="ca-cp-card">
                <div className="ca-cp-card-h">팩터 요약 · 116개 (펀더 64 + 가격수급 28 + 가치 24)</div>
                <div className="ca-cp-catbars">
                  {c.fundamentals.map((g) => { const avg = Math.round(g.factors.reduce((s, x) => s + x.pct, 0) / g.factors.length); return (
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
            <table className="ca-cp-peertbl">
              <thead><tr><th>종목</th><th className="n">현재가</th><th className="n">PER</th><th className="n">PBR</th><th className="n">ROE</th><th className="n">괴리율</th><th className="n">시가총액</th></tr></thead>
              <tbody>{c.peers.map((p) => (
                <tr key={p.code} className={p.self ? "self" : ""} onClick={() => !p.self && onPick?.(p.code)}>
                  <td>{p.name}{p.self && <span className="ca-cp-self">현재</span>}</td>
                  <td className="n">{won(p.price)}</td><td className="n">{p.per}</td><td className="n">{p.pbr}</td><td className="n">{p.roe}%</td>
                  <td className="n" style={{ color: p.gap < 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(p.gap)}</td><td className="n">{eok(p.mktcap)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
