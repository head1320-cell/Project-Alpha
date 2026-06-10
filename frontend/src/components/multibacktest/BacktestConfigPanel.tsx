"use client";

import { useState } from "react";
import {
  Play, Loader2, Calendar, Layers, Settings, Sparkles,
} from "lucide-react";

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
}

interface Props {
  strategies: Strategy[];
  onRun: (config: Config) => Promise<void>;
  running: boolean;
}

export default function BacktestConfigPanel({ strategies, onRun, running }: Props) {
  const today = new Date().toISOString().slice(0, 10);
  const twoYearsAgo = new Date();
  twoYearsAgo.setFullYear(twoYearsAgo.getFullYear() - 2);
  const defaultStart = twoYearsAgo.toISOString().slice(0, 10);

  const [config, setConfig] = useState<Config>({
    strategy_ids: strategies.filter((s) => s.is_active).map((s) => s.id),
    start_date: defaultStart,
    end_date: today,
    initial_capital: 10_000_000,
    allocation_method: "hrp_macro",
    rebalance_policy: "monthly",
    netting_enabled: true,
    macro_overlay_enabled: true,
    commission_rate: 0.00015,
    slippage_rate: 0.0005,
  });

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
              등록된 전략 없음 — Multi-Strategy 페이지에서 먼저 등록
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
              <option value="hrp_macro">③ HRP + Macro</option>
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
              <option value="regime_change">국면 변경</option>
            </select>
          </div>
        </div>

        {/* Toggles */}
        <div style={{ display: "flex", gap: 12, marginTop: 4 }}>
          <Toggle label="중앙 청산 (Netting)" value={config.netting_enabled}
                   onChange={(v) => setConfig({ ...config, netting_enabled: v })} />
          <Toggle label="매크로 오버레이" value={config.macro_overlay_enabled}
                   onChange={(v) => setConfig({ ...config, macro_overlay_enabled: v })} />
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

function Toggle({ label, value, onChange }: {
  label: string; value: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div onClick={() => onChange(!value)} style={{
      flex: 1, padding: "8px 10px", cursor: "pointer",
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
