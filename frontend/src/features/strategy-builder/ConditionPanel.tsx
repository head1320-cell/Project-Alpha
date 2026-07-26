"use client";

import { useState, useEffect } from "react";
import { Plus, X } from "lucide-react";
import { useBuilderStore } from "@/features/strategy-builder/store";
import { screenerApiAdvanced } from "@/entities/screener/api/ast";
import type { BuilderCondition, ConditionOperand, ConditionOperator } from "@/entities/strategy/model";

const OPS: { value: ConditionOperator; label: string }[] = [
  { value: "greater_than",  label: ">"  },
  { value: "less_than",     label: "<"  },
  { value: "greater_equal", label: ">=" },
  { value: "less_equal",    label: "<=" },
  { value: "cross_above",   label: "↑ 돌파" },
  { value: "cross_below",   label: "↓ 이탈" },
  { value: "equals",        label: "=="  },
];

const PRICE_FIELDS = ["close", "open", "high", "low"] as const;

// 재무 지표는 백엔드 fields 카탈로그에서 동적 로드 (스크리너와 동일한 단일 소스).
// 팩터를 백엔드에 추가하면 빌더 드롭다운에 자동 반영됨.
type FundGroup = { category: string; label: string; fields: { id: string; label: string }[] };
const DEFAULT_FUNDAMENTAL = "roic";

// 모듈 레벨 캐시 (한 번만 fetch, 모든 인스턴스 공유)
let _fundGroupsCache: FundGroup[] | null = null;
let _fundGroupsPromise: Promise<FundGroup[]> | null = null;

async function loadFundamentalGroups(): Promise<FundGroup[]> {
  if (_fundGroupsCache) return _fundGroupsCache;
  if (!_fundGroupsPromise) {
    _fundGroupsPromise = screenerApiAdvanced.fields().then((cat) => {
      // 스크리너 필드 카탈로그 → 빌더 재무 그룹. 펀더멘털 + 가격·수급 팩터.
      const allowed = new Set([
        "valuation", "quality", "profitability", "growth", "safety", "stability", "composite", "score", "dividend",
        "momentum", "volatility", "technical", "volume", "supply",
      ]);
      const groups: FundGroup[] = [];
      for (const c of cat.categories) {
        if (!allowed.has(c.id)) continue;
        groups.push({
          category: c.id, label: c.label,
          fields: c.fields.map((f) => ({ id: f.id, label: f.label })),
        });
      }
      _fundGroupsCache = groups;
      return groups;
    }).catch(() => []);
  }
  return _fundGroupsPromise;
}

function useFundamentalGroups(): FundGroup[] {
  const [groups, setGroups] = useState<FundGroup[]>(_fundGroupsCache ?? []);
  useEffect(() => {
    if (!_fundGroupsCache) loadFundamentalGroups().then(setGroups);
  }, []);
  return groups;
}

interface Props { section: "entry" | "exit" }

export function ConditionPanel({ section }: Props) {
  const { indicators, entry, exit, addCondition, removeCondition, updateCondition, setLogic } = useBuilderStore();
  const group = section === "entry" ? entry : exit;
  const title = section === "entry" ? "진입 조건 (Entry)" : "청산 조건 (Exit)";

  return (
    <div className="flex flex-col gap-2">
      {/* Header with logic toggle */}
      <div className="flex items-center justify-between">
        <span className="label">{title}</span>
        <div className="flex items-center gap-1">
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>조건 결합:</span>
          {(["AND", "OR"] as const).map((l) => (
            <button key={l} onClick={() => setLogic(section, l)}
              className="text-xs px-2 py-0.5 rounded transition-all"
              style={{
                background: group.logic === l ? "rgba(0,180,216,0.15)" : "transparent",
                border: `1px solid ${group.logic === l ? "var(--accent)" : "var(--border)"}`,
                color: group.logic === l ? "var(--accent)" : "var(--text-muted)",
                cursor: "pointer",
              }}>
              {l}
            </button>
          ))}
        </div>
      </div>

      {/* Condition rows */}
      {group.conditions.map((cond) => (
        <ConditionRow
          key={cond.id}
          cond={cond}
          indicators={indicators.map((i) => ({ alias: i.alias, outputs: i.output }))}
          onChange={(patch) => updateCondition(section, cond.id, patch)}
          onRemove={() => removeCondition(section, cond.id)}
        />
      ))}

      {/* Add button */}
      <button
        onClick={() => addCondition(section)}
        className="flex items-center gap-1.5 px-3 py-2 rounded-md text-xs transition-all w-full justify-center"
        style={{
          background: "transparent",
          border: `1px dashed var(--border)`,
          color: "var(--text-muted)", cursor: "pointer",
        }}
        onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; e.currentTarget.style.color = "var(--accent)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-muted)"; }}
      >
        <Plus size={11} /> 조건 추가
      </button>

      {group.conditions.length === 0 && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", textAlign: "center", padding: "8px 0" }}>
          조건을 추가하세요
        </div>
      )}
    </div>
  );
}

function ConditionRow({
  cond, indicators, onChange, onRemove,
}: {
  cond: BuilderCondition;
  indicators: { alias: string; outputs: string }[];
  onChange: (patch: Partial<BuilderCondition>) => void;
  onRemove: () => void;
}) {
  const fundGroups = useFundamentalGroups();
  function OperandSelect({ side }: { side: "left" | "right" }) {
    const operand = side === "left" ? cond.left : cond.right;
    const setOperand = (op: ConditionOperand) => onChange({ [side]: op });

    const type = operand.type;

    return (
      <div className="flex items-center gap-1">
        {/* Type selector */}
        <select
          className="select py-1 text-xs"
          style={{ width: 70 }}
          value={type}
          onChange={(e) => {
            const t = e.target.value as ConditionOperand["type"];
            if (t === "indicator") setOperand({ type: "indicator", indicatorAlias: indicators[0]?.alias, indicatorOutput: "value" });
            else if (t === "price") setOperand({ type: "price", priceField: "close" });
            else if (t === "fundamental") setOperand({ type: "fundamental", fundamentalField: DEFAULT_FUNDAMENTAL });
            else setOperand({ type: "value", value: 0 });
          }}
        >
          <option value="indicator">지표</option>
          <option value="price">가격</option>
          <option value="fundamental">팩터</option>
          <option value="value">값</option>
        </select>

        {/* Value input */}
        {type === "indicator" && (
          <select
            className="select py-1 text-xs"
            style={{ width: 110 }}
            value={operand.indicatorAlias ?? ""}
            onChange={(e) => setOperand({ ...operand, indicatorAlias: e.target.value })}
          >
            {indicators.map((i) => <option key={i.alias} value={i.alias}>{i.alias}</option>)}
            {indicators.length === 0 && <option value="">--지표 추가 필요--</option>}
          </select>
        )}
        {type === "fundamental" && (
          <select
            className="select py-1 text-xs"
            style={{ width: 150 }}
            value={operand.fundamentalField ?? DEFAULT_FUNDAMENTAL}
            onChange={(e) => setOperand({ ...operand, fundamentalField: e.target.value })}
          >
            {fundGroups.length === 0 && <option value={DEFAULT_FUNDAMENTAL}>로딩...</option>}
            {fundGroups.map((g) => (
              <optgroup key={g.category} label={g.label}>
                {g.fields.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
              </optgroup>
            ))}
          </select>
        )}
        {type === "price" && (
          <select
            className="select py-1 text-xs"
            style={{ width: 80 }}
            value={operand.priceField ?? "close"}
            onChange={(e) => setOperand({ ...operand, priceField: e.target.value as typeof PRICE_FIELDS[number] })}
          >
            {PRICE_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        )}
        {type === "value" && (
          <input
            className="input py-1 text-xs"
            style={{ width: 70 }}
            type="number"
            value={operand.value ?? 0}
            onChange={(e) => setOperand({ ...operand, value: parseFloat(e.target.value) })}
          />
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5 p-2 rounded-md"
         style={{ background: "var(--slate-light)", border: "1px solid var(--border)" }}>

      <OperandSelect side="left" />

      {/* Operator */}
      <select
        className="select py-1 text-xs"
        style={{ width: 76 }}
        value={cond.operator}
        onChange={(e) => onChange({ operator: e.target.value as ConditionOperator })}
      >
        {OPS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>

      <OperandSelect side="right" />

      {/* Delete */}
      <button onClick={onRemove}
        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: 2, marginLeft: "auto" }}>
        <X size={11} />
      </button>
    </div>
  );
}
