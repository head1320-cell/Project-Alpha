"use client";
// 03 TIMING — 카나리 신호 + 마켓타이밍. 좌: 카나리 자산·지표(신호·임계·룩백) + 브레드스
// 게이트(k-of-N) + 위험-온/오프 자산군 + 추세 오버레이 / 우: 위험-온·오프 판정 + 결과 배분
// (적용) + 시장 타이밍 컴포짓(timing_panel 재사용) + 자산 추세표. 백엔드 POST /allocation/timing.
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { type TimingConfig, useAllocation } from "@/widgets/allocation/AllocationProvider";
import { ConfidenceGauge } from "@/widgets/allocation/parts";
import { TimingFactorModal } from "@/widgets/allocation/TimingFactorModal";
import { ThreeWayPanel } from "@/widgets/allocation/ThreeWayPanel";
import { allocationApi, type CanaryInput } from "@/entities/allocation/api";

import {
  ASSET_SUGGEST, IND_SUGGEST, MARKET_GATES, OFF_DEFENSIVE, type Gate,
} from "@/widgets/allocation/timingPresets";

const parseList = (s: string) => s.split(/[,\s]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);

export default function TimingWorkspace() {
  const { timingCfg, setTimingCfg, timingQ, applyTiming, applyTimingOverlay, holdings, loadedStrategy,
    attachedSnapshotId } = useAllocation();
  const [onText, setOnText] = useState(timingCfg.riskOnAssets.join(", "));
  const [offText, setOffText] = useState(timingCfg.riskOffAssets.join(", "));
  const [pickerOpen, setPickerOpen] = useState(false);
  // 팩터 라벨/메타 — 칩 표시에 사용(카탈로그 1회 로드, 모달과 캐시 공유)
  const catQ = useQuery({
    queryKey: ["allocation", "timing-factors"],
    queryFn: () => allocationApi.timingFactors(),
    staleTime: Infinity,
  });
  const factorMeta = React.useMemo(() => {
    const m: Record<string, { label: string }> = {};
    (catQ.data?.groups ?? []).forEach((g) => g.factors.forEach((f) => { m[f.id] = f; }));
    return m;
  }, [catQ.data]);

  const applyGate = (g: Gate) => {
    const cfg = g.build(timingCfg.market);
    setTimingCfg(cfg);
    setOnText(cfg.riskOnAssets.join(", "));
    setOffText(cfg.riskOffAssets.join(", "));
  };

  const setCfg = (patch: Partial<TimingConfig>) => setTimingCfg({ ...timingCfg, ...patch });
  const updCanary = (i: number, patch: Partial<CanaryInput>) =>
    setCfg({ canaries: timingCfg.canaries.map((c, ix) => (ix === i ? { ...c, ...patch } : c)) });
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
          <div className="as-card-title">타이밍 팩터
            <span className="as-note-inline">위험-온/오프를 결정하는 관문 — 팩터 창에서 통합 관리</span>
          </div>
          {timingCfg.canaries.length === 0 && (
            <div className="as-empty">팩터가 없습니다 — 아래에서 추가하세요.</div>
          )}
          <div className="tfc-list">
            {timingCfg.canaries.map((c, i) => {
              const meta = factorMeta[c.signal];
              const pv = Object.entries(c.params || {}).map(([k, v]) => `${k} ${v}`).join(" · ");
              return (
                <div key={i} className="tfc-chip">
                  <div className="tfc-chip-main">
                    <span className="tfc-chip-t">{meta?.label ?? c.signal}</span>
                    <span className="tfc-chip-tk num">{c.id}</span>
                    <span className="tfc-chip-cond num">
                      {c.direction === "above" ? ">" : "<"} {c.threshold}
                      {pv ? ` · ${pv}` : ""}
                    </span>
                  </div>
                  <div className="tfc-chip-acts">
                    <button className="as-chip sm" title="임계 방향 전환"
                      onClick={() => updCanary(i, { direction: c.direction === "above" ? "below" : "above" })}>⇄</button>
                    <input className="as-tm-num num" type="number" step={0.1} value={c.threshold}
                      title="임계값" onChange={(e) => updCanary(i, { threshold: parseFloat(e.target.value) || 0 })} />
                    <button className="as-x" title="제거" onClick={() => rmCanary(i)}>×</button>
                  </div>
                </div>
              );
            })}
          </div>
          <button className="as-fb-apply" onClick={() => setPickerOpen(true)}>+ 팩터 창에서 추가</button>
          <div className="as-note">
            모멘텀·이격도·돌파·오버나이트·국면 팩터를 한 창에서 검색·추가합니다. 각 팩터는
            TimingRule 공통 스키마로 등록되어 규칙 세트로 저장·재사용할 수 있습니다.
          </div>
        </section>

        <TimingFactorModal open={pickerOpen} onClose={() => setPickerOpen(false)}
          active={timingCfg.canaries}
          onAdd={(c) => setCfg({ canaries: [...timingCfg.canaries, c] })} />

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

        <section className="as-card">
          <div className="as-card-title">리스크 제어 <span className="as-note-inline">이진 게이트 → 연속 노출</span></div>
          <label className="as-tm-set" style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span>국면-확률 블렌드 <em className="as-note-inline">휩쏘 억제</em></span>
            <input type="checkbox" checked={timingCfg.regimeBlend}
              onChange={(e) => setCfg({ regimeBlend: e.target.checked })} />
          </label>
          <label className="as-tm-set" style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span>목표 변동성(연 %) <em className="as-note-inline">위험자산 노출 스케일</em></span>
            <input className="as-tm-num" type="number" min={0} max={40} step={1}
              value={timingCfg.targetVolPct ?? ""} placeholder="off"
              onChange={(e) => setCfg({ targetVolPct: e.target.value === "" ? null : Math.max(2, Math.min(40, +e.target.value)) })} />
          </label>
          <div className="as-note">블렌드: 국면확률로 온/오프 바스켓 연속 혼합. 목표변동성: 실현 변동성이 목표 초과 시 노출 축소(잔여 현금).</div>
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
              {(data.regime_blend || data.vol_target) && (
                <div className="as-tm-risk">
                  {data.regime_blend && (
                    <div className="as-tm-risk-row" title={data.regime_blend.note}>
                      <span className="as-tm-risk-k">국면-확률 블렌드</span>
                      <b className="num">P(위험선호) {data.regime_blend.p_risk_on}%</b>
                      <span className="as-note-inline">{Object.entries(data.regime_blend.probs).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(" · ")}</span>
                    </div>
                  )}
                  {data.vol_target && (
                    <div className="as-tm-risk-row" title={data.vol_target.note}>
                      <span className="as-tm-risk-k">목표 변동성</span>
                      <b className="num">{data.vol_target.target_pct}% ← 실현 {data.vol_target.realized_pct}%</b>
                      <span className="as-note-inline">노출 ×{data.vol_target.scale} · 현금 +{data.vol_target.cash_added_pct}%p</span>
                    </div>
                  )}
                </div>
              )}
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

        {/* 3자 비교 — 카나리 판정과 별개의 V2 3-상태 경로다(레거시 `passes()` 를 건드리지 않는다) */}
        <ThreeWayPanel canaries={timingCfg.canaries} market={timingCfg.market}
          snapshotId={attachedSnapshotId} />

        {data && (
          <section className="as-card">
            <div className="as-card-title">권고 배분
              {/* ★두 동작을 구별해 이름 붙인다★ (스펙 §8, Phase 10c)
                  오버레이는 전략 비중을 그대로 두고 노출만 줄인다. 교체는 권고 배분으로
                  **갈아탄다** — 위험-오프면 방어자산(IEF/SHY)이 들어오므로 배율로는 재현할 수
                  없는 별개의 능력이다. §8 이 금지하는 것은 조용한 덮어쓰기이지 명시적 교체가
                  아니므로, 남기되 무엇을 하는지 버튼과 안내에 적는다. */}
              <button className="as-fb-apply as-tm-overlay"
                disabled={!data.holdings.some((h) => h.weight > 0)} onClick={applyTimingOverlay}>
                오버레이로 적용 (전략 비중 유지)
              </button>
              <button className="as-chip as-tm-replace"
                disabled={!data.holdings.some((h) => h.weight > 0)} onClick={applyTiming}
                title="현재 보유 종목·비중을 권고 배분으로 교체합니다 — 되돌리려면 다시 구성해야 합니다">
                권고 배분으로 교체 →
              </button>
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

