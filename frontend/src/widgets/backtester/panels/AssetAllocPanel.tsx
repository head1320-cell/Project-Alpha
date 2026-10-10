"use client";
// 자산배분 옵션 (젠포트 미러) — ETF 바스켓을 주식 전략과 병행, 주기 리밸런싱.
//   ETF % + 주식 % (잔여=현금) · 프리셋(중립/공격/안정/직접) · 리밸런싱 주기 ·
//   ETF 매수 기준가±% · 바스켓 표(가중 편집) · 자산군 그룹 관리 모달(ETF 선택).

import React from "react";
import { useState } from "react";
import { X, Plus } from "lucide-react";
import { Section, QuickStepper, Segmented, Field, GroupedSelect } from "@/shared/ui/kit";
import OffsetInput from "./OffsetInput";
import dynamic from "next/dynamic";
// 기본이 '닫힘' 인 창 — Radix Dialog 무게를 /backtest 첫 로드에서 뺀다(실측 +20 kB).
const WatchGroupModal = dynamic(() => import("./WatchGroupModal"), { ssr: false });
import { FILL_PRICE_GROUPS_NO_EXPR } from "@/entities/backtest/fillPrice";
import { ASSET_PRESETS, presetBasket } from "@/entities/backtest/assetPresets";
import type { BacktestStrategy, AssetAllocState, BasketLeg } from "@/entities/backtest/strategy";


export default function AssetAllocPanel({ s, set }: {
  s: BacktestStrategy; set: React.Dispatch<React.SetStateAction<BacktestStrategy>>;
}) {
  // ★포커스 복귀를 명시적으로 되돌린다★ 창을 `next/dynamic` 으로 떼어내면 클릭 시점에는
  // Dialog 가 아직 마운트되지 않아, Radix 가 기억하는 복귀 대상이 트리거가 아닐 수 있다.
  // 닫은 뒤 포커스가 body 로 떨어지면 키보드 사용자는 목록의 어디에 있었는지 잃는다.
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const a = s.assetAlloc;
  const [modalOpen, setModalOpen] = useState(false);
  const patch = (p: Partial<AssetAllocState>) => set((x) => ({ ...x, assetAlloc: { ...x.assetAlloc, ...p } }));
  const cashPct = Math.max(0, 100 - a.etfPct - a.stockPct);
  const wsum = a.basket.reduce((t, l) => t + (l.weightPct || 0), 0);

  const applyPreset = (id: AssetAllocState["preset"]) =>
    patch({ preset: id, basket: id === "custom" ? a.basket : presetBasket(id) });

  const addLegs = (_name: string, _tickers: string[], items: Array<{ code: string; name: string }>) => {
    const have = new Set(a.basket.map((l) => l.ticker));
    const fresh: BasketLeg[] = items.filter((it) => !have.has(it.code))
      .map((it) => ({ ticker: it.code, name: it.name, weightPct: 0 }));
    if (fresh.length) patch({ preset: "custom", basket: [...a.basket, ...fresh] });
  };
  const setWeight = (i: number, w: number) =>
    patch({ preset: "custom", basket: a.basket.map((l, j) => (j === i ? { ...l, weightPct: w } : l)) });
  const removeLeg = (i: number) =>
    patch({ preset: "custom", basket: a.basket.filter((_, j) => j !== i) });
  const equalize = () => {
    if (!a.basket.length) return;
    const w = Math.round((100 / a.basket.length) * 10) / 10;
    patch({ basket: a.basket.map((l, i) => ({ ...l, weightPct: i === 0 ? 100 - w * (a.basket.length - 1) : w })) });
  };

  return (
    <Section title="ETF로 나눠 담기" hint="ETF 바스켓을 주식 전략과 함께 · 정한 주기마다 다시 맞춰요(자산배분)" tone="neutral"
      enabled={a.enabled} onToggle={(on) => patch({ enabled: on })}>
      <p className="bte-note">포트폴리오의 일정 비율을 ETF로 늘 들고 있어요. 남는 비율은 현금이에요.</p>

      <Field label="나누는 비율">
        <span className="bte-sm">ETF</span>
        <QuickStepper value={a.etfPct} onChange={(v) => patch({ etfPct: v })} chips={[5, 10, 30]} unit="%" min={0} max={100} />
        <span className="bte-sm">주식</span>
        <QuickStepper value={a.stockPct} onChange={(v) => patch({ stockPct: v })} chips={[30, 60]} unit="%" min={0} max={100} />
        <span className={`bte-note${a.etfPct + a.stockPct > 100 ? " bte-note--bad" : ""}`}>
          현금 {cashPct}%{a.etfPct + a.stockPct > 100 ? " — 합이 100%를 넘어요" : ""}
        </span>
      </Field>

      <Field label="다시 맞추는 주기">
        <Segmented value={String(a.rebalanceMonths)} onChange={(v) => patch({ rebalanceMonths: Number(v) })}
          options={[{ id: "1", label: "1개월" }, { id: "3", label: "3개월" }, { id: "6", label: "6개월" }, { id: "12", label: "12개월" }]} />
      </Field>

      <Field label="ETF 사는 가격">
        <GroupedSelect value={a.fillType} onChange={(id) => patch({ fillType: id })} groups={FILL_PRICE_GROUPS_NO_EXPR} />
        <OffsetInput value={a.offsetPct} onChange={(offsetPct) => patch({ offsetPct })} />
      </Field>

      {/* 자산군 프리셋 */}
      <Field label="자산군">
        <Segmented value={a.preset} onChange={(id) => applyPreset(id as AssetAllocState["preset"])}
          options={ASSET_PRESETS.map((p) => ({ id: p.id, label: p.label }))} />
      </Field>

      {/* 바스켓 표 */}
      <div className="bte-basket" role="table" aria-label="ETF 바스켓">
        <div className="bte-basket-row bte-basket-h" role="row">
          <span role="columnheader">종목코드</span><span role="columnheader">종목명</span><span role="columnheader" className="num">비중</span><span />
        </div>
        {a.basket.length === 0 ? (
          <p className="bte-note bte-basket-empty">담은 ETF가 없어요. 자산군을 고르거나 ‘자산군 추가’로 ETF를 담아요.</p>
        ) : a.basket.map((l, i) => (
          <div key={l.ticker} className="bte-basket-row" role="row">
            <span className="scr-code" role="cell">{l.ticker}</span>
            <span className="bte-basket-n" role="cell">{l.name || "몰라요"}</span>
            <span role="cell" className="num">
              <input type="number" value={l.weightPct} min={0} max={100} className="kit-num kit-num--sm" aria-label={`${l.name || l.ticker} 비중 %`}
                onChange={(e) => setWeight(i, Number(e.target.value) || 0)} />
            </span>
            <button type="button" className="bte-icon-btn" aria-label={`${l.name || l.ticker} 빼기`} onClick={() => removeLeg(i)}><X size={16} aria-hidden /></button>
          </div>
        ))}
      </div>
      <div className="bte-row">
        <button type="button" ref={triggerRef} className="tx-btn tx-btn--sub bte-group-add" onClick={() => setModalOpen(true)}>
          <Plus size={16} aria-hidden /> 자산군 추가
        </button>
        {a.basket.length > 0 && (
          <button type="button" className="kit-chip" onClick={equalize}>똑같이 나누기</button>
        )}
        <span className={`bte-note${wsum !== 100 ? " bte-note--warn" : ""}`}>
          비중 합 {wsum}%{wsum !== 100 ? " — 실행할 때 100%로 맞춰 계산해요" : ""}
        </span>
      </div>

      <p className="bte-note bte-note--warn">
        레버리지·인버스 ETF를 실제로 사려면 기본 예탁금과 사전 교육이 필요해요. 백테스트에는 상관없어요.
      </p>
      <p className="bte-note">ETF 몫은 주식 전략과 따로 들고 있어요. 매수 기준가에 닿지 못한 몫은 다음 주기에 다시 시도해요(보수적).</p>

      <WatchGroupModal open={modalOpen} etfOnly title="자산군 그룹 관리"
        onClose={() => { setModalOpen(false); // ★언마운트 뒤에 포커스를 준다★ 같은 틱에 주면 Radix 의 포커스 가드가 아직
        // 살아 있어 도로 가져간다 — 한 프레임 뒤에야 트리거가 실제로 포커스를 받는다.
        requestAnimationFrame(() => triggerRef.current?.focus()); }} onSave={addLegs} />
    </Section>
  );
}
