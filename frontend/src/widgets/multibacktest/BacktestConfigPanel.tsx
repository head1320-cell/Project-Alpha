"use client";

import { useEffect, useState } from "react";
import {
  Play, Loader2, Calendar, Layers, Settings, Sparkles,
} from "lucide-react";

import {
  unsupportedReason, type MultistrategyAvailability,
} from "@/entities/multibacktest";

interface Strategy {
  id: number;
  name: string;
  favored_factor?: string;
  is_active: number | boolean;
}

interface Config {
  strategy_ids: number[];
  start_date: string;
  end_date: string;
  initial_capital: number;
  allocation_method: "inverse_vol" | "hrp" | "hrp_macro";
  rebalance_policy: "daily" | "weekly" | "monthly" | "quarterly" | "regime_change";
  netting_enabled: boolean;
  macro_overlay_enabled: boolean;
  commission_rate: number;
  slippage_rate: number;
  /** ★국면 판정 시장★ (BH3) — regime_change 트리거·결과의 국면 칸. 두 시장 라벨은 늘 실린다. */
  regime_market: "kr" | "us";
}

interface Props {
  strategies: Strategy[];
  onRun: (config: Config) => Promise<void>;
  running: boolean;
  /** `GET /availability` — ★안 되는 옵션과 그 사유는 서버가 말한다★ (BG6). */
  availability?: MultistrategyAvailability | null;
}

export default function BacktestConfigPanel({ strategies, onRun, running, availability = null }: Props) {
  const today = new Date().toISOString().slice(0, 10);
  const twoYearsAgo = new Date();
  twoYearsAgo.setFullYear(twoYearsAgo.getFullYear() - 2);
  const defaultStart = twoYearsAgo.toISOString().slice(0, 10);

  const [config, setConfig] = useState<Config>({
    strategy_ids: strategies.filter((s) => s.is_active).map((s) => s.id),
    start_date: defaultStart,
    end_date: today,
    initial_capital: 10_000_000,
    // ★기본은 hrp★ (BG6) — hrp_macro 는 R4 전까지 서버가 422 로 막는다.
    allocation_method: "hrp",
    rebalance_policy: "monthly",
    netting_enabled: true,
    // 매크로 오버레이는 hrp_macro 에서만 작동한다 — 다른 방법에서는 효과가 없다.
    macro_overlay_enabled: false,
    commission_rate: 0.00015,
    slippage_rate: 0.0005,
    // 기본 kr — 전략이 한국 주식이다. 지금은 KR 빈티지가 없어 국면이 대부분 미상이고,
    // 결과가 그렇게 말한다(적재되면 코드 변경 없이 산다).
    regime_market: "kr",
  });

  // 전략이 새로 등록·비활성되면 선택을 맞춘다 — 사라진 id 는 빼고 새 id 는 넣는다.
  const activeIds = strategies.filter((s) => s.is_active).map((s) => s.id).join(",");
  useEffect(() => {
    const ids = activeIds ? activeIds.split(",").map(Number) : [];
    setConfig((c) => {
      const kept = c.strategy_ids.filter((id) => ids.includes(id));
      const added = ids.filter((id) => !c.strategy_ids.includes(id));
      return { ...c, strategy_ids: [...kept, ...added] };
    });
  }, [activeIds]);

  const macroWhy = unsupportedReason(availability, "allocation_method", "hrp_macro");
  const regimeWhy = unsupportedReason(availability, "rebalance_policy", "regime_change");
  const overlayWhy = config.allocation_method !== "hrp_macro"
    ? "매크로 오버레이는 hrp_macro 에서만 작동해요 — 지금 방법에서는 켜도 효과가 없어요."
    : null;

  const toggleStrategy = (sid: number) => {
    setConfig((c) => ({
      ...c,
      strategy_ids: c.strategy_ids.includes(sid)
        ? c.strategy_ids.filter((id) => id !== sid)
        : [...c.strategy_ids, sid],
    }));
  };

  const canRun = config.strategy_ids.length > 0 && !running;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      {/* Left column: Strategy selection */}
      <div>
        <Label icon={Layers}>전략 선택 ({config.strategy_ids.length}개)</Label>
        <div style={{
          maxHeight: 200, overflowY: "auto",
          background: "#060a1a",
          border: "1px solid #1e2d4a", borderRadius: 6,
          padding: 6,
        }}>
          {strategies.length === 0 ? (
            <div style={{ padding: 12, fontSize: 11, color: "#6b7fa3",
                            textAlign: "center" }}>
              등록된 전략 없음 — 위 &apos;전략 등록&apos; 에서 완료된 백테스트 실행을 등록하세요
            </div>
          ) : strategies.map((s) => {
            const selected = config.strategy_ids.includes(s.id);
            return (
              <div key={s.id}
                    onClick={() => toggleStrategy(s.id)}
                    style={{
                      display: "flex", alignItems: "center", gap: 8,
                      padding: "6px 10px", cursor: "pointer",
                      borderRadius: 3, fontSize: 11,
                      background: selected ? "rgba(18,0,255,0.15)" : "transparent",
                      border: `1px solid ${selected ? "#1200ff60" : "transparent"}`,
                      marginBottom: 2,
                    }}>
                <input type="checkbox" checked={selected} readOnly
                        style={{ accentColor: "#1200ff" }} />
                <span style={{ flex: 1, color: selected ? "#fff" : "#a7c8ff",
                                 fontWeight: selected ? 600 : 400 }}>
                  #{s.id} · {s.name}
                </span>
                {s.favored_factor && (
                  <span style={{
                    fontSize: 9, padding: "1px 6px",
                    background: "#0a0e27", borderRadius: 2,
                    color: "#6b7fa3",
                  }}>
                    {s.favored_factor}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Right column: Settings */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* Dates */}
        <div>
          <Label icon={Calendar}>기간</Label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <input type="date" value={config.start_date}
                    onChange={(e) => setConfig({ ...config, start_date: e.target.value })}
                    style={inputStyle} />
            <input type="date" value={config.end_date}
                    onChange={(e) => setConfig({ ...config, end_date: e.target.value })}
                    style={inputStyle} />
          </div>
        </div>

        {/* Capital */}
        <div>
          <Label>초기 자본 (원)</Label>
          <input type="number" value={config.initial_capital}
                  onChange={(e) => setConfig({ ...config, initial_capital: Number(e.target.value) })}
                  step={1_000_000} min={100_000}
                  style={inputStyle} />
        </div>

        {/* Method + Rebalance — 2 selects */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
          <div>
            <Label icon={Sparkles}>배분 알고리즘</Label>
            <select value={config.allocation_method}
                    onChange={(e) => setConfig({ ...config, allocation_method: e.target.value as any })}
                    style={inputStyle}>
              <option value="inverse_vol">① InverseVolatility</option>
              <option value="hrp">② HRP</option>
              <option value="hrp_macro" disabled={macroWhy !== null}>
                ③ HRP + Macro{macroWhy ? " (R4 전까지 불가)" : ""}
              </option>
            </select>
          </div>
          <div>
            <Label icon={Settings}>리밸런싱</Label>
            <select value={config.rebalance_policy}
                    onChange={(e) => setConfig({ ...config, rebalance_policy: e.target.value as any })}
                    style={inputStyle}>
              <option value="daily">매일</option>
              <option value="weekly">매주</option>
              <option value="monthly">매월</option>
              <option value="quarterly">매분기</option>
              <option value="regime_change" disabled={regimeWhy !== null}>
                국면 변경{regimeWhy ? " (R4 전까지 불가)" : ""}
              </option>
            </select>
          </div>
        </div>

        {/* 국면 시장 — ★엄격 PIT(그 시점 공표 빈티지만)★ (BH3) */}
        <div>
          <Label>국면 시장 (regime_change·국면 표 기준)</Label>
          <select value={config.regime_market}
                  onChange={(e) => setConfig({ ...config, regime_market: e.target.value as "kr" | "us" })}
                  style={inputStyle}>
            <option value="kr">KR 국면 (빈티지 적재 전에는 대부분 미상)</option>
            <option value="us">US 국면 (FRED/ALFRED 빈티지)</option>
          </select>
        </div>

        {/* ★안 되는 이유는 서버가 준 문장 그대로★ */}
        {(macroWhy || regimeWhy) && (
          <div style={{ fontSize: 10, color: "#ffab91", lineHeight: 1.5 }}>
            {macroWhy && <div>HRP + Macro: {macroWhy}</div>}
            {regimeWhy && <div>국면 변경: {regimeWhy}</div>}
          </div>
        )}

        {/* Toggles */}
        <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
          <Toggle label="중앙 청산 (Netting)" value={config.netting_enabled}
                   onChange={(v) => setConfig({ ...config, netting_enabled: v })} />
          <Toggle label="매크로 오버레이" value={config.macro_overlay_enabled}
                   disabledReason={overlayWhy}
                   onChange={(v) => setConfig({ ...config, macro_overlay_enabled: v })} />
        </div>
        <div style={{ fontSize: 10, color: "#6b7fa3", lineHeight: 1.5 }}>
          네팅은 ★보고 전용★이에요 — 전략 보유로 잰 상쇄 절감을 따로 보여 줄 뿐 수익률에는
          더하지 않아요.
        </div>

        {/* Run button */}
        <button onClick={() => onRun(config)} disabled={!canRun}
                style={{
                  padding: "10px 20px", marginTop: 4,
                  background: canRun
                    ? "linear-gradient(135deg, #0d47a1 0%, #1200ff 100%)"
                    : "#1e2d4a",
                  color: "#fff", border: "none", borderRadius: 6,
                  fontSize: 13, fontWeight: 700,
                  cursor: canRun ? "pointer" : "not-allowed",
                  opacity: canRun ? 1 : 0.5,
                  display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                }}>
          {running ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
          {running ? "실행 중..." : "통합 백테스트 실행"}
        </button>
      </div>
    </div>
  );
}

function Label({ icon: Icon, children }: { icon?: any; children: React.ReactNode }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 5,
      fontSize: 10, fontWeight: 600, color: "#6b7fa3",
      textTransform: "uppercase", letterSpacing: "0.05em",
      marginBottom: 4,
    }}>
      {Icon && <Icon size={11} color="#1200ff" />}
      {children}
    </div>
  );
}

function Toggle({ label, value, onChange, disabledReason = null }: {
  label: string; value: boolean; onChange: (v: boolean) => void;
  disabledReason?: string | null;
}) {
  const disabled = disabledReason !== null;
  return (
    <div onClick={() => { if (!disabled) onChange(!value); }}
         title={disabledReason ?? undefined}
         aria-disabled={disabled}
         style={{
      flex: 1, padding: "8px 10px", cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
      background: value ? "rgba(105,240,174,0.1)" : "#060a1a",
      border: `1px solid ${value ? "#69f0ae60" : "#1e2d4a"}`,
      borderRadius: 4, fontSize: 11,
      display: "flex", alignItems: "center", gap: 6,
    }}>
      <div style={{
        width: 12, height: 12, borderRadius: 2,
        background: value ? "#69f0ae" : "transparent",
        border: `1px solid ${value ? "#69f0ae" : "#3a4f7a"}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 8, color: "#0a0e27", fontWeight: 700,
      }}>
        {value && "✓"}
      </div>
      <span style={{ color: value ? "#69f0ae" : "#6b7fa3", fontWeight: 600 }}>
        {label}
      </span>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "6px 10px",
  background: "#060a1a", color: "#e0e8f5",
  border: "1px solid #1e2d4a", borderRadius: 4,
  fontSize: 11, outline: "none",
  fontFamily: "'Roboto Mono', monospace",
};
