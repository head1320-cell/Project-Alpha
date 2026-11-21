"use client";
/**
 * 노드 카드 위젯 (CF1) — 가까이(확대 ≥ 1.05)에서 카드 안에서 바로 고치는 기본 설정 2~4칸.
 * ==========================================================================
 * ★칸은 서버가 정한다★ — `x-ui.tier: "basic"` 칸 중 카드에 맞는 것(고르기·프리셋·슬라이더·예/아니요)만, 설정 판과 같은 순서.
 * 값 쓰기는 설정 판과 같은 길(`updateParams` + `setOrClear`)이라 되돌리기·예전 결과(하류)가 그대로 따라온다.
 * 표식은 `.pg-cw-*` — 설정 판의 `.pg-basic-field` 와 다르다(같은 칸이 판과 카드에 동시에 보일 때 둘을 가른다).
 */
import {
  CARD_WIDGETS_MAX, cardControlOf, constraintsSummary, maxPresetActive, mergeMaxPreset, sameValue, setOrClear, type FieldSpec, type JsonSchema,
} from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "./store";

type Params = Record<string, unknown>;

/** 한 줄 고르기의 선택지 — 선택지(서버 순서) · 프리셋 · 예/아니요. 값은 JSON 글로 담아 무엇이든 그대로 되돌린다. */
function choicesOf(f: FieldSpec): { label: string; value: unknown }[] {
  if (f.ui.options) {
    const order = f.ui.order ?? [];
    return Object.entries(f.ui.options)
      .sort(([a], [b]) => (order.indexOf(a) + 1 || 1e9) - (order.indexOf(b) + 1 || 1e9))
      .map(([value, label]) => ({ label, value }));
  }
  if (f.ui.presets) return f.ui.presets.map((p) => ({ label: p.label, value: p.value }));
  return [{ label: "네", value: true }, { label: "아니요", value: false }];
}

function CardField({ f, value, root, onChange }: {
  f: FieldSpec; value: unknown; root: JsonSchema | null; onChange: (v: unknown) => void;
}) {
  const eff = value !== undefined ? value : f.defaultValue;
  const control = cardControlOf(f, root);
  const q = f.ui.question ?? f.ui.label;
  if (control === "slider") {
    const v = typeof eff === "number" ? eff : f.min!;
    const step = f.kind === "integer" ? 1 : (f.max! - f.min!) / 100;
    return (
      <label className="pg-cw-f" data-field={f.name}>
        <span className="pg-cw-q">{q}</span>
        <span className="pg-cw-row">
          <input className="pg-cw-range" type="range" min={f.min} max={f.max} step={step} value={v} aria-label={f.ui.label}
                 onChange={(e) => onChange(Number(e.target.value))} />
          <span className="pg-cw-v">{Number.isInteger(v) ? v : v.toFixed(1)}{f.ui.unit ?? ""}</span>
        </span>
      </label>
    );
  }
  const choices = choicesOf(f);
  // 제약(P2) — 칩은 한 종목 최대만 고른다: 다른 제약이 있어도 켜지고, 고르면 나머지는 그대로 둔다(설정 판의 편집기와 같은 규칙).
  const cons = f.ui.widget === "constraints";
  const at = choices.findIndex((c) => (cons ? maxPresetActive(eff, c.value) : sameValue(eff, c.value)));
  return (
    <label className="pg-cw-f" data-field={f.name}>
      <span className="pg-cw-q">{q}</span>
      <select className="pg-cw-select" aria-label={f.ui.label} value={at >= 0 ? String(at) : "custom"}
              onChange={(e) => {
                const c = choices[Number(e.target.value)];
                if (!c) return;
                // 프리셋의 null 은 "서버 기본값" — 설정 판과 같이 칸을 지운다.
                onChange(cons ? mergeMaxPreset(eff, c.value) : f.ui.presets && c.value === null ? undefined : c.value);
              }}>
        {at < 0 && <option value="custom" disabled>직접 정한 값{eff !== undefined && eff !== null
          ? ` (${cons ? constraintsSummary(eff) ?? "" : String(eff)})` : ""}</option>}
        {choices.map((c, i) => <option key={i} value={String(i)}>{c.label}</option>)}
      </select>
    </label>
  );
}

export function NodeWidgets({ id, fields, more, params, schema }: {
  id: string; fields: FieldSpec[]; more: boolean; params: Params; schema: JsonSchema | null;
}) {
  if (!fields.length && !more) return null;
  const write = (name: string, v: unknown) => usePortfolioGraph.getState().updateParams(id, setOrClear(params, name, v));
  return (
    <div className="pg-cw nodrag nowheel" data-count={Math.min(fields.length, CARD_WIDGETS_MAX)}>
      {fields.map((f) => <CardField key={f.name} f={f} value={params[f.name]} root={schema} onChange={(v) => write(f.name, v)} />)}
      {more && (
        <button type="button" className="pg-cw-more"
                onClick={(e) => { e.stopPropagation(); const st = usePortfolioGraph.getState(); st.select(id); st.setTab("settings"); }}>
          설정 더 보기
        </button>
      )}
    </div>
  );
}
