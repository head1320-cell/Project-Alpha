"use client";
// 후보 B — "Briefing": 내러티브 스크롤 (밸리AI/에픽). hero + 스토리 섹션, 큰 시각요소.
import React from "react";
import type { CompanyData } from "./sampleData";
import { won, eok, pct, toneColor } from "./sampleData";
import { PriceChart, KpiBars, ValueBand, FactorBar, Gauge, ScenarioCards, VerdictBadge, Metric } from "./parts";

export default function CandidateBriefing({ company }: { company: CompanyData }) {
  const c = company;
  const tc = toneColor(c.tone);
  const direction = c.gapPct < 0 ? "저평가" : c.gapPct > 0 ? "고평가" : "적정 수준";
  return (
    <div className="ca-bf">
      {/* HERO */}
      <div className="ca-bf-hero">
        <div className="ca-bf-hero-l">
          <div className="ca-bf-eyebrow">COMPANY BRIEFING · KRX {c.code}</div>
          <h1 className="ca-bf-name">{c.name}<span className="ca-bf-sector">{c.sector}</span></h1>
          <div className="ca-bf-pxrow">
            <span className="ca-bf-price">{won(c.price)}</span>
            <span className="ca-bf-chg" style={{ color: c.changePct >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(c.changePct, 2)} 오늘</span>
            <VerdictBadge verdict={c.verdict} tone={c.tone} big />
          </div>
          <p className="ca-bf-headline">통합 내재가치 <b>{won(c.intrinsic)}</b> 대비 현재가는 <b style={{ color: tc }}>{pct(Math.abs(c.gapPct) === c.gapPct ? c.gapPct : c.gapPct)}</b> 수준 — <b style={{ color: tc }}>{Math.abs(c.gapPct).toFixed(1)}% {direction}</b>입니다.</p>
          <div className="ca-bf-hero-metrics">
            <Metric label="PER" value={`${c.summary.per}배`} />
            <Metric label="PBR" value={`${c.summary.pbr}배`} />
            <Metric label="ROE" value={`${c.summary.roe}%`} />
            <Metric label="배당수익률" value={`${c.summary.divYield}%`} />
            <Metric label="시가총액" value={eok(c.mktcap)} />
          </div>
        </div>
        <div className="ca-bf-hero-r">
          <PriceChart data={c.price1y} tone={c.tone} height={260} intrinsic={c.intrinsic} />
        </div>
      </div>

      {/* 01 저평가? */}
      <Section n="01" title="지금 저평가인가?" sub="현재가와 3가지 내재가치 모형(RIM·DCF·DDM)을 비교합니다.">
        <div className="ca-bf-val">
          <div className="ca-bf-val-band">
            <ValueBand price={c.price} models={c.models} intrinsic={c.intrinsic} />
            <div className="ca-bf-models">
              {c.models.map((m) => (
                <div key={m.key} className="ca-bf-model">
                  <span className="ca-bf-model-k">{m.key}</span>
                  <span className="ca-bf-model-v">{won(m.value)}</span>
                  <span className="ca-bf-model-g" style={{ color: m.value >= c.price ? "var(--color-bull)" : "var(--color-bear)" }}>{pct((m.value / c.price - 1) * 100)}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="ca-bf-val-gauge">
            <Gauge value={c.score.composite} label="종합점수" sub={c.verdict} color={tc} size={160} />
            <p className="ca-bf-reason">{c.name}의 종합점수는 <b>{c.score.composite}</b>점. 괴리({c.score.gap}) · 수익성({c.score.roe}) · 안정성({c.score.stability}) 가중 합산이며, <b style={{ color: tc }}>{c.verdict}</b>으로 판정됩니다.</p>
          </div>
        </div>
      </Section>

      {/* 02 무엇으로 버나 */}
      <Section n="02" title="무엇으로 돈을 버나" sub="최근 5년 매출·영업이익·순이익 추세와 마진.">
        <div className="ca-bf-kpis">
          <KpiCard title="매출액" data={c.years} k="revenue" />
          <KpiCard title="영업이익" data={c.years} k="op" color="#16a34a" />
          <KpiCard title="순이익" data={c.years} k="ni" color="#1200ff" />
        </div>
        <div className="ca-bf-margins">
          <Metric label="영업이익률" value={`${(c.summary.op / c.summary.revenue * 100).toFixed(1)}%`} />
          <Metric label="순이익률" value={`${(c.summary.ni / c.summary.revenue * 100).toFixed(1)}%`} />
          <Metric label="FCF" value={eok(c.summary.fcf)} />
          <Metric label="자기자본" value={eok(c.summary.equity)} />
          <Metric label="ROA" value={`${c.summary.roa}%`} />
        </div>
      </Section>

      {/* 03 강점과 약점 */}
      <Section n="03" title="강점과 약점" sub="116개 팩터 중 백분위 최상·최하 항목 (높을수록 동종 대비 우위).">
        <div className="ca-bf-sw">
          <div className="ca-bf-sw-col">
            <div className="ca-bf-sw-h up">강점 TOP</div>
            {c.strengths.map((fac) => <FactorBar key={fac.id} fac={fac} />)}
          </div>
          <div className="ca-bf-sw-col">
            <div className="ca-bf-sw-h down">약점 / 주의</div>
            {c.weaknesses.map((fac) => <FactorBar key={fac.id} fac={fac} />)}
          </div>
        </div>
      </Section>

      {/* 04 시나리오 */}
      <Section n="04" title="Bull · Base · Bear" sub="가치평가 가정(성장률·요구수익률)을 시프트해 우리 엔진으로 재계산한 미래 시나리오.">
        <ScenarioCards scenarios={c.scenarios} price={c.price} />
      </Section>

      {/* 05 피어 */}
      <Section n="05" title="동종업계 대비" sub={`${c.sector} 섹터 내 밸류에이션·수익성 비교.`}>
        <div className="ca-bf-peers">
          {c.peers.map((p) => (
            <div key={p.code} className={`ca-bf-peer${p.self ? " self" : ""}`}>
              <div className="ca-bf-peer-nm">{p.name}{p.self && <span className="ca-bf-peer-self">현재</span>}</div>
              <div className="ca-bf-peer-px">{won(p.price)}</div>
              <div className="ca-bf-peer-kv"><span>PER</span><b>{p.per}</b></div>
              <div className="ca-bf-peer-kv"><span>ROE</span><b>{p.roe}%</b></div>
              <div className="ca-bf-peer-gap" style={{ color: p.gap < 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(p.gap)}</div>
            </div>
          ))}
        </div>
      </Section>

      {/* 06 주주환원·컨센서스 */}
      <Section n="06" title="주주환원 · 컨센서스" sub="배당 정책과 시장 추정치.">
        <div className="ca-bf-last">
          <div className="ca-bf-last-card">
            <div className="ca-bf-last-h">주주환원</div>
            <div className="ca-bf-last-grid">
              <Metric label="배당수익률" value={`${c.shareholder.divYield}%`} />
              <Metric label="배당성향" value={`${c.shareholder.payout}%`} />
              <Metric label="DPS" value={won(c.shareholder.dps)} />
              <Metric label="총주주환원" value={`${c.shareholder.shYield}%`} />
            </div>
          </div>
          <div className="ca-bf-last-card">
            <div className="ca-bf-last-h">컨센서스 <span className="ca-mockbadge">mock</span></div>
            <div className="ca-bf-last-grid">
              <Metric label="12M 선행 PER" value={`${c.consensus.fwdPer}배`} />
              <Metric label="EPS 1M 변화" value={pct(c.consensus.fwdEpsChg)} color={c.consensus.fwdEpsChg >= 0 ? "var(--color-bull)" : "var(--color-bear)"} />
              <Metric label="목표주가" value={won(c.consensus.targetPrice)} />
              <Metric label="상승여력" value={pct(c.consensus.targetUpside)} color="var(--color-bull)" />
            </div>
          </div>
        </div>
      </Section>
    </div>
  );
}

function Section({ n, title, sub, children }: { n: string; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="ca-bf-sec">
      <div className="ca-bf-sec-head">
        <span className="ca-bf-sec-n">{n}</span>
        <div><h2 className="ca-bf-sec-title">{title}</h2>{sub && <p className="ca-bf-sec-sub">{sub}</p>}</div>
      </div>
      <div className="ca-bf-sec-body">{children}</div>
    </section>
  );
}

function KpiCard({ title, data, k, color }: { title: string; data: CompanyData["years"]; k: string; color?: string }) {
  const last = data[data.length - 1][k as "revenue"] as number;
  const prev = data[data.length - 2][k as "revenue"] as number;
  const g = prev ? (last / prev - 1) * 100 : 0;
  return (
    <div className="ca-bf-kpi">
      <div className="ca-bf-kpi-h">{title}<span style={{ color: g >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>{pct(g)} YoY</span></div>
      <div className="ca-bf-kpi-v">{eok(last)}</div>
      <KpiBars data={data} dataKey={k} color={color} height={120} />
    </div>
  );
}
