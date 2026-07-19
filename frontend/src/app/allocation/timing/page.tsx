"use client";
// 03 TIMING — 카나리 신호 + 마켓타이밍. 좌: 카나리 자산·지표(신호·임계·룩백) + 브레드스
// 게이트(k-of-N) + 위험-온/오프 자산군 + 추세 오버레이 / 우: 위험-온·오프 판정 + 결과 배분
// (적용) + 시장 타이밍 컴포짓(timing_panel 재사용) + 자산 추세표. 백엔드 POST /allocation/timing.
import React, { useState } from "react";
import { type TimingConfig, useAllocation } from "@/components/allocation/AllocationProvider";
import { ConfidenceGauge } from "@/components/allocation/parts";
import type { CanaryInput, CanarySignalType } from "@/lib/allocationApi";

const ASSET_SUGGEST = ["SPY", "QQQ", "IWM", "EFA", "EEM", "AGG", "TLT", "IEF", "SHY", "LQD", "HYG", "GLD", "VNQ", "BIL"];
const IND_SUGGEST: [string, string][] = [
  ["VIXCLS", "VIX 변동성"], ["DGS10", "미 10년물"], ["BAMLH0A0HYM2", "HY 스프레드"], ["T10Y2Y", "10Y-2Y"],
];
const ASSET_SIGNALS: { id: CanarySignalType; label: string }[] = [
  { id: "score_13612", label: "13612W 가속모멘텀" },
  { id: "abs_mom", label: "절대모멘텀(N개월)" },
  { id: "ma_month", label: "N개월 이동평균 상회" },
  { id: "ma_day", label: "N일 이동평균 상회" },
];
const parseList = (s: string) => s.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);

// ── 마켓 지수 게이트 프리셋 — 백테스터 탭 '마켓타이밍'(지수 조건 → 위험 시 방어 전환)을
//    자산배분 맥락으로 일반화. 위험-온이면 현재/전략 포트폴리오 유지, 위험-오프면 방어자산 전환
//    (백테스터 exit_all 대응). 위험자산 추세 프록시는 ETF 매핑(SPY→국내 대형주 ETF)을 사용. ──
type Gate = { id: string; label: string; sub: string; build: (mk: "kr" | "us") => TimingConfig };
const OFF_DEFENSIVE = ["IEF", "SHY"];
const MARKET_GATES: Gate[] = [
  {
    id: "trend200", label: "추세 게이트 (200일선)",
    sub: "위험자산이 200일 이동평균 위 → 위험-온 · 아래 → 방어 전환",
    build: (mk) => ({ market: mk,
      canaries: [{ kind: "asset", id: "SPY", signal: "ma_day", lookback: 200, threshold: 0, direction: "above" }],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "none", n: 200, lookback: 12 } }),
  },
  {
    id: "mom13612", label: "가속 모멘텀 게이트 (13612W)",
    sub: "1·3·6·12M 가속 모멘텀 > 0 → 위험-온 (VAA/DAA식)",
    build: (mk) => ({ market: mk,
      canaries: [{ kind: "asset", id: "SPY", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" }],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "none", n: 200, lookback: 12 } }),
  },
  {
    id: "dual", label: "이중 확인 게이트",
    sub: "추세(200일) + 가속 모멘텀 둘 다 통과해야 위험-온",
    build: (mk) => ({ market: mk,
      canaries: [
        { kind: "asset", id: "SPY", signal: "ma_day", lookback: 200, threshold: 0, direction: "above" },
        { kind: "asset", id: "EFA", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" },
      ],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "none", n: 200, lookback: 12 } }),
  },
  {
    id: "trend_overlay", label: "추세 + 자산별 청산",
    sub: "게이트 + 보유자산 개별 추세 이탈분 현금화 (백테스터 exit_all 근사)",
    build: (mk) => ({ market: mk,
      canaries: [{ kind: "asset", id: "SPY", signal: "ma_day", lookback: 200, threshold: 0, direction: "above" }],
      minBreadth: 0, riskOnAssets: [], riskOffAssets: OFF_DEFENSIVE, overlay: { type: "ma_day", n: 200, lookback: 12 } }),
  },
];

export default function TimingWorkspace() {
  const { timingCfg, setTimingCfg, timingQ, applyTiming, holdings, loadedStrategy } = useAllocation();
  const [onText, setOnText] = useState(timingCfg.riskOnAssets.join(", "));
  const [offText, setOffText] = useState(timingCfg.riskOffAssets.join(", "));

  const applyGate = (g: Gate) => {
    const cfg = g.build(timingCfg.market);
    setTimingCfg(cfg);
    setOnText(cfg.riskOnAssets.join(", "));
    setOffText(cfg.riskOffAssets.join(", "));
  };

  const setCfg = (patch: Partial<TimingConfig>) => setTimingCfg({ ...timingCfg, ...patch });
  const updCanary = (i: number, patch: Partial<CanaryInput>) =>
    setCfg({ canaries: timingCfg.canaries.map((c, ix) => (ix === i ? { ...c, ...patch } : c)) });
  const addCanary = () =>
    setCfg({ canaries: [...timingCfg.canaries, { kind: "asset", id: "SPY", signal: "score_13612", lookback: 12, threshold: 0, direction: "above" }] });
  const rmCanary = (i: number) => setCfg({ canaries: timingCfg.canaries.filter((_, ix) => ix !== i) });

  const data = timingQ.data && !timingQ.data.error ? timingQ.data : null;
  const mt = data?.market_timing;

  return (
    <div className="as-ws2 as-ws-tm">
      {/* ── 좌: 마켓 지수 게이트 프리셋 · 카나리 · 게이트 · 오버레이 설정 ── */}
      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">마켓 지수 게이트 <span className="as-note-inline">백테스터 마켓타이밍 → 자산배분 적용</span></div>
          <div className="as-seg as-seg-2">
            {(["kr", "us"] as const).map((m) => (
              <button key={m} className={timingCfg.market === m ? "on" : ""}
                onClick={() => setTimingCfg({ ...timingCfg, market: m })}>{m === "kr" ? "국내 ETF" : "미국 원본"}</button>
            ))}
          </div>
          <div className="as-tm-gates">
            {MARKET_GATES.map((g) => (
              <button key={g.id} className="as-tm-gate" onClick={() => applyGate(g)}>
                <span className="as-tm-gate-t">{g.label}</span>
                <span className="as-tm-gate-s">{g.sub}</span>
              </button>
            ))}
          </div>
          <div className="as-note">
            지수 추세·모멘텀이 <b>위험-온</b>이면 {loadedStrategy ? `불러온 전략(${loadedStrategy.name})` : "현재 포트폴리오"}를 유지,
            <b> 위험-오프</b>면 방어자산(IEF·SHY)으로 전환합니다 — 백테스터의 지수 조건 게이트(전량 청산)를 정적 배분에 적용한 형태.
            {timingCfg.market === "kr" && " 위험자산 프록시는 국내 대형주 ETF로 매핑됩니다."}
          </div>
        </section>

        <section className="as-card">
          <div className="as-card-title">카나리 신호 <span className="as-note-inline">위험-온/오프를 결정하는 관문 지표</span></div>
          {timingCfg.canaries.map((c, i) => (
            <div key={i} className="as-tm-canary">
              <button className="as-x" title="제거" onClick={() => rmCanary(i)}>×</button>
              <select className="as-tm-kind" value={c.kind}
                onChange={(e) => updCanary(i, { kind: e.target.value as "asset" | "indicator", id: e.target.value === "indicator" ? "VIXCLS" : "SPY", signal: e.target.value === "indicator" ? "threshold" : "score_13612" })}>
                <option value="asset">자산</option>
                <option value="indicator">지표</option>
              </select>
              <input className="as-tm-id" list={c.kind === "asset" ? "tm-assets" : "tm-inds"} value={c.id}
                onChange={(e) => updCanary(i, { id: e.target.value.toUpperCase() })} />
              {c.kind === "asset" ? (
                <>
                  <select className="as-tm-sig" value={c.signal} onChange={(e) => updCanary(i, { signal: e.target.value as CanarySignalType })}>
                    {ASSET_SIGNALS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                  </select>
                  {(c.signal === "abs_mom" || c.signal === "ma_month" || c.signal === "ma_day") && (
                    <input className="as-tm-num num" type="number" min={1} max={252} value={c.lookback}
                      title={c.signal === "ma_day" ? "일" : "개월"}
                      onChange={(e) => updCanary(i, { lookback: parseInt(e.target.value) || 1 })} />
                  )}
                </>
              ) : (
                <>
                  <select className="as-tm-sig" value={c.direction} onChange={(e) => updCanary(i, { direction: e.target.value as "above" | "below" })}>
                    <option value="above">임계 초과 시 통과</option>
                    <option value="below">임계 미만 시 통과</option>
                  </select>
                  <input className="as-tm-num num" type="number" step={0.1} value={c.threshold}
                    title="임계값" onChange={(e) => updCanary(i, { threshold: parseFloat(e.target.value) || 0 })} />
                </>
              )}
            </div>
          ))}
          <button className="as-chip sm" onClick={addCanary}>+ 카나리 추가</button>
          <div className="as-note">모멘텀 관문(0 초과)은 VAA·DAA식 위험-온 판정과 동일. 지표는 임계 방향으로 통과.</div>
        </section>

        <section className="as-card">
          <div className="as-card-title">브레드스 게이트</div>
          <label className="as-param">
            <span>통과 필요 수 <b className="num">{timingCfg.minBreadth === 0 ? `전부(${timingCfg.canaries.length})` : `${timingCfg.minBreadth} / ${timingCfg.canaries.length}`}</b></span>
            <input type="range" min={0} max={timingCfg.canaries.length} step={1} value={timingCfg.minBreadth}
              onChange={(e) => setCfg({ minBreadth: parseInt(e.target.value) })} />
            <em className="as-note-inline">0 = 카나리 전부 통과해야 위험-온 · k = k개 이상</em>
          </label>
        </section>

        <section className="as-card">
          <div className="as-card-title">자산군 스위치</div>
          <label className="as-tm-set">
            <span>위험-온 자산 <em className="as-note-inline">(비우면 현재 포트폴리오 유지)</em></span>
            <input value={onText} placeholder="예: SPY, QQQ, EFA (비움=보유 유지)"
              onChange={(e) => setOnText(e.target.value)} onBlur={() => setCfg({ riskOnAssets: parseList(onText) })} />
          </label>
          <label className="as-tm-set">
            <span>위험-오프(방어) 자산</span>
            <input value={offText} placeholder="예: IEF, SHY"
              onChange={(e) => setOffText(e.target.value)} onBlur={() => setCfg({ riskOffAssets: parseList(offText) })} />
          </label>
          <div className="as-note">US ETF 티커는 국내 대응 ETF로 자동 매핑됩니다(KODEX·TIGER). 국내 종목코드도 사용 가능.</div>
        </section>

        <section className="as-card">
          <div className="as-card-title">추세 오버레이 <span className="as-note-inline">마켓타이밍 — 추세 이탈 자산은 현금화</span></div>
          <div className="as-seg">
            {(["none", "ma_day", "abs_mom"] as const).map((t) => (
              <button key={t} className={timingCfg.overlay.type === t ? "on" : ""}
                onClick={() => setCfg({ overlay: { ...timingCfg.overlay, type: t } })}>
                {t === "none" ? "없음" : t === "ma_day" ? "N일 이동평균" : "절대모멘텀"}
              </button>
            ))}
          </div>
          {timingCfg.overlay.type === "ma_day" && (
            <label className="as-param"><span>이동평균 <b className="num">{timingCfg.overlay.n}일</b></span>
              <input type="range" min={20} max={250} step={10} value={timingCfg.overlay.n}
                onChange={(e) => setCfg({ overlay: { ...timingCfg.overlay, n: parseInt(e.target.value) } })} /></label>
          )}
          {timingCfg.overlay.type === "abs_mom" && (
            <label className="as-param"><span>모멘텀 룩백 <b className="num">{timingCfg.overlay.lookback}개월</b></span>
              <input type="range" min={1} max={24} step={1} value={timingCfg.overlay.lookback}
                onChange={(e) => setCfg({ overlay: { ...timingCfg.overlay, lookback: parseInt(e.target.value) } })} /></label>
          )}
        </section>
      </aside>

      {/* ── 우: 판정 · 배분 · 시장 타이밍 ── */}
      <main className="as-center">
        <section className={`as-card${timingQ.isLoading ? " as-loading" : ""}`}>
          <div className="as-card-title">위험 국면 판정</div>
          {timingQ.isLoading && <div className="as-empty">카나리 계산 중…</div>}
          {timingQ.data?.error && <div className="as-err">{timingQ.data.message}</div>}
          {data && (
            <>
              <div className="as-tm-verdict">
                <span className={`as-tm-sig-badge ${data.canary.signal}`}>
                  {data.canary.signal === "risk_on" ? "위험-온 (RISK-ON)" : "위험-오프 (RISK-OFF)"}
                </span>
                <span className="num">통과 {data.canary.hits} / {data.canary.total} · 필요 {data.canary.need}</span>
                <span className="as-note-inline">{data.signal_label}</span>
              </div>
              <table className="as-metrics">
                <thead><tr><th>카나리</th><th>신호</th><th>값</th><th>통과</th></tr></thead>
                <tbody>
                  {data.canary.details.map((d, i) => (
                    <tr key={i}>
                      <td>{d.label}<span className="as-fb-code num"> {d.id}</span></td>
                      <td className="num">{d.signal}</td>
                      <td className="num">{d.value != null ? d.value : "—"}</td>
                      <td className="num" style={{ color: d.pass ? "var(--color-bull)" : "var(--color-bear)" }}>{d.pass ? "✓" : "✗"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>

        {data && (
          <section className="as-card">
            <div className="as-card-title">권고 배분
              <button className="as-fb-apply" disabled={!data.holdings.some((h) => h.weight > 0)} onClick={applyTiming}>이 배분 적용 →</button>
            </div>
            {data.holdings.filter((h) => h.weight > 0).map((h) => (
              <div key={h.ticker + h.code} className="as-wrow">
                <span className="as-wrow-nm">{h.label}{h.is_cash ? " (현금)" : ""}</span>
                <div className="as-wrow-bar"><i style={{ width: `${Math.min(h.weight, 100)}%`, background: h.is_cash ? "var(--t-muted)" : undefined }} /></div>
                <span className="num">{h.weight.toFixed(1)}%</span>
              </div>
            ))}
            {data.cash_pct > 0 && <div className="as-note">추세 이탈로 현금화 {data.cash_pct.toFixed(1)}% (오버레이 {data.overlay}).</div>}
            {!holdings.length && data.canary.signal === "risk_on" && !data.holdings.length && (
              <div className="as-empty">위험-온이나 위험-온 자산이 비어 있고 보유 포트폴리오도 없습니다 — 01 CONSTRUCT에서 자산을 담거나 위험-온 자산을 입력하세요.</div>
            )}
          </section>
        )}

        {mt?.composite && (
          <section className="as-card">
            <div className="as-card-title">시장 타이밍 컴포짓 <span className="as-note-inline">breadth·모멘텀·수익률곡선·신용·VIX</span></div>
            <div className="as-tm-mkt">
              <ConfidenceGauge value={mt.composite.score} height={100} />
              <div className="as-tm-mkt-lab">
                <b>{mt.composite.label}</b>
                <span className="num">{mt.composite.score}/100</span>
              </div>
            </div>
            {!!mt.components?.length && (
              <div className="as-tm-comps">
                {mt.components.map((c) => (
                  <div key={c.key} className="as-tm-comp">
                    <span>{c.label}</span>
                    <b className="num" style={{ color: c.score >= 60 ? "var(--color-bull)" : c.score <= 40 ? "var(--color-bear)" : "var(--t-muted)" }}>{c.score}</b>
                  </div>
                ))}
              </div>
            )}
            {!!mt.assets?.length && (
              <table className="as-metrics">
                <thead><tr><th>자산</th><th>vs 200일</th><th>12M모멘텀</th><th>RSI</th><th>추세</th></tr></thead>
                <tbody>
                  {mt.assets.slice(0, 8).map((a) => (
                    <tr key={a.ticker}>
                      <td>{a.label}</td>
                      <td className="num">{a.vs_ma200_pct != null ? `${a.vs_ma200_pct}%` : "—"}</td>
                      <td className="num">{a.mom_12m != null ? `${a.mom_12m}%` : "—"}</td>
                      <td className="num">{a.rsi != null ? a.rsi : "—"}</td>
                      <td className="num" style={{ color: a.trend === "상승" ? "var(--color-bull)" : a.trend === "하락" ? "var(--color-bear)" : "var(--t-muted)" }}>{a.trend}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="as-note">컴포짓·추세는 시장 전반(timing_panel) 기준 — 카나리 판정과 독립적인 참고 지표입니다.</div>
          </section>
        )}
      </main>

      <datalist id="tm-assets">{ASSET_SUGGEST.map((t) => <option key={t} value={t} />)}</datalist>
      <datalist id="tm-inds">{IND_SUGGEST.map(([id, lbl]) => <option key={id} value={id}>{lbl}</option>)}</datalist>
    </div>
  );
}
