"use client";
// 후보 A — "Terminal": 고밀도 탭형 (버틀러/Fnguide). sticky 헤더 + L레일 + 탭 워크스페이스.
import React, { useState } from "react";
import { Search, Star, ChevronRight } from "lucide-react";
import type { CompanyData } from "./sampleData";
import { COMPANIES, won, eok, pct, toneColor, pctColor } from "./sampleData";
import { PriceChart, KpiBars, ValueBand, FactorBar, Gauge, Spark, ScenarioCards, VerdictBadge } from "./parts";

const TABS = ["요약", "밸류에이션", "재무", "펀더멘탈", "가격·수급", "주주환원", "컨센서스", "피어"] as const;
type Tab = typeof TABS[number];

export default function CandidateTerminal({ company, onPick }: { company: CompanyData; onPick?: (code: string) => void }) {
  const [tab, setTab] = useState<Tab>("요약");
  const [period, setPeriod] = useState<"year" | "quarter">("year");
  const c = company;
  const F = (id: string) => c.fundamentals.flatMap((g) => g.factors).find((x) => x.id === id);
  const piotroski = F("piotroski_f")?.value ?? "—";

  return (
    <div className="ca-tm">
      {/* sticky 헤더 스트립 */}
      <div className="ca-tm-head">
        <div className="ca-tm-id">
          <span className="ca-tm-name">{c.name}</span>
          <span className="ca-tm-code">{c.code} · {c.sector} · KRX</span>
        </div>
        <div className="ca-tm-px">
          <span className="ca-tm-price">{won(c.price)}</span>
          <span className="ca-tm-chg" style={{ color: c.changePct >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(c.changePct, 2)}</span>
        </div>
        <VerdictBadge verdict={c.verdict} tone={c.tone} big />
        <span className="ca-tm-gap" style={{ color: toneColor(c.tone) }}>괴리율 {pct(c.gapPct)}</span>
        <div className="ca-tm-strip">
          {[["PER", `${c.summary.per}배`], ["PBR", `${c.summary.pbr}배`], ["ROE", `${c.summary.roe}%`], ["배당", `${c.summary.divYield}%`], ["시총", eok(c.mktcap)], ["F-Score", `${piotroski}/9`]].map(([k, v]) => (
            <span key={k} className="ca-tm-strip-item"><b>{k}</b>{v}</span>
          ))}
        </div>
      </div>

      <div className="ca-tm-body">
        {/* 좌측 레일 */}
        <aside className="ca-tm-rail">
          <div className="ca-tm-search"><Search size={13} /><input placeholder="기업명·코드 검색" readOnly /></div>
          <div className="ca-tm-rail-sec">관심종목</div>
          {COMPANIES.map((x) => (
            <button key={x.code} className={`ca-tm-rail-item${x.code === c.code ? " on" : ""}`} onClick={() => onPick?.(x.code)}>
              <Star size={11} className="ca-tm-rail-star" />
              <span className="ca-tm-rail-nm">{x.name}</span>
              <span className="ca-tm-rail-vd" style={{ color: toneColor(x.tone) }}>{x.verdict}</span>
            </button>
          ))}
          <div className="ca-tm-rail-sec">동종 피어</div>
          {c.peers.filter((p) => !p.self).slice(0, 4).map((p) => (
            <div key={p.code} className="ca-tm-rail-peer">
              <span className="ca-tm-rail-nm">{p.name}</span>
              <span className="ca-tm-rail-pe">PER {p.per}</span>
            </div>
          ))}
        </aside>

        {/* 메인 */}
        <div className="ca-tm-main">
          <div className="ca-tm-tabs">
            {TABS.map((t) => <button key={t} className={`ca-tm-tab${tab === t ? " on" : ""}`} onClick={() => setTab(t)}>{t}</button>)}
          </div>

          {tab === "요약" && (
            <div className="ca-tm-grid2">
              <Card title="주가 (14M)"><PriceChart data={c.price1y} tone={c.tone} height={200} intrinsic={c.intrinsic} /></Card>
              <Card title="내재가치 vs 현재가"><ValueBand price={c.price} models={c.models} intrinsic={c.intrinsic} /></Card>
              <Card title="종합점수 분해">
                <div className="ca-tm-score">
                  <Gauge value={c.score.composite} label="Composite" sub={c.verdict} color={toneColor(c.tone)} />
                  <div className="ca-tm-score-rows">
                    {[["밸류(괴리)", c.score.gap], ["수익성(ROE)", c.score.roe], ["안정성", c.score.stability]].map(([k, v]) => (
                      <div key={k as string} className="ca-tm-score-row"><span>{k}</span><span className="ca-tm-score-bar"><i style={{ width: `${v}%`, background: pctColor(v as number) }} /></span><b>{v}</b></div>
                    ))}
                  </div>
                </div>
              </Card>
              <Card title="다음 이벤트">
                <div className="ca-tm-events">
                  <div className="ca-tm-event"><span>실적발표</span><b>D-{c.events.earningsDays}</b></div>
                  <div className="ca-tm-event"><span>배당락</span><b>D-{c.events.exDivDays}</b></div>
                  <div className="ca-tm-event"><span>목표주가</span><b>{won(c.consensus.targetPrice)}</b></div>
                  <div className="ca-tm-event"><span>상승여력</span><b style={{ color: "var(--color-bull)" }}>{pct(c.consensus.targetUpside)}</b></div>
                </div>
              </Card>
            </div>
          )}

          {tab === "밸류에이션" && (
            <div className="ca-tm-val">
              <div className="ca-tm-models">
                {c.models.map((m) => (
                  <div key={m.key} className="ca-tm-model">
                    <div className="ca-tm-model-h"><b>{m.key}</b> {m.label}<span className="ca-tm-model-w">가중 {(m.weight * 100).toFixed(0)}%</span></div>
                    <div className="ca-tm-model-v">{won(m.value)}</div>
                    <div className="ca-tm-model-g" style={{ color: m.value >= c.price ? "var(--color-bull)" : "var(--color-bear)" }}>{pct((m.value / c.price - 1) * 100)}</div>
                    <table className="ca-tm-kv"><tbody>
                      {m.assumptions.map((a) => <tr key={a.k}><td>{a.k}</td><td>{a.v}</td></tr>)}
                    </tbody></table>
                    <div className="ca-tm-comp">{m.components.map((cp) => <div key={cp.k}><span>{cp.k}</span><b>{cp.v}</b></div>)}</div>
                  </div>
                ))}
              </div>
              <Card title="Bull · Base · Bear (가정 시프트 재계산)"><ScenarioCards scenarios={c.scenarios} price={c.price} /></Card>
            </div>
          )}

          {tab === "재무" && (
            <div>
              <div className="ca-tm-toggle">
                <button className={period === "year" ? "on" : ""} onClick={() => setPeriod("year")}>연도</button>
                <button className={period === "quarter" ? "on" : ""} onClick={() => setPeriod("quarter")}>분기</button>
                <span className="ca-tm-toggle-note">단위: 억원 · DART PIT 기준</span>
              </div>
              <FinTable c={c} period={period} />
              <div className="ca-tm-grid3" style={{ marginTop: 14 }}>
                <Card title="매출"><KpiBars data={c.years} dataKey="revenue" /></Card>
                <Card title="영업이익"><KpiBars data={c.years} dataKey="op" color="#16a34a" /></Card>
                <Card title="순이익"><KpiBars data={c.years} dataKey="ni" color="#1200ff" /></Card>
              </div>
            </div>
          )}

          {tab === "펀더멘탈" && (
            <div className="ca-tm-facgrid">
              {c.fundamentals.map((g) => (
                <div key={g.id} className="ca-tm-facgroup">
                  <div className="ca-tm-facgroup-h">{g.label}<span>{g.factors.length}</span></div>
                  {g.factors.map((fac) => <FactorBar key={fac.id} fac={fac} />)}
                </div>
              ))}
            </div>
          )}

          {tab === "가격·수급" && (
            <div className="ca-tm-facgrid">
              {c.priceFactors.map((g) => (
                <div key={g.id} className="ca-tm-facgroup">
                  <div className="ca-tm-facgroup-h">{g.label}<span>{g.factors.length}</span></div>
                  {g.factors.map((fac) => <FactorBar key={fac.id} fac={fac} />)}
                </div>
              ))}
            </div>
          )}

          {tab === "주주환원" && (
            <div className="ca-tm-grid2">
              <Card title="배당 지표">
                <table className="ca-tm-kv wide"><tbody>
                  <tr><td>배당수익률</td><td>{c.shareholder.divYield}%</td></tr>
                  <tr><td>배당성향</td><td>{c.shareholder.payout}%</td></tr>
                  <tr><td>주당배당금(DPS)</td><td>{won(c.shareholder.dps)}</td></tr>
                  <tr><td>총주주환원수익률</td><td>{c.shareholder.shYield}%</td></tr>
                </tbody></table>
              </Card>
              <Card title="DPS 추이"><KpiBars data={c.years} dataKey="dps" color="#d97706" fmt={(n) => won(n)} /></Card>
            </div>
          )}

          {tab === "컨센서스" && (
            <Card title="애널리스트 컨센서스" badge="mock">
              <div className="ca-tm-cons">
                {[["12M 선행 PER", `${c.consensus.fwdPer}배`], ["EPS 1M 변화", pct(c.consensus.fwdEpsChg)], ["리비전 점수", `${c.consensus.revision}`], ["목표주가", won(c.consensus.targetPrice)], ["상승여력", pct(c.consensus.targetUpside)]].map(([k, v]) => (
                  <div key={k} className="ca-tm-cons-item"><span>{k}</span><b>{v}</b></div>
                ))}
              </div>
            </Card>
          )}

          {tab === "피어" && <PeerTable c={c} onPick={onPick} />}
        </div>
      </div>
    </div>
  );
}

function Card({ title, children, badge }: { title: string; children: React.ReactNode; badge?: string }) {
  return (
    <div className="ca-tm-card">
      <div className="ca-tm-card-h">{title}{badge && <span className="ca-mockbadge">{badge}</span>}</div>
      <div className="ca-tm-card-b">{children}</div>
    </div>
  );
}

function FinTable({ c, period }: { c: CompanyData; period: "year" | "quarter" }) {
  if (period === "quarter") {
    const rows: [string, (q: CompanyData["quarters"][0]) => string][] = [
      ["매출액", (q) => eok(q.revenue)], ["영업이익", (q) => eok(q.op)], ["순이익", (q) => eok(q.ni)], ["영업이익률", (q) => `${q.opMargin}%`],
    ];
    return (
      <table className="ca-tm-fin">
        <thead><tr><th>항목</th>{c.quarters.map((q) => <th key={q.q}>{q.q}</th>)}<th>추세</th></tr></thead>
        <tbody>{rows.map(([lbl, get], ri) => (
          <tr key={lbl}><td className="lbl">{lbl}</td>{c.quarters.map((q) => <td key={q.q}>{get(q)}</td>)}<td className="spark"><Spark values={c.quarters.map((q) => ri === 3 ? q.opMargin : ri === 0 ? q.revenue : ri === 1 ? q.op : q.ni)} /></td></tr>
        ))}</tbody>
      </table>
    );
  }
  const rows: [string, (y: CompanyData["years"][0]) => string, (y: CompanyData["years"][0]) => number][] = [
    ["매출액", (y) => eok(y.revenue), (y) => y.revenue], ["영업이익", (y) => eok(y.op), (y) => y.op], ["순이익", (y) => eok(y.ni), (y) => y.ni],
    ["ROE", (y) => `${y.roe}%`, (y) => y.roe], ["부채비율", (y) => `${y.debt}%`, (y) => y.debt], ["EPS", (y) => won(y.eps), (y) => y.eps], ["BPS", (y) => won(y.bps), (y) => y.bps], ["DPS", (y) => won(y.dps), (y) => y.dps],
  ];
  return (
    <table className="ca-tm-fin">
      <thead><tr><th>항목</th>{c.years.map((y) => <th key={y.year}>{y.year}</th>)}<th>추세</th></tr></thead>
      <tbody>{rows.map(([lbl, get, num]) => (
        <tr key={lbl}><td className="lbl">{lbl}</td>{c.years.map((y) => <td key={y.year}>{get(y)}</td>)}<td className="spark"><Spark values={c.years.map(num)} /></td></tr>
      ))}</tbody>
    </table>
  );
}

function PeerTable({ c, onPick }: { c: CompanyData; onPick?: (code: string) => void }) {
  return (
    <table className="ca-tm-peer">
      <thead><tr><th>종목</th><th className="n">현재가</th><th className="n">PER</th><th className="n">PBR</th><th className="n">ROE</th><th className="n">괴리율</th><th className="n">시총</th></tr></thead>
      <tbody>{c.peers.map((p) => (
        <tr key={p.code} className={p.self ? "self" : ""} onClick={() => !p.self && onPick?.(p.code)}>
          <td>{p.name}{p.self && <span className="ca-tm-self">현재</span>}{!p.self && <ChevronRight size={12} className="ca-tm-peer-go" />}</td>
          <td className="n">{won(p.price)}</td><td className="n">{p.per}</td><td className="n">{p.pbr}</td><td className="n">{p.roe}%</td>
          <td className="n" style={{ color: p.gap < 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(p.gap)}</td><td className="n">{eok(p.mktcap)}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}
