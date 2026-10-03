"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// CompanyCockpit — 기업 분석 한 흐름 + 붙는 목차 (BU6, 사용자 결정 2026-10-03)
// ─────────────────────────────────────────────────────────────────────────────
// 예전: 왼쪽 기업 패널 + 영어 탭 7(Overview·Valuation·Financials·Factors·Peers·Risk·AI). 지금: 토스증권 종목 상세처럼 한 세로 흐름
//   머리(이름·코드·가격·판정·설계에 넣기) → 답 한 문장 → 붙는 목차 → 가치 → 여러 모형 → 핵심 숫자 → 돈 버는 힘 → 위험 → 같은 업종 → 팩터 → AI.
// ★그림·표는 하나도 지우지 않았다★ 탭 안에 있던 것은 그대로 그 절로 옮겼다(가치 절의 무거운 것들은 "자세히" 안). 같은 종합점수를
//   두 번 그리던 고리(ScoreRing)는 반원 게이지 하나로 합쳤다. 새로 더한 그림: 주가와 가치 범위를 겹친 그림(사용자 결정).
// ★답 문장 = 서버 값(ADR-003 §2.6)★ evaluate 의 intrinsic_value·gap_pct(엔진 `compute_gap_pct` = (현재가−적정가)/적정가). 내재가치가 없으면
//   판단 없이 "계산하지 못했어요". 판정·괴리·점수는 색으로 말하지 않는다(중립) — 등락만 등락색, 백분위는 수준 색.
// ★실패와 "없음"을 가른다★ 코어 하위 요청 실패(`company.failed`)는 그 절 alert + 다시 시도 · 시세가 비면 주가 선을 그리지 않는다(지어내지 않음).
// 무거운 절(위험·같은 업종의 관계도)은 화면에 들어올 때 부른다. AI 는 단추를 눌러야만(비용).
// BU6a+(사용자 피드백): 백엔드에 있던 가치 모형 여덟을 "여러 모형" 절로(모형 한눈에 = 한 축 위 점·범위) · 매크로 민감도(위험 절) ·
//   옛 왼쪽 패널의 "늘 보이는 요약"은 붙는 미니 머리(이름·현재가·전일 대비·판정) + 넓은 화면의 오른쪽 레일(핵심 숫자·모형 한눈에·같은 업종)로.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import type { CompanyData, RiskInfo, NetworkInfo, NarrativeInfo } from "@/entities/company/insightsModel";
import { won, eok, pct } from "@/entities/company/insightsModel";
import { companyApi } from "@/entities/company/api";
import { loadSignal, regimeToMacroInfo } from "@/entities/company/data";
import { macroApi } from "@/entities/macro/api";
import { regimeName } from "@/entities/macro/regimeKo";
import { Answer, RetryFail, type Chip } from "@/shared/ui/tx";
import { UNKNOWN_TEXT, priceWon } from "@/shared/lib/krFormat";
import { KpiBars, PriceChart, ValueBand, FactorBar, Gauge, Spark, Radar, ScenarioCards, VerdictBadge, PriceValueChart, type ValueBandIn } from "./parts";
import ValuationTab from "./ValuationTab";
import FinancialsDeepTab from "./FinancialsDeepTab";
import RiskDeepTab from "./RiskDeepTab";
import { useCompanyModels } from "./useModels";
import { ModelLadder, buildLadderRows } from "./ModelLadder";
import { ModelsSection, MacroBlock } from "./ModelsSection";

export interface LazyLoaders {
  network: () => Promise<NetworkInfo>;
  risk: () => Promise<RiskInfo>;
  narrative: () => Promise<NarrativeInfo>;
}

const SECS = [
  { id: "value", label: "가치", title: "주가와 가치" },
  { id: "models", label: "여러 모형", title: "여러 모형으로 본 가치" },
  { id: "numbers", label: "핵심 숫자", title: "핵심 숫자" },
  { id: "money", label: "돈 버는 힘", title: "돈 버는 힘" },
  { id: "risk", label: "위험", title: "위험" },
  { id: "peers", label: "같은 업종", title: "같은 업종" },
  { id: "factors", label: "팩터", title: "팩터로 본 위치" },
  { id: "ai", label: "AI", title: "AI 설명" },
] as const;
type SecId = typeof SECS[number]["id"];

/** 값 → 글자. ★null = 몰라요(0 과 다르다)★ */
const show = (v: number | null | undefined, f: (x: number) => string) => (v == null || !Number.isFinite(v) ? UNKNOWN_TEXT : f(v));
/** 기술 시그널 번역 — 서버 action 을 옮길 뿐 판단을 더하지 않는다. 모르는 값은 서버 글자 그대로. */
const SIGNAL_KO: Record<string, string> = { buy: "사는 쪽", strong_buy: "강하게 사는 쪽", sell: "파는 쪽", strong_sell: "강하게 파는 쪽", hold: "지켜보는 쪽", neutral: "지켜보는 쪽" };
const signalKo = (a?: string) => (a ? SIGNAL_KO[a.toLowerCase()] ?? a : UNKNOWN_TEXT);

/** 한 번 화면에 들어오면 true (무거운 절을 그때 부른다). */
function useSeen(ref: React.RefObject<HTMLElement>) {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setSeen(true); }, { rootMargin: "200px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, seen]);
  return seen;
}

export default function CompanyCockpit({ company, onPick, lazy, onRetry }: {
  company: CompanyData; onPick?: (code: string) => void; lazy: LazyLoaders; onRetry: () => void;
}) {
  const c = company;
  const { data: signal } = useQuery({ queryKey: ["company", "signal", c.code], queryFn: () => loadSignal(c.code, c.name) });
  // 매크로 분석·홈과 같은 키 — 실패를 null 로 감싸 캐시하지 않는다(BU5a).
  const { data: regimeRaw } = useQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime() });
  const macro = regimeToMacroInfo(regimeRaw);
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  // 가치 범위(풋볼필드·샌드박스) — 겹친 그림과 "자세히"가 같은 응답을 쓴다(요청 하나).
  const sb = useQuery({ queryKey: ["company", "sandbox", c.code, c.price], queryFn: () => companyApi.valuationSandbox(c.code, c.price) });

  const [network, setNetwork] = useState<NetworkInfo | null | undefined>();
  const [risk, setRisk] = useState<RiskInfo | null | undefined>();
  const [narr, setNarr] = useState<NarrativeInfo | null | undefined>();
  const [narrLoading, setNarrLoading] = useState(false);
  const [finMode, setFinMode] = useState<"annual" | "quarter">("annual");
  const [netTry, setNetTry] = useState(0);
  const [riskTry, setRiskTry] = useState(0);

  const refs = {
    value: useRef<HTMLElement>(null), models: useRef<HTMLElement>(null), numbers: useRef<HTMLElement>(null), money: useRef<HTMLElement>(null),
    risk: useRef<HTMLElement>(null), peers: useRef<HTMLElement>(null), factors: useRef<HTMLElement>(null), ai: useRef<HTMLElement>(null),
  } as Record<SecId, React.RefObject<HTMLElement>>;
  // 여러 모형(BU6a+) — 가치 샌드박스가 끝난 뒤 부른다(첫 화면과 무거운 요청이 겹치지 않게). 모형 한눈에·레일·카드·위험 절이 같은 응답을 쓴다.
  const models = useCompanyModels(c.code, c.price, c.mktcap, sb.isSuccess || sb.isError);
  const ladder = buildLadderRows(sb, models);
  // 붙는 미니 머리 — 머리가 화면 밖으로 나가면 이름·현재가·전일 대비·판정을 목차 위에 붙인다(옛 왼쪽 패널의 "늘 보이는 요약").
  const headRef = useRef<HTMLElement>(null);
  const [mini, setMini] = useState(false);
  useEffect(() => {
    const el = headRef.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setMini(!e.isIntersecting), { rootMargin: "-64px 0px 0px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const riskSeen = useSeen(refs.risk);
  const moneySeen = useSeen(refs.money);
  const peersSeen = useSeen(refs.peers);

  // 종목이 바뀌면 절마다 늦게 부른 것을 비운다(옛 종목 값이 남지 않게).
  useEffect(() => { setNetwork(undefined); setRisk(undefined); setNarr(undefined); }, [c.code]);
  useEffect(() => {
    if (!peersSeen || network !== undefined) return;
    let ok = true;
    lazy.network().then((v) => ok && setNetwork(v)).catch(() => ok && setNetwork(null));
    return () => { ok = false; };
  }, [peersSeen, network, lazy, netTry]);
  useEffect(() => {
    if (!riskSeen || risk !== undefined) return;
    let ok = true;
    lazy.risk().then((v) => ok && setRisk(v)).catch(() => ok && setRisk(null));
    return () => { ok = false; };
  }, [riskSeen, risk, lazy, riskTry]);
  const runNarrative = () => {
    setNarrLoading(true);
    lazy.narrative().then(setNarr).catch(() => setNarr(null)).finally(() => setNarrLoading(false));
  };

  // ── 붙는 목차: 지금 절 = 화면 위 30% 선을 지난 마지막 절(끝까지 내렸으면 마지막 절) ──
  // IntersectionObserver 는 "바뀐" 절만 알려 줘서 늦게 차오르는 절(위험·같은 업종)이 자리를 밀면 표시가 남는다 → 스크롤마다 직접 잰다.
  const [active, setActive] = useState<SecId>("value");
  const clickLock = useRef(0);
  useEffect(() => {
    let raf = 0;
    const pick = () => {
      raf = 0;
      if (Date.now() < clickLock.current) return;
      const line = window.innerHeight * 0.3;
      let cur: SecId = SECS[0].id;
      for (const s of SECS) {
        const el = refs[s.id].current;
        if (el && el.getBoundingClientRect().top <= line) cur = s.id;
      }
      const last = refs[SECS[SECS.length - 1].id].current;
      if (last && last.getBoundingClientRect().bottom <= window.innerHeight + 1 && last.getBoundingClientRect().top < window.innerHeight) cur = SECS[SECS.length - 1].id;
      setActive(cur);
    };
    const on = () => { if (!raf) raf = requestAnimationFrame(pick); };
    document.addEventListener("scroll", on, { capture: true, passive: true });
    window.addEventListener("resize", on);
    return () => { document.removeEventListener("scroll", on, { capture: true }); window.removeEventListener("resize", on); if (raf) cancelAnimationFrame(raf); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const go = (id: SecId) => {
    setActive(id);
    clickLock.current = Date.now() + 900;
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    refs[id].current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  };

  // ── 답 ──
  const hasIntrinsic = c.intrinsic > 0 && Number.isFinite(c.gapPct);
  const sentence = hasIntrinsic
    ? <>우리 추정 내재가치 {priceWon(c.intrinsic)}보다 {Math.round(Math.abs(c.gapPct))}% {c.gapPct < 0 ? "낮게" : "높게"} 거래돼요</>
    : <>내재가치를 계산하지 못했어요. 지금은 판단하지 않아요.</>;
  const chips: Chip[] = [];
  // 연습용 = connection-status(mock 게이트) 또는 머리 문장 응답의 is_mock — 어느 하나라도 연습용이면 말한다.
  if (cs.data?.mock_allowed || c.isMock) chips.push({ label: "연습용 시세·재무", tone: "practice" });
  if (!c.failed.includes("valuation")) chips.push({ label: `가치 모형 ${c.models.length}개로 계산(RIM·DCF·DDM 중)`, tone: "info" });
  if (c.failed.includes("valuation")) chips.push({ label: "가치평가를 불러오지 못했어요", tone: "unknown" });
  if (!c.price1y.length && !c.failed.includes("prices")) chips.push({ label: "시세 없음", tone: "unknown" });

  const bands: ValueBandIn[] = (sb.data?.football_field.bands ?? [])
    .filter((b) => b.available !== false && b.lo != null && b.hi != null)
    .map((b) => ({ id: b.id, label: b.label, lo: b.lo as number, hi: b.hi as number }));

  const sec = (id: SecId, body: React.ReactNode, extraClass = "") => {
    const meta = SECS.find((s) => s.id === id)!;
    return (
      <section key={id} ref={refs[id]} className={`ci-sec ${extraClass}`.trim()} data-sec={id} aria-labelledby={`ci-h-${id}`}>
        <h2 className="ci-sec-h" id={`ci-h-${id}`}>{meta.title}</h2>
        {body}
      </section>
    );
  };

  return (
    <div className="ci">
      <header className="ci-head" ref={headRef}>
        <div className="ci-head-main">
          <h1 className="ci-name">{c.name}</h1>
          <p className="ci-meta"><span className="ci-code" data-mono>{c.code}</span><span data-server>{c.sector}</span>{c.market && <span data-server>{c.market}</span>}</p>
          <p className="ci-px"><b className="ci-price">{priceWon(c.price)}</b><DayChange c={c} cls="ci-chg" /><VerdictBadge verdict={c.verdict} tone={c.tone} /></p>
        </div>
        <Link className="tx-btn tx-btn--main ci-bridge" href={`/allocation?tickers=${c.code}`}>설계에 넣기</Link>
      </header>

      <Answer sentence={sentence} chips={chips} figures={[
        { label: "현재가", value: priceWon(c.price) },
        { label: "내재가치", value: hasIntrinsic ? priceWon(c.intrinsic) : UNKNOWN_TEXT },
        { label: "판정(서버)", value: <span data-server>{c.verdict}</span> },
      ]} />

      <div className="ci-stick">
        <div className="ci-mini" hidden={!mini} aria-label="지금 보는 기업">
          <b className="ci-mini-name">{c.name}</b>
          <span className="ci-mini-price">{priceWon(c.price)}</span>
          <DayChange c={c} cls="ci-mini-chg" />
          <VerdictBadge verdict={c.verdict} tone={c.tone} />
        </div>
        <nav className="ci-toc" aria-label="이 페이지 목차">
          {SECS.map((s) => (
            <button key={s.id} type="button" className={`ci-toc-item${active === s.id ? " on" : ""}`}
                    aria-current={active === s.id ? "true" : undefined} onClick={() => go(s.id)}>{s.label}</button>
          ))}
        </nav>
      </div>

      <div className="ci-body">
      <div className="ci-flow">

      {/* ── 주가와 가치 ── */}
      {sec("value", (
        <>
          <p className="ci-sec-lede">1년 주가 선 뒤에 모형별 가치 범위를 띠로 깔았어요. 점선은 우리 추정 내재가치예요.</p>
          {c.failed.includes("prices") && <RetryFail title="시세를 불러오지 못했어요" onRetry={onRetry} />}
          {!c.price1y.length && !c.failed.includes("prices") && <p className="ci-pv-noprice">시세가 아직 적재되지 않았어요. 주가 선 없이 가치 범위만 보여 드려요.</p>}
          {sb.isError && <RetryFail title="가치 범위를 불러오지 못했어요" onRetry={() => void sb.refetch()} />}
          <PriceValueChart data={c.price1y} price={c.price} intrinsic={hasIntrinsic ? c.intrinsic : 0} bands={bands} />

          <div className="ci-block">
            <h3 className="ci-block-h">모형 한눈에</h3>
            <p className="ci-assume-diff">위 문장의 내재가치는 무위험수익률 3.5%·베타 1.0 고정 가정이에요. 아래 줄들은 실측 기본값
              {sb.data ? <>(무위험 <span data-server>{(sb.data.assumptions.find((a) => a.key === "rf")?.source) ?? "출처 모름"}</span>, 베타 <span data-server>{(sb.data.assumptions.find((a) => a.key === "beta")?.source) ?? "출처 모름"}</span>)</> : null}
              을 써서 값이 다를 수 있어요.</p>
            <ModelLadder rows={ladder} price={c.price} intrinsic={hasIntrinsic ? c.intrinsic : null} />
          </div>

          {c.failed.includes("valuation")
            ? <RetryFail title="가치평가를 불러오지 못했어요" onRetry={onRetry}>서버에 닿지 못했어요. 모형별 값은 다시 시도하면 나와요.</RetryFail>
            : c.models.length ? (
              <div className="ci-models">
                {c.models.map((m) => (
                  <div key={m.key} className="ci-model">
                    <p className="ci-model-h"><b>{m.label}</b><span data-mono>{m.key}</span><em>가중 {(m.weight * 100).toFixed(0)}%</em></p>
                    <p className="ci-model-v">{priceWon(m.value)}</p>
                    <p className="ci-model-g">현재가 대비 {pct((m.value / c.price - 1) * 100)}</p>
                    <details className="ci-model-more">
                      <summary>가정과 계산 보기</summary>
                      <table className="ca-cp-kv"><tbody>{m.assumptions.map((a, i) => <tr key={i}><td>{a.k}</td><td>{a.v}</td></tr>)}</tbody></table>
                      <div className="ca-cp-comp">{m.components.map((cp, i) => <div key={i}><span>{cp.k}</span><b>{cp.v}</b></div>)}</div>
                    </details>
                  </div>
                ))}
              </div>
            ) : <p className="ci-models-none">가치 모형이 이번에는 값을 내지 못했어요(재무 자료가 부족해요).</p>}

          {c.scenarios.length >= 2 && (
            <div className="ci-block">
              <h3 className="ci-block-h">가정을 바꿔 다시 계산하면</h3>
              <ScenarioCards scenarios={c.scenarios} price={c.price} />
            </div>
          )}

          <details className="ci-more">
            <summary>가치를 더 자세히 보기(1년 주가·가치 밴드·모형별 범위·가정 바꿔 보기·민감도·업종 안 위치·상대가치)</summary>
            {c.price1y.length > 0 && (
              <div className="ci-block">
                <h3 className="ci-block-h">1년 주가</h3>
                <PriceChart data={c.price1y} intrinsic={hasIntrinsic ? c.intrinsic : undefined} />
                <p className="ci-note">점선은 우리 추정 내재가치예요.</p>
              </div>
            )}
            <div className="ci-block">
              <h3 className="ci-block-h">현재가와 모형별 값</h3>
              <ValueBand price={c.price} models={c.models} intrinsic={c.intrinsic} />
            </div>
            {sb.data && <ValuationTab code={c.code} price={c.price} base={sb.data} />}
            {sb.isLoading && <p className="ca-cp-note">가치 범위를 계산하는 중이에요</p>}
          </details>
        </>
      ))}


      {/* ── 여러 모형(BU6a+) ── */}
      {sec("models", <ModelsSection m={models} price={c.price} pbr={c.summary.pbr} code={c.code} />)}

      {/* ── 핵심 숫자 ── (`.ca-cp-panel` 은 module-motion 패널 계약 — 예전 왼쪽 패널의 자리) */}
      {sec("numbers", (
        <div className="ca-cp-panel ci-numbers">
          <dl className="ci-nums">
            {([
              ["PER(주가수익비율)", show(c.summary.per, (x) => `${x}배`)],
              ["PBR(주가순자산비율)", show(c.summary.pbr, (x) => `${x}배`)],
              ["ROE(자기자본이익률)", show(c.summary.roe, (x) => `${x}%`)],
              ["배당", show(c.summary.divYield, (x) => `${x}%`)],
              ["부채비율", show(c.summary.debt, (x) => `${x}%`)],
              ["시가총액", show(c.mktcap, eok)],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} className="ci-num"><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
          <div className="ci-numgrid">
            <div className="ci-block ca-cp-card">
              <h3 className="ci-block-h">종합점수</h3>
              <div className="ca-cp-judge">
                <Gauge value={c.score.composite} label="종합점수" size={150} />
                <div className="ca-cp-judge-rows">
                  {([["가치(괴리)", c.score.gap], ["수익성", c.score.roe], ["안정성", c.score.stability]] as [string, number][]).map(([k, v]) => (
                    <div key={k} className="ca-cp-judge-row"><span>{k}</span><i><b style={{ width: `${v}%` }} /></i><em>{v}</em></div>
                  ))}
                </div>
              </div>
              <p className="ci-note">100점 만점. 점수는 서버가 계산한 값이에요.</p>
            </div>
            <div className="ci-block ca-cp-card">
              <h3 className="ci-block-h">최근 추세(연도별)</h3>
              {c.years.length ? (
                <div className="ca-cp-kpis">
                  {([["매출", c.years.map((y) => y.revenue), eok], ["영업이익", c.years.map((y) => y.op), eok], ["순이익", c.years.map((y) => y.ni), eok], ["ROE", c.years.map((y) => y.roe), (n: number) => `${n}%`]] as [string, number[], (n: number) => string][]).map(([k, vals, f]) => (
                    <div key={k} className="ca-cp-kpi"><span className="ca-cp-kpi-k">{k}</span><Spark values={vals} w={84} h={28} /><span className="ca-cp-kpi-v">{f(vals.slice(-1)[0])}</span></div>
                  ))}
                </div>
              ) : c.failed.includes("financials")
                ? <RetryFail title="재무 시계열을 불러오지 못했어요" onRetry={onRetry} />
                : <p className="ca-cp-empty">재무 시계열 자료가 없어요.</p>}
            </div>
            <div className="ci-block ca-cp-card">
              <h3 className="ci-block-h">강한 점과 약한 점(업종 백분위)</h3>
              <div className="ca-cp-sw">
                {c.strengths.slice(0, 3).map((fac) => <FactorBar key={fac.id} fac={fac} />)}
                <div className="ca-cp-sw-div" />
                {c.weaknesses.slice(0, 2).map((fac) => <FactorBar key={fac.id} fac={fac} />)}
              </div>
            </div>
            <div className="ci-block ca-cp-card">
              <h3 className="ci-block-h">기술 신호와 시장 국면</h3>
              <dl className="ci-dl">
                <div><dt>기술 신호</dt><dd>{signal === undefined ? "확인하는 중이에요" : signal === null ? "신호를 받지 못했어요" : signalKo(signal.action)}</dd></div>
                {signal?.strategy && <div><dt>근거 전략</dt><dd data-server>{signal.strategy}</dd></div>}
                {signal?.reason && <div><dt>이유</dt><dd data-server>{signal.reason}</dd></div>}
                <div><dt>시장 국면</dt><dd>{macro ? regimeName(macro.regime) : "국면을 받지 못했어요"}</dd></div>
                {macro?.riskFree != null && <div><dt>무위험수익률</dt><dd>{(macro.riskFree * 100).toFixed(1)}%</dd></div>}
              </dl>
            </div>
          </div>
        </div>
      ))}

      {/* ── 돈 버는 힘 ── (안쪽 모양은 BU6b) */}
      {sec("money", (
        <div className="ca-cp-pad">
          {c.years.length ? (
            <>
              <div className="ca-cp-fintabs" role="group" aria-label="기간 단위">
                <button type="button" aria-pressed={finMode === "annual"} className={finMode === "annual" ? "on" : ""} onClick={() => setFinMode("annual")}>연도</button>
                <button type="button" aria-pressed={finMode === "quarter"} className={finMode === "quarter" ? "on" : ""} disabled={!c.quarters.length} onClick={() => c.quarters.length && setFinMode("quarter")}>분기</button>
                {!c.quarters.length && <span className="ci-note">분기 자료가 없어요(DART 분기보고서가 적재되면 켜져요)</span>}
              </div>
              {finMode === "quarter" && c.quarters.length ? (
                <>
                  <FinTable cols={c.quarters.map((q) => q.q)} rows={([["매출액", c.quarters.map((q) => q.revenue), eok], ["영업이익", c.quarters.map((q) => q.op), eok], ["순이익", c.quarters.map((q) => q.ni), eok], ["자기자본", c.quarters.map((q) => q.equity), eok], ["ROE %", c.quarters.map((q) => q.roe), (n: number) => `${n}%`], ["부채비율 %", c.quarters.map((q) => q.debt), (n: number) => `${n}%`], ["영업이익률 %", c.quarters.map((q) => q.opMargin), (n: number) => `${n}%`], ["EPS", c.quarters.map((q) => q.eps), won], ["BPS", c.quarters.map((q) => q.bps), won], ["DPS", c.quarters.map((q) => q.dps), won]])} />
                  <div className="ca-cp-kpibars">
                    <div className="ca-cp-card"><div className="ca-cp-card-h">매출액</div><KpiBars data={c.quarters} dataKey="revenue" xKey="q" /></div>
                    <div className="ca-cp-card"><div className="ca-cp-card-h">영업이익</div><KpiBars data={c.quarters} dataKey="op" xKey="q" /></div>
                    <div className="ca-cp-card"><div className="ca-cp-card-h">순이익</div><KpiBars data={c.quarters} dataKey="ni" xKey="q" /></div>
                  </div>
                </>
              ) : (
                <>
                  <FinTable cols={c.years.map((y) => y.year)} rows={([["매출액", c.years.map((y) => y.revenue), eok], ["영업이익", c.years.map((y) => y.op), eok], ["순이익", c.years.map((y) => y.ni), eok], ["자기자본", c.years.map((y) => y.equity), eok], ["ROE %", c.years.map((y) => y.roe), (n: number) => `${n}%`], ["부채비율 %", c.years.map((y) => y.debt), (n: number) => `${n}%`], ["EPS", c.years.map((y) => y.eps), won], ["BPS", c.years.map((y) => y.bps), won], ["DPS", c.years.map((y) => y.dps), won]])} />
                  <div className="ca-cp-kpibars">
                    <div className="ca-cp-card"><div className="ca-cp-card-h">매출액</div><KpiBars data={c.years} dataKey="revenue" /></div>
                    <div className="ca-cp-card"><div className="ca-cp-card-h">영업이익</div><KpiBars data={c.years} dataKey="op" /></div>
                    <div className="ca-cp-card"><div className="ca-cp-card-h">순이익</div><KpiBars data={c.years} dataKey="ni" /></div>
                  </div>
                </>
              )}
            </>
          ) : c.failed.includes("financials")
            ? <RetryFail title="재무 시계열을 불러오지 못했어요" onRetry={onRetry} />
            : <p className="ca-cp-empty">재무 시계열 자료가 없어요(DART 에 없는 종목일 수 있어요).</p>}
          {moneySeen && <FinancialsDeepTab code={c.code} />}
        </div>
      ))}

      {/* ── 위험 ── (안쪽 모양은 BU6b) */}
      {sec("risk", (
        <div className="ca-cp-pad">
          <MacroBlock q={models.macro} />
          {riskSeen && <RiskDeepTab code={c.code} price={c.price} />}
          <h3 className="ci-block-h">시세로 잰 위험</h3>
          {risk === undefined ? <p className="ca-cp-empty">위험 지표를 계산하는 중이에요</p>
            : risk === null ? <RetryFail title="위험 지표를 불러오지 못했어요" onRetry={() => { setRisk(undefined); setRiskTry((n) => n + 1); }} />
            : risk.note ? <p className="ca-cp-empty">{risk.note}</p>
            : (
              <div className="ca-cp-riskgrid">
                {([
                  ["하루 최대 손실 추정(VaR 99%)", risk.varPct != null ? `−${Math.abs(risk.varPct).toFixed(2)}%` : UNKNOWN_TEXT],
                  ["그보다 나쁜 날 평균 손실(ES, 1억원 기준)", risk.esAmount != null ? `−${won(Math.abs(risk.esAmount))}` : UNKNOWN_TEXT],
                  ["1년 변동성", risk.vol != null ? `${risk.vol.toFixed(1)}%` : UNKNOWN_TEXT],
                  ["샤프 지수(무위험 0)", risk.sharpe != null ? risk.sharpe.toFixed(2) : UNKNOWN_TEXT],
                  ["최대 낙폭(MDD)", risk.mdd != null ? `${risk.mdd.toFixed(1)}%` : UNKNOWN_TEXT],
                ] as [string, string][]).map(([k, v]) => <div key={k} className="ca-cp-riskcard"><span>{k}</span><b>{v}</b></div>)}
              </div>
            )}
          <p className="ci-note">종목 일별 시세(최근 400거래일까지)로 직접 계산해요. 시세가 적재되지 않은 종목은 표본이 부족해 나오지 않을 수 있어요.</p>
        </div>
      ))}

      {/* ── 같은 업종 ── */}
      {sec("peers", (
        <div className="ca-cp-pad">
          <p className="ci-sec-lede"><span data-server>{c.sector}</span> 업종의 다른 기업이에요. 줄을 누르면 그 기업을 열어요.</p>
          <div className="ci-tablewrap">
            <table className="ca-cp-peertbl">
              <thead><tr><th scope="col">종목</th><th scope="col" className="n">현재가</th><th scope="col" className="n">PER</th><th scope="col" className="n">PBR</th><th scope="col" className="n">ROE</th><th scope="col" className="n">괴리율</th><th scope="col" className="n">시가총액</th></tr></thead>
              <tbody>{c.peers.map((p) => (
                <tr key={p.code} data-code={p.code} className={p.self ? "self" : ""} tabIndex={p.self ? undefined : 0}
                    onClick={() => !p.self && onPick?.(p.code)}
                    onKeyDown={(e) => { if (!p.self && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onPick?.(p.code); } }}>
                  <td>{p.name}{p.self && <span className="ca-cp-self">지금 보는 기업</span>}</td>
                  <td className="n">{priceWon(p.price)}</td><td className="n">{p.per ? p.per : UNKNOWN_TEXT}</td><td className="n">{p.pbr ? p.pbr : UNKNOWN_TEXT}</td><td className="n">{p.roe ? `${p.roe}%` : UNKNOWN_TEXT}</td>
                  <td className="n">{pct(p.gap)}</td><td className="n">{p.mktcap ? eok(p.mktcap) : UNKNOWN_TEXT}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <h3 className="ci-block-h">밸류체인 관계</h3>
          {network === undefined ? <p className="ca-cp-empty">관계도를 불러오는 중이에요</p>
            : network === null ? <RetryFail title="관계도를 불러오지 못했어요" onRetry={() => { setNetwork(undefined); setNetTry((n) => n + 1); }} />
            : network.groups.length ? (
              <div className="ca-cp-net">
                {network.groups.map((grp) => (
                  <div key={grp.relation} className="ca-cp-net-grp">
                    <div className="ca-cp-net-h">{grp.label} <span>{grp.nodes.length}</span></div>
                    <div className="ca-cp-net-nodes">{grp.nodes.map((nd, i) => <button type="button" key={i} className="ca-cp-net-node" onClick={() => nd.code && onPick?.(nd.code)}>{nd.name}</button>)}</div>
                  </div>
                ))}
              </div>
            ) : <p className="ca-cp-empty">{network.note ?? "등록된 관계가 없어요."}</p>}
        </div>
      ))}

      {/* ── 팩터 ── */}
      {sec("factors", (
        <div className="ca-cp-pad">
          <div className="ca-cp-factop">
            <div className="ca-cp-card"><div className="ca-cp-card-h">카테고리별 평균 백분위</div><div className="ca-cp-radar"><Radar groups={c.fundamentals} size={260} /></div></div>
            <div className="ca-cp-card">
              <div className="ca-cp-card-h">팩터 백분위: 재무 {c.fundamentals.reduce((s, g) => s + g.factors.length, 0)}개, 가격·수급 {c.priceFactors.reduce((s, g) => s + g.factors.length, 0)}개</div>
              <div className="ca-cp-catbars">
                {[...c.fundamentals, ...c.priceFactors].map((g) => { const avg = Math.round(g.factors.reduce((s, x) => s + x.pct, 0) / (g.factors.length || 1)); return (
                  <div key={g.id} className="ca-cp-catbar"><span data-server>{g.label}</span><i><b style={{ width: `${avg}%` }} /></i><em>{avg}</em></div>
                ); })}
              </div>
            </div>
          </div>
          <div className="ca-cp-facgrid">
            {[...c.fundamentals, ...c.priceFactors].map((g) => (
              <div key={g.id} className="ca-cp-facgroup">
                <div className="ca-cp-facgroup-h"><span data-server>{g.label}</span><span>{g.factors.length}</span></div>
                {g.factors.map((fac) => <FactorBar key={fac.id} fac={fac} />)}
              </div>
            ))}
          </div>
        </div>
      ))}

      {/* ── AI ── */}
      {sec("ai", (
        <div className="ca-cp-pad">
          <div className="ca-cp-ai-head">
            <p className="ci-sec-lede">가치평가·재무·팩터를 모아 AI 가 설명 글을 써요. 누를 때마다 비용이 들어요.</p>
            <button type="button" className="tx-btn tx-btn--sub ca-cp-ai-btn" onClick={runNarrative} disabled={narrLoading}>{narrLoading ? "쓰는 중이에요" : narr ? "다시 쓰기" : "AI 설명 받기"}</button>
          </div>
          {narr === null && <RetryFail title="AI 설명을 받지 못했어요" onRetry={runNarrative} />}
          {narr?.error && <p className="ca-cp-empty">AI 설명을 쓰지 못했어요: <span data-server>{narr.error}</span></p>}
          {narr && !narr.error && (
            <div className="ca-cp-ai-body">
              <div className="ca-cp-ai-content" data-server>{narr.content}</div>
              <div className="ca-cp-ai-meta">{narr.tokens.toLocaleString()} 토큰, 약 {narr.costKrw.toFixed(1)}원{narr.cached ? "(저장해 둔 글)" : ""}</div>
            </div>
          )}
          {narr === undefined && !narrLoading && <details className="ci-note"><summary>켜는 방법</summary>관리자가 AI 키를 넣어 두면 켜져요(환경변수 ANTHROPIC_API_KEY).</details>}
        </div>
      ))}
      </div>

      {/* ── 오른쪽 레일(≥1280 에서만 — 좁으면 미니 머리가 대신한다) ── */}
      <aside className="ci-rail" aria-label="기업 요약">
        <section className="ci-rail-card">
          <h2 className="ci-rail-h">핵심 숫자</h2>
          <dl className="ci-rail-nums">
            {([["PER", show(c.summary.per, (x) => `${x}배`)], ["PBR", show(c.summary.pbr, (x) => `${x}배`)],
               ["ROE", show(c.summary.roe, (x) => `${x}%`)], ["배당", show(c.summary.divYield, (x) => `${x}%`)]] as [string, string][]).map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </section>
        <section className="ci-rail-card">
          <h2 className="ci-rail-h">모형 한눈에</h2>
          <ModelLadder rows={ladder} price={c.price} intrinsic={hasIntrinsic ? c.intrinsic : null} compact />
        </section>
        <section className="ci-rail-card">
          <h2 className="ci-rail-h">같은 업종 바꾸기</h2>
          <ul className="ci-rail-peers">
            {c.peers.map((p) => (
              <li key={p.code}>
                <button type="button" className="ci-rail-peer" data-code={p.code} aria-current={p.self ? "true" : undefined}
                        disabled={p.self} onClick={() => !p.self && onPick?.(p.code)}>
                  <span className="ci-rail-peer-n">{p.name}</span><span className="ci-rail-peer-p">{priceWon(p.price)}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <Link className="tx-btn tx-btn--main ci-rail-go" href={`/allocation?tickers=${c.code}`}>설계에 넣기</Link>
      </aside>
      </div>
    </div>
  );
}

/** 전일 대비 — 일별 시세 마지막 두 종가(서버 원본). 모르면 그리지 않는다(0% 금지). 한국식 등락색 + 부호. */
function DayChange({ c, cls }: { c: CompanyData; cls: string }) {
  const d = c.dayChange;
  if (!d) return null;
  const dir = d.pct > 0 ? "up" : d.pct < 0 ? "down" : "flat";
  return <span className={cls} data-dir={dir}>{d.pct > 0 ? "+" : d.pct < 0 ? "−" : ""}{Math.abs(d.pct).toFixed(2)}%<span className="ci-chg-k"> 전일 대비</span></span>;
}

/** 재무 표 — 항목 × 기간 + 추세 스파크라인(등락색). 0 은 0, 값이 없으면 몰라요는 BU6b 에서(지금은 서버가 0 으로 채운다). */
function FinTable({ cols, rows }: { cols: string[]; rows: [string, number[], (n: number) => string][] }) {
  return (
    <div className="ci-tablewrap">
      <table className="ca-cp-fin">
        <thead><tr><th scope="col">항목(억원)</th>{cols.map((k) => <th key={k} scope="col">{k}</th>)}<th scope="col">추세</th></tr></thead>
        <tbody>
          {rows.map(([lbl, vals, fmt]) => (
            <tr key={lbl}><td className="lbl">{lbl}</td>{vals.map((v, i) => <td key={i}>{fmt(v)}</td>)}<td className="spark"><Spark values={vals} /></td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
