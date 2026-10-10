"use client";

import { useState, useMemo } from "react";
import { Search, Plus, X, ChevronDown } from "lucide-react";
import clsx from "clsx";
import { INDICATORS, CANDLESTICK_PATTERNS, CATEGORY_LABELS, CATEGORY_ORDER } from "@/features/strategy-builder/constants";
import { useBuilderStore } from "@/features/strategy-builder/store";
import type { BuilderIndicator, IndicatorCategory } from "@/entities/strategy/model";

export function IndicatorPanel() {
  const { indicators, addIndicator, removeIndicator, updateIndicator } = useBuilderStore();
  const [search, setSearch]   = useState("");
  const [cat, setCat]         = useState<IndicatorCategory | "all">("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const allItems = useMemo(() => [...INDICATORS, ...CANDLESTICK_PATTERNS], []);

  const filtered = useMemo(() => allItems.filter((def) => {
    const matchCat = cat === "all" || def.category === cat;
    const q = search.toLowerCase();
    const matchQ = !q || def.id.includes(q) || def.nameKo.toLowerCase().includes(q) || def.name.toLowerCase().includes(q);
    return matchCat && matchQ;
  }), [allItems, cat, search]);

  return (
    <div className="flex flex-col gap-3">
      {/* Search */}
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md"
           style={{ background: "var(--navy)", border: "1px solid var(--border)" }}>
        <Search size={12} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
        <input
          className="flex-1 bg-transparent text-xs outline-none"
          style={{ color: "var(--text-primary)" }}
          placeholder="지표 검색..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {/* Category tabs — scrollable */}
      <div className="flex gap-1 overflow-x-auto pb-0.5" style={{ scrollbarWidth: "none" }}>
        {(["all", ...CATEGORY_ORDER] as const).map((c) => (
          <button key={c}
            onClick={() => setCat(c)}
            className="whitespace-nowrap text-xs px-2 py-1 rounded transition-all shrink-0"
            style={{
              background: cat === c ? "rgba(0,180,216,0.15)" : "transparent",
              border: `1px solid ${cat === c ? "var(--accent)" : "var(--border)"}`,
              color: cat === c ? "var(--accent)" : "var(--text-muted)",
              cursor: "pointer",
            }}>
            {c === "all" ? "전체" : CATEGORY_LABELS[c]}
          </button>
        ))}
      </div>

      {/* Indicator grid */}
      <div className="flex flex-col gap-1 overflow-auto" style={{ maxHeight: 220 }}>
        {filtered.map((def) => (
          <button key={def.id}
            onClick={() => addIndicator(def.id)}
            className="flex items-center justify-between px-2.5 py-1.5 rounded text-left transition-all group"
            style={{
              background: "var(--slate-light)",
              border: "1px solid transparent",
              cursor: "pointer",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "transparent")}
          >
            <div>
              <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>
                {def.nameKo}
              </div>
              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{def.id}</div>
            </div>
            <Plus size={12} style={{ color: "var(--accent)", opacity: 0 }}
              className="group-hover:opacity-100 transition-opacity shrink-0" />
          </button>
        ))}
        {filtered.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: 12, textAlign: "center", padding: 16 }}>
            검색 결과 없음
          </div>
        )}
      </div>

      {/* Added indicators */}
      {indicators.length > 0 && (
        <>
          <div className="divider" />
          <div className="label">추가된 지표 ({indicators.length})</div>
          <div className="flex flex-col gap-1.5">
            {indicators.map((ind) => (
              <IndicatorRow key={ind.id} ind={ind}
                expanded={expanded === ind.id}
                onToggle={() => setExpanded(expanded === ind.id ? null : ind.id)}
                onRemove={() => removeIndicator(ind.id)}
                onChange={(params) => updateIndicator(ind.id, params)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function IndicatorRow({
  ind, expanded, onToggle, onRemove, onChange,
}: {
  ind: BuilderIndicator; expanded: boolean;
  onToggle: () => void; onRemove: () => void;
  onChange: (p: Record<string, number | string>) => void;
}) {
  const def = INDICATORS.find((d) => d.id === ind.indicatorId)
           || CANDLESTICK_PATTERNS.find((d) => d.id === ind.indicatorId);

  return (
    <div className="rounded-md overflow-hidden" style={{ border: "1px solid var(--border)" }}>
      {/* Header row */}
      <div className="flex items-center gap-2 px-2.5 py-2"
           style={{ background: "var(--slate-light)" }}>
        <div className="flex-1 flex items-center gap-2 cursor-pointer" onClick={onToggle}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--accent)", fontFamily: "monospace" }}>
            {ind.alias}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-secondary)" }}>
            {def?.nameKo ?? ind.indicatorId}
          </div>
          {def?.params.length ? (
            <ChevronDown size={11} style={{ color: "var(--text-muted)", transform: expanded ? "rotate(180deg)" : "none", transition: "transform 0.15s" }} />
          ) : null}
        </div>
        <button onClick={onRemove} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: 2 }}>
          <X size={11} />
        </button>
      </div>

      {/* Expanded params */}
      {expanded && def && def.params.length > 0 && (
        <div className="px-2.5 py-2 flex flex-wrap gap-2"
             style={{ background: "var(--navy)", borderTop: "1px solid var(--border)" }}>
          {def.params.map((p) => (
            <div key={p.name} className="flex flex-col gap-0.5">
              <div style={{ fontSize: 10, color: "var(--text-muted)" }}>{p.name}</div>
              <input
                className="input py-0.5 px-2 text-xs"
                style={{ width: 70 }}
                type="number"
                value={ind.params[p.name] ?? p.default}
                min={p.min}
                max={p.max}
                step={p.step ?? 1}
                onChange={(e) => onChange({ ...ind.params, [p.name]: parseFloat(e.target.value) })}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
