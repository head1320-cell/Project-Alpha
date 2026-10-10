"use client";

import { useState } from "react";
import { Copy, Download, Check } from "lucide-react";
import { useBuilderStore } from "@/features/strategy-builder/store";
import { builderStateToYaml, builderStateToPython } from "@/features/strategy-builder/yamlgen";
import type { BuilderState } from "@/entities/strategy/model";

// ── RiskPanel ─────────────────────────────────────────────────────────────────

export function RiskPanel() {
  const { risk, updateRisk } = useBuilderStore();

  const RiskRow = ({
    label, enabled, percent,
    onToggle, onPercent,
  }: {
    label: string; enabled: boolean; percent: number;
    onToggle: () => void; onPercent: (v: number) => void;
  }) => (
    <div className="flex items-center gap-3 py-2"
         style={{ borderBottom: "1px solid var(--border)" }}>
      <button
        onClick={onToggle}
        className="w-8 h-4 rounded-full transition-all shrink-0"
        style={{
          background: enabled ? "var(--accent)" : "var(--border)",
          position: "relative", cursor: "pointer", border: "none",
        }}>
        <span style={{
          position: "absolute", top: 2,
          left: enabled ? "calc(100% - 14px)" : 2,
          width: 12, height: 12, borderRadius: "50%",
          background: "white", transition: "left 0.15s",
          display: "block",
        }} />
      </button>
      <span style={{ fontSize: 12, color: enabled ? "var(--text-primary)" : "var(--text-muted)", flex: 1 }}>
        {label}
      </span>
      <div className="flex items-center gap-1">
        <input
          className="input py-1 text-xs"
          style={{ width: 58 }}
          type="number"
          disabled={!enabled}
          value={percent}
          min={0.1} max={50} step={0.5}
          onChange={(e) => onPercent(parseFloat(e.target.value))}
        />
        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>%</span>
      </div>
    </div>
  );

  return (
    <div className="flex flex-col">
      <RiskRow
        label="손절 (Stop Loss)"
        enabled={risk.stopLoss.enabled}
        percent={risk.stopLoss.percent}
        onToggle={() => updateRisk({ stopLoss: { ...risk.stopLoss, enabled: !risk.stopLoss.enabled } })}
        onPercent={(v) => updateRisk({ stopLoss: { ...risk.stopLoss, percent: v } })}
      />
      <RiskRow
        label="익절 (Take Profit)"
        enabled={risk.takeProfit.enabled}
        percent={risk.takeProfit.percent}
        onToggle={() => updateRisk({ takeProfit: { ...risk.takeProfit, enabled: !risk.takeProfit.enabled } })}
        onPercent={(v) => updateRisk({ takeProfit: { ...risk.takeProfit, percent: v } })}
      />
      <RiskRow
        label="트레일링 스탑"
        enabled={risk.trailingStop.enabled}
        percent={risk.trailingStop.percent}
        onToggle={() => updateRisk({ trailingStop: { ...risk.trailingStop, enabled: !risk.trailingStop.enabled } })}
        onPercent={(v) => updateRisk({ trailingStop: { ...risk.trailingStop, percent: v } })}
      />
    </div>
  );
}

// ── MetaPanel ─────────────────────────────────────────────────────────────────

export function MetaPanel() {
  const { metadata, updateMetadata } = useBuilderStore();
  const [tagInput, setTagInput] = useState("");

  const addTag = () => {
    const t = tagInput.trim();
    if (t && !metadata.tags.includes(t)) {
      updateMetadata({ tags: [...metadata.tags, t] });
    }
    setTagInput("");
  };

  return (
    <div className="flex flex-col gap-3">
      {[
        { label: "전략 ID",   key: "id",          placeholder: "my_strategy" },
        { label: "전략 이름", key: "name",         placeholder: "나의 전략" },
        { label: "설명",      key: "description",  placeholder: "전략 설명을 입력하세요" },
      ].map(({ label, key, placeholder }) => (
        <div key={key} className="flex flex-col gap-1">
          <div className="label">{label}</div>
          <input
            className="input text-xs"
            value={(metadata as unknown as Record<string, string>)[key]}
            placeholder={placeholder}
            onChange={(e) => updateMetadata({ [key]: e.target.value })}
          />
        </div>
      ))}

      <div className="flex flex-col gap-1">
        <div className="label">카테고리</div>
        <select
          className="select text-xs"
          value={metadata.category}
          onChange={(e) => updateMetadata({ category: e.target.value })}
        >
          {["trend", "momentum", "mean_reversion", "volatility", "oscillator", "custom"].map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <div className="label">태그</div>
        <div className="flex gap-1">
          <input
            className="input text-xs flex-1"
            value={tagInput}
            placeholder="태그 입력..."
            onChange={(e) => setTagInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addTag()}
          />
          <button className="btn-ghost text-xs px-2" onClick={addTag}>+</button>
        </div>
        {metadata.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {metadata.tags.map((t) => (
              <span key={t} className="badge-blue flex items-center gap-1">
                {t}
                <button
                  onClick={() => updateMetadata({ tags: metadata.tags.filter((x) => x !== t) })}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "inherit", padding: 0, lineHeight: 1 }}>
                  ×
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── PreviewPanel ──────────────────────────────────────────────────────────────

export function PreviewPanel() {
  const state = useBuilderStore();
  const [tab, setTab] = useState<"yaml" | "python">("yaml");
  const [copied, setCopied] = useState(false);

  const yaml   = builderStateToYaml(state as BuilderState);
  const python = builderStateToPython(state as BuilderState);
  const content = tab === "yaml" ? yaml : python;

  const copy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const download = () => {
    const name  = state.metadata.id || "strategy";
    const ext   = tab === "yaml" ? `${name}.kis.yaml` : `${name}.py`;
    const blob  = new Blob([content], { type: "text/plain" });
    const url   = URL.createObjectURL(blob);
    const a     = document.createElement("a");
    a.href = url; a.download = ext; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full">
      {/* Tabs + actions */}
      <div className="flex items-center justify-between px-3 py-2 border-b"
           style={{ borderColor: "var(--border)" }}>
        <div className="flex gap-0 p-0.5 rounded" style={{ background: "var(--navy)" }}>
          {(["yaml", "python"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className="px-2.5 py-1 rounded text-xs font-semibold transition-all"
              style={{
                background: tab === t ? "var(--slate)" : "transparent",
                color: tab === t ? "var(--accent)" : "var(--text-muted)",
                border: "none", cursor: "pointer",
              }}>
              {t === "yaml" ? "YAML" : "Python"}
            </button>
          ))}
        </div>
        <div className="flex gap-1">
          <button className="btn-ghost text-xs py-1 px-2 flex items-center gap-1" onClick={copy}>
            {copied ? <Check size={11} /> : <Copy size={11} />}
            {copied ? "복사됨" : "복사"}
          </button>
          <button className="btn-ghost text-xs py-1 px-2 flex items-center gap-1" onClick={download}>
            <Download size={11} /> Export
          </button>
        </div>
      </div>

      {/* Code block */}
      <pre className="flex-1 overflow-auto p-3 text-xs"
           style={{
             fontFamily: "var(--font-geist-mono, monospace)",
             color: "var(--text-secondary)",
             background: "var(--navy)",
             margin: 0,
             lineHeight: 1.6,
             whiteSpace: "pre-wrap",
             wordBreak: "break-word",
           }}>
        {content}
      </pre>
    </div>
  );
}
