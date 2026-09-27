"use client";
/**
 * 노드 파라미터 편집기 — ★폼은 서버 스키마가 만든다★ (BI3)
 * ==========================================================================
 * 범위·선택지는 `params_schema`(서버 요청 모델) 한 곳에만 있다. 여기서는 칸의 종류만 정하고,
 * 값이 옳은지는 서버 검증(`/validate`)이 노드 위에 빨갛게 말한다 — 화면이 규칙을 따로 들면
 * 두 곳이 갈라진다.
 *
 * ★빈 칸 = 서버 기본값★ — 비우면 파라미터에서 키를 지운다(0 이나 "" 를 넣지 않는다).
 */
import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { fieldsOf, type FieldSpec, type NodeCatalogEntry, type PgNode } from "@/entities/portfolio-graph";

type Params = Record<string, unknown>;

const show = (v: unknown) => (v === undefined || v === null ? "" : String(v));

function without(p: Params, k: string): Params {
  const next = { ...p };
  delete next[k];
  return next;
}

function JsonField({ f, value, onChange }: { f: FieldSpec; value: unknown; onChange: (v: unknown) => void }) {
  const [text, setText] = useState(() => (value === undefined ? "" : JSON.stringify(value, null, 2)));
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setText(value === undefined ? "" : JSON.stringify(value, null, 2)); }, [value]);
  return (
    <>
      <textarea className="pg-field-json" rows={Math.min(12, Math.max(3, text.split("\n").length))}
                value={text} spellCheck={false}
                placeholder={f.defaultValue !== undefined ? `기본값: ${JSON.stringify(f.defaultValue)}` : "JSON"}
                onChange={(e) => setText(e.target.value)}
                onBlur={() => {
                  if (!text.trim()) { setErr(null); onChange(undefined); return; }
                  try { onChange(JSON.parse(text)); setErr(null); }
                  catch (e) { setErr(`JSON 이 아닙니다 — ${(e as Error).message}. 반영하지 않았습니다.`); }
                }} />
      {err && <div className="pg-field-err">{err}</div>}
    </>
  );
}

/** 목록 칸 — 입력 중에는 글자 그대로 두고, 벗어날 때 목록으로 반영한다(쉼표가 먹히지 않게). */
export function ListField({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) {
  const joined = Array.isArray(value) ? value.join(", ") : "";
  const [text, setText] = useState(joined);
  useEffect(() => { setText(joined); }, [joined]);
  const commit = () => {
    const items = text.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
    onChange(items.length ? items : undefined);
  };
  return (
    <input className="pg-field-input" value={text} placeholder="쉼표로 구분 (예: 005930, 000660)"
           onChange={(e) => setText(e.target.value)} onBlur={commit}
           onKeyDown={(e) => { if (e.key === "Enter") commit(); }} />
  );
}

function Field({ f, value, onChange }: { f: FieldSpec; value: unknown; onChange: (v: unknown) => void }) {
  const placeholder = f.defaultValue !== undefined && f.defaultValue !== null
    ? `기본값 ${String(f.defaultValue)}` : f.nullable ? "비움 = 없음" : "";
  switch (f.kind) {
    case "boolean":
      return (
        <select className="pg-field-input" value={value === undefined ? "" : String(value)}
                onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value === "true")}>
          <option value="">기본값 ({String(f.defaultValue ?? false)})</option>
          <option value="true">켜기</option>
          <option value="false">끄기</option>
        </select>
      );
    case "enum":
      return (
        <select className="pg-field-input" value={show(value)}
                onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}>
          <option value="">기본값{f.defaultValue !== undefined ? ` (${String(f.defaultValue)})` : ""}</option>
          {(f.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      );
    case "number":
    case "integer":
      return (
        <input className="pg-field-input" type="number" value={show(value)} placeholder={placeholder}
               min={f.min} max={f.max} step={f.kind === "integer" ? 1 : "any"}
               onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))} />
      );
    case "string_list":
      return <ListField value={value} onChange={onChange} />;
    case "string":
      return (
        <input className="pg-field-input" value={show(value)} placeholder={placeholder}
               onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)} />
      );
    default:
      return <JsonField f={f} value={value} onChange={onChange} />;
  }
}

export function NodeInspector({ node, entry, onChange, onRemove }: {
  node: PgNode;
  entry: NodeCatalogEntry | undefined;
  onChange: (params: Params) => void;
  onRemove: () => void;
}) {
  const params = node.data.params ?? {};
  const fields = fieldsOf(entry?.params_schema ?? null);
  return (
    <section className="pg-inspector">
      <header className="pg-panel-head">
        <div>
          <div className="pg-panel-title">{entry?.label ?? node.data.kind}</div>
          <div className="pg-panel-sub">{node.id}</div>
        </div>
        <button type="button" className="pg-btn pg-btn--danger" onClick={onRemove} title="노드 삭제">
          <Trash2 size={13} />
        </button>
      </header>
      {entry?.description && <p className="pg-panel-note">{entry.description}</p>}
      {!entry && (
        <>
          <p className="pg-field-err">{node.data.unknownReason ?? "모르는 노드입니다."}</p>
          <pre className="pg-raw">{JSON.stringify(params, null, 2)}</pre>
        </>
      )}
      {entry && fields.length === 0 && <p className="pg-panel-note">설정할 파라미터가 없습니다.</p>}
      {fields.map((f) => (
        <label key={f.name} className="pg-field">
          <span className="pg-field-label">
            {f.title}{f.required ? " *" : ""}
            {(f.min !== undefined || f.max !== undefined) && (
              <span className="pg-field-range"> [{f.min ?? "−∞"} ~ {f.max ?? "∞"}]</span>
            )}
          </span>
          <Field f={f} value={params[f.name]}
                 onChange={(v) => onChange(v === undefined ? without(params, f.name) : { ...params, [f.name]: v })} />
          {/* 서버 x-ui 도움말(BN N2) — 전문가 칸도 무엇을 움직이는지(또는 움직이지 않는지) 쉬운 말로 */}
          {f.ui.help && <span className="pg-field-help">{f.ui.label !== f.title ? `${f.ui.label} — ` : ""}{f.ui.help}</span>}
        </label>
      ))}
    </section>
  );
}
