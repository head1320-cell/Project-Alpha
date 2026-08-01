"use client";
// 자산배분 옵션 (젠포트 미러) — ETF 바스켓을 주식 전략과 병행, 주기 리밸런싱.
//   ETF % + 주식 % (잔여=현금) · 프리셋(중립/공격/안정/직접) · 리밸런싱 주기 ·
//   ETF 매수 기준가±% · 바스켓 표(가중 편집) · 자산군 그룹 관리 모달(ETF 선택).

import React from "react";
import { useState } from "react";
import { X, Plus } from "lucide-react";
import { Section, SubToggle, QuickStepper, Segmented, Field, GroupedSelect } from "@/shared/ui/kit";
import OffsetInput from "./OffsetInput";
import dynamic from "next/dynamic";
// 기본이 '닫힘' 인 창 — Radix Dialog 무게를 /backtest 첫 로드에서 뺀다(실측 +20 kB).
const WatchGroupModal = dynamic(() => import("./WatchGroupModal"), { ssr: false });
import { FILL_PRICE_GROUPS_NO_EXPR } from "@/entities/backtest/fillPrice";
import { ASSET_PRESETS, presetBasket } from "@/entities/backtest/assetPresets";
import type { BacktestStrategy, AssetAllocState, BasketLeg } from "@/entities/backtest/strategy";

const wbox: React.CSSProperties = {
  fontFamily: "var(--bs-font-mono)", fontSize: 13, width: 64, textAlign: "center",
  padding: "5px 8px", border: "1px solid var(--border-strong)",
  borderRadius: "var(--bs-border-radius)", background: "var(--bg-card)", color: "var(--text-primary)",
};

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
    <Section title="자산배분 옵션" hint="ETF 바스켓 · 주기 리밸런싱" tone="neutral"
      enabled={a.enabled} onToggle={(on) => patch({ enabled: on })}>
      <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 4 }}>
        전체 포트폴리오 자산의 일정 비율을 ETF로 상시 보유하도록 설정합니다. 잔여는 현금.
      </div>

      <Field label="자산 배분 비중">
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>ETF</span>
        <QuickStepper value={a.etfPct} onChange={(v) => patch({ etfPct: v })} chips={[5, 10, 30]} unit="%" min={0} max={100} />
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>주식</span>
        <QuickStepper value={a.stockPct} onChange={(v) => patch({ stockPct: v })} chips={[30, 60]} unit="%" min={0} max={100} />
        <span style={{ fontSize: 11, color: cashPct < 0 ? "#dc2626" : "var(--text-muted)" }}>
          현금 {cashPct}%{a.etfPct + a.stockPct > 100 ? " — 합이 100%를 넘습니다" : ""}
        </span>
      </Field>

      <Field label="리밸런싱 주기">
        <Segmented value={String(a.rebalanceMonths)} onChange={(v) => patch({ rebalanceMonths: Number(v) })}
          options={[{ id: "1", label: "1개월" }, { id: "3", label: "3개월" }, { id: "6", label: "6개월" }, { id: "12", label: "12개월" }]} />
      </Field>

      <Field label="ETF 매수 기준">
        <GroupedSelect value={a.fillType} onChange={(id) => patch({ fillType: id })} groups={FILL_PRICE_GROUPS_NO_EXPR} />
        <OffsetInput value={a.offsetPct} onChange={(offsetPct) => patch({ offsetPct })} />
      </Field>

      {/* 자산군 프리셋 */}
      <Field label="자산군 선택">
        <Segmented value={a.preset} onChange={(id) => applyPreset(id as AssetAllocState["preset"])}
          options={ASSET_PRESETS.map((p) => ({ id: p.id, label: p.label }))} />
      </Field>

      {/* 바스켓 표 */}
      <div style={{ border: "1px solid var(--border)", borderRadius: "var(--bs-border-radius)", overflow: "hidden", marginTop: 4 }}>
        <div style={{ display: "grid", gridTemplateColumns: "76px 1fr 84px 32px", gap: 6, padding: "7px 10px", fontSize: 11, color: "var(--text-secondary)", background: "var(--bg-section)" }}>
          <span>종목코드</span><span>종목명</span><span style={{ textAlign: "right" }}>배분</span><span />
        </div>
        {a.basket.length === 0 ? (
          <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "10px 10px" }}>
            자산군이 없습니다 — 프리셋을 선택하거나 "자산군 추가"로 ETF를 담으세요.
          </div>
        ) : a.basket.map((l, i) => (
          <div key={l.ticker} style={{ display: "grid", gridTemplateColumns: "76px 1fr 84px 32px", gap: 6, padding: "7px 10px", alignItems: "center", borderTop: "1px solid var(--border)", fontSize: 13 }}>
            <span style={{ fontFamily: "var(--bs-font-mono)", fontSize: 12, color: "var(--text-secondary)" }}>{l.ticker}</span>
            <span style={{ color: "var(--text-primary)", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.name || "—"}</span>
            <input type="number" value={l.weightPct} min={0} max={100}
              onChange={(e) => setWeight(i, Number(e.target.value) || 0)} style={{ ...wbox, width: 70, justifySelf: "end" }} />
            <button type="button" aria-label="제거" onClick={() => removeLeg(i)}
              style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", display: "flex", justifySelf: "center" }}><X size={14} /></button>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 9, marginTop: 7 }}>
        <button type="button" ref={triggerRef} onClick={() => setModalOpen(true)}
          style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: "var(--bs-border-radius)", padding: "5px 10px", cursor: "pointer" }}>
          <Plus size={13} /> 자산군 추가
        </button>
        {a.basket.length > 0 && (
          <button type="button" onClick={equalize}
            style={{ fontSize: 12, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: "var(--bs-border-radius)", padding: "5px 10px", cursor: "pointer" }}>
            균등 배분
          </button>
        )}
        <span style={{ fontSize: 11, color: wsum !== 100 ? "#d97706" : "var(--text-muted)" }}>
          배분 합 {wsum}%{wsum !== 100 ? " — 100%로 맞춰주세요 (실행 시 정규화)" : ""}
        </span>
      </div>

      <div style={{ fontSize: 11, color: "#d97706", marginTop: 9, lineHeight: 1.6 }}>
        ⚠ ETF 사전 교육 의무 안내 — 레버리지/인버스 ETF 투자를 위해서는 기본 예탁금 충족 및 사전 교육 이수가 필요합니다 (백테스트는 무관, 실거래 시 유의).
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
        ETF 슬리브는 주식 전략과 별도 보유 · 매수 기준가 미도달분은 다음 주기 재시도 (보수적)
      </div>

      <WatchGroupModal open={modalOpen} etfOnly title="자산군 그룹 관리"
        onClose={() => { setModalOpen(false); // ★언마운트 뒤에 포커스를 준다★ 같은 틱에 주면 Radix 의 포커스 가드가 아직
        // 살아 있어 도로 가져간다 — 한 프레임 뒤에야 트리거가 실제로 포커스를 받는다.
        requestAnimationFrame(() => triggerRef.current?.focus()); }} onSave={addLegs} />
    </Section>
  );
}
