"use client";
/**
 * 설정 탭 — 기본(쉬운 질문) ↔ 전문가(모든 파라미터) (BJ3 · 목업 승인본)
 * ==========================================================================
 * 위에는 n8n 식 **받는 것 / 내는 것**. 기본 화면은 서버 x-ui 의 `tier: basic` 칸만 질문형으로:
 * 선택 카드(options) · 슬라이더(widget=slider) · 프리셋 칩 · 켬/끔. 전문가 토글을 켜면 모든
 * 파라미터를 쉬운 이름 + 파라미터 키 + 범위로(`NodeInspector`). ★규칙은 서버에만 있다★ —
 * 값이 틀리면 서버 검증이 노드 위에 빨갛게 말한다. 빈 칸 = 서버 기본값(키를 지운다).
 */
import { useState } from "react";
import type { Edge } from "reactflow";
import { Copy, Plus, X } from "lucide-react";
import {
  basicFieldsOf, fieldsOf, itemSchemaOf, type FieldSpec, type JsonSchema, type NodeCatalogEntry, type NodeRunResult, type PgNode,
  type SaveResult,
} from "@/entities/portfolio-graph";
import { ListField, NodeInspector } from "./NodeInspector";
import { TickerField } from "./TickerInput";
import { FilterEditor } from "./FilterEditor";
import { PickField } from "./PickField";
import { PORT_PLAIN } from "./GraphNode";

type Params = Record<string, unknown>;
const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

function setOrClear(p: Params, k: string, v: unknown): Params {
  const next = { ...p };
  if (v === undefined) delete next[k]; else next[k] = v;
  return next;
}

/** 행 칸의 선택지 — 서버가 준 이름표(`x-ui.options`)가 우선, 없으면 스키마의 enum 값을 그대로. */
function rowOptions(x: FieldSpec): Record<string, string> | null {
  if (x.ui.options) return x.ui.options;
  if (x.kind === "enum" && x.options?.length) return Object.fromEntries(x.options.map((o) => [o, o]));
  return null;
}

/** 객체 목록(예: 내 생각 목록) — 항목 스키마의 기본 칸만 한 줄씩. 전문가 칸은 전문가 설정에서. */
function ObjectList({ f, item, value, onChange }: {
  f: FieldSpec; item: JsonSchema; value: unknown; onChange: (v: unknown) => void;
}) {
  const rows = Array.isArray(value) ? (value as Params[]) : [];
  const fields = fieldsOf(item).filter((x) => x.ui.tier === "basic");
  const blank = Object.fromEntries(fields.filter((x) => x.defaultValue !== undefined && x.defaultValue !== null)
    .map((x) => [x.name, x.defaultValue]));
  const put = (i: number, row: Params) => onChange(rows.map((r, j) => (j === i ? row : r)));
  return (
    <div className="pg-basic-field" data-field={f.name}>
      <div className="pg-q">{f.ui.question ?? f.ui.label}</div>
      {rows.length === 0 && <p className="pg-help">아직 없어요.</p>}
      {rows.map((row, i) => (
        <div key={i} className="pg-objrow">
          {fields.map((x) => (
            <label key={x.name} className="pg-objcell">
              <span>{x.ui.label}</span>
              {x.kind === "string_list" ? (
                <ListField value={row[x.name]} onChange={(v) => put(i, setOrClear(row, x.name, v))} />
              ) : rowOptions(x) ? (
                <select className="pg-field-input" value={String(row[x.name] ?? x.defaultValue ?? "")}
                        onChange={(e) => put(i, setOrClear(row, x.name, x.kind === "integer" || x.kind === "number"
                          ? Number(e.target.value) : e.target.value))}>
                  {Object.entries(rowOptions(x) ?? {}).map(([k, lab]) => <option key={k} value={k}>{lab}</option>)}
                </select>
              ) : x.kind === "string" ? (
                // ★글자 칸은 글자로★ 예전에는 숫자 입력으로 그려 종목코드 "000660" 이 660 이 됐다(BL3 W5 에서 발견).
                <input className="pg-field-input" type="text" value={row[x.name] === undefined ? "" : String(row[x.name])}
                       placeholder={x.defaultValue !== undefined && x.defaultValue !== null ? String(x.defaultValue) : ""}
                       onChange={(e) => put(i, setOrClear(row, x.name, e.target.value === "" ? undefined : e.target.value))} />
              ) : (
                <input className="pg-field-input" type="number" min={x.min} max={x.max} step="any"
                       value={row[x.name] === undefined ? "" : String(row[x.name])}
                       placeholder={x.defaultValue !== undefined ? String(x.defaultValue) : ""}
                       onChange={(e) => put(i, setOrClear(row, x.name, e.target.value === "" ? undefined : Number(e.target.value)))} />
              )}
            </label>
          ))}
          <button type="button" className="pg-icon-btn" aria-label={`${i + 1}번째 항목 지우기`}
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}><X size={14} /></button>
        </div>
      ))}
      <button type="button" className="pg-add" onClick={() => onChange([...rows, { ...blank }])}>
        <Plus size={14} /> {f.ui.label} 추가
      </button>
      {f.ui.help && <p className="pg-help">{f.ui.help}</p>}
    </div>
  );
}

/**
 * 프리셋 + 직접 정하기 (BO O1) — 초보자는 칩 셋 중 하나, 전문가는 "직접 정하기" 로 슬라이더.
 * 값이 칩에 없으면 처음부터 직접 정하기 상태. 비워 두면 서버가 쓰는 값(`empty_value`)을 "기본" 으로 표시만 한다.
 */
function PresetSlider({ f, value, onChange }: { f: FieldSpec; value: unknown; onChange: (v: unknown) => void }) {
  const presets = f.ui.presets ?? [];
  const onPreset = (v: unknown) => presets.some((p) => same(p.value, v));
  // 칩에 없는 값이면 늘 직접 정하기 — 상태로 들고 있지 않아 다른 노드로 옮겨도 어긋나지 않는다.
  const [forced, setCustom] = useState(false);
  const custom = forced || (value !== undefined && value !== null && !onPreset(value));
  const shown = value !== undefined ? value : f.ui.empty_value;
  const min = f.min ?? 0, max = f.max ?? 1;
  const v = typeof shown === "number" ? shown : min;
  return (
    <div className="pg-basic-field" data-field={f.name}>
      <div className="pg-q">{f.ui.question ?? f.ui.label}</div>
      <div className="pg-chips" role="group" aria-label={f.ui.label}>
        {presets.map((p) => {
          const on = !custom && same(shown, p.value);
          return (
            <button key={p.label} type="button" className={`pg-chip${on ? " on" : ""}`} aria-pressed={on}
                    onClick={() => { setCustom(false); onChange(p.value === null ? undefined : p.value); }}>
              {p.label}{value === undefined && same(f.ui.empty_value, p.value) && <span className="pg-chip-default"> · 기본</span>}
            </button>
          );
        })}
        <button type="button" className={`pg-chip pg-chip--custom${custom ? " on" : ""}`} aria-pressed={custom}
                onClick={() => setCustom(true)}>직접 정하기</button>
      </div>
      {custom && (
        <div className="pg-custom">
          <input className="pg-slider" type="range" min={min} max={max} step={f.kind === "integer" ? 1 : 0.5}
                 value={v} aria-label={`${f.ui.label} 직접 정하기`} onChange={(e) => onChange(Number(e.target.value))} />
          <div className="pg-slider-ends"><span>{f.ui.ends?.[0] ?? min}</span><span className="pg-slider-v">{v.toFixed(1)}</span><span>{f.ui.ends?.[1] ?? max}</span></div>
        </div>
      )}
      {f.ui.help && <p className="pg-help">{f.ui.help}</p>}
    </div>
  );
}

function BasicField({ f, value, root, onChange }: {
  f: FieldSpec; value: unknown; root: JsonSchema | null; onChange: (v: unknown) => void;
}) {
  const eff = value !== undefined ? value : f.defaultValue;
  const item = f.kind === "json" ? itemSchemaOf(f, root) : null;
  if (item) return <ObjectList f={f} item={item} value={eff} onChange={onChange} />;
  const q = <div className="pg-q">{f.ui.question ?? f.ui.label}</div>;
  const help = f.ui.help ? <p className="pg-help">{f.ui.help}</p> : null;

  if (f.ui.options && Object.keys(f.ui.options).length > 12) {
    // 선택지가 12개를 넘으면(예: 시나리오 19개) 카드 벽 대신 한 줄 목록 — 고른 것이 한눈에 보인다.
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <select className="pg-select" value={String(eff ?? "")} aria-label={f.ui.label}
                onChange={(e) => onChange(e.target.value)}>
          {Object.entries(f.ui.options).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        {help}
      </div>
    );
  }
  if (f.ui.options) {
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <div className="pg-choices">
          {Object.entries(f.ui.options).map(([k, label]) => (
            <button key={k} type="button" className={`pg-choice${same(eff, k) ? " on" : ""}`} aria-pressed={same(eff, k)}
                    onClick={() => onChange(k)}>
              <b>{label}</b>
            </button>
          ))}
        </div>
        {help}
      </div>
    );
  }
  if (f.ui.widget === "text") {
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <textarea className="pg-text" rows={f.name === "title" ? 1 : 3} value={typeof eff === "string" ? eff : ""}
                  aria-label={f.ui.label} maxLength={f.raw.maxLength}
                  onChange={(e) => onChange(e.target.value === "" && f.defaultValue === undefined ? undefined : e.target.value)} />
        {help}
      </div>
    );
  }
  if (f.ui.widget === "pick" && f.ui.source) {
    // 저장된 것에서 고르기 — 등록된 전략(여럿) · 연구 기록(하나). 목록은 기존 문에서 온다.
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <PickField source={f.ui.source} multi={f.kind !== "string"} value={eff} onChange={onChange} />
        {help}
      </div>
    );
  }
  if (f.ui.widget === "filter") {
    // 스크리너 조건 — 프리셋 칩으로 시작하고, 줄 편집기로 고친다(규칙은 서버 검증).
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        {f.ui.presets && (
          <div className="pg-chips">
            {f.ui.presets.map((p) => (
              <button key={p.label} type="button" className={`pg-chip${same(eff, p.value) ? " on" : ""}`} aria-pressed={same(eff, p.value)}
                      onClick={() => onChange(p.value)}>{p.label}</button>
            ))}
          </div>
        )}
        <FilterEditor value={eff} onChange={onChange} />
        {help}
      </div>
    );
  }
  if (f.ui.presets && f.ui.widget === "slider" && (f.kind === "number" || f.kind === "integer")
      && f.min !== undefined && f.max !== undefined) {
    return <PresetSlider f={f} value={value} onChange={onChange} />;
  }
  if (f.ui.presets) {
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <div className="pg-chips">
          {f.ui.presets.map((p) => (
            <button key={p.label} type="button" className={`pg-chip${same(eff, p.value) ? " on" : ""}`} aria-pressed={same(eff, p.value)}
                    onClick={() => onChange(p.value === null ? undefined : p.value)}>{p.label}</button>
          ))}
        </div>
        {help}
      </div>
    );
  }
  if (f.ui.widget === "slider" && (f.kind === "number" || f.kind === "integer") && f.min !== undefined && f.max !== undefined) {
    const v = typeof eff === "number" ? eff : f.min;
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <input className="pg-slider" type="range" min={f.min} max={f.max} step={f.kind === "integer" ? 1 : (f.max - f.min) / 100}
               value={v} aria-label={f.ui.label} onChange={(e) => onChange(Number(e.target.value))} />
        <div className="pg-slider-ends"><span>{f.ui.ends?.[0] ?? f.min}</span><span className="pg-slider-v">{v.toFixed(1)}</span><span>{f.ui.ends?.[1] ?? f.max}</span></div>
        {help}
      </div>
    );
  }
  if (f.ui.widget === "tickers") {
    // 종목 이름 찾기(BN N2) — 코드 목록은 그대로, 이름은 서버 종목 검색에서만.
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <TickerField value={eff} onChange={onChange} />
        {help}
      </div>
    );
  }
  if (f.kind === "string_list") {
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <ListField value={eff} onChange={onChange} />
        {help}
      </div>
    );
  }
  if (f.kind === "boolean") {
    const on = eff === true;
    return (
      <div className="pg-basic-field" data-field={f.name}>
        {q}
        <div className="pg-chips">
          <button type="button" className={`pg-chip${on ? " on" : ""}`} aria-pressed={on} onClick={() => onChange(true)}>네</button>
          <button type="button" className={`pg-chip${!on ? " on" : ""}`} aria-pressed={!on} onClick={() => onChange(false)}>아니요</button>
        </div>
        {help}
      </div>
    );
  }
  return null;   // 기본 화면에 알맞은 위젯이 없는 칸은 전문가 설정에서 다룬다.
}

/** 저장하기 (BK W4) — ★계산은 쓰지 않는다★ 서버가 다시 계산해 이 미리보기와 같을 때만 한 번 저장한다. */
function SaveBox({ result, stale, onSave, label, followUp }: {
  result?: NodeRunResult; stale: boolean; onSave: () => Promise<SaveResult>; label?: string | null;
  followUp?: { label: string; run: (savedId: string) => void } | null;
}) {
  const [savedId, setSavedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const ready = result?.status === "ok" && !!result.view_hash && !stale;
  const why = !result ? "먼저 계산해 주세요." : stale ? "바뀐 설정으로 다시 계산한 뒤 저장할 수 있어요."
    : result.status !== "ok" ? "이 노드가 계산되지 않아 저장할 것이 없어요." : null;
  return (
    <div className="pg-save">
      <button type="button" className="pg-btn pg-btn--primary pg-save-btn" disabled={!ready || busy}
              onClick={async () => {
                setBusy(true); setMsg(null);
                try {
                  const r = await onSave();
                  setMsg(r.ok ? { ok: true, text: r.text ?? "저장했어요" } : { ok: false, text: r.message });
                  setSavedId(r.ok ? r.saved_id : null);
                } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
                finally { setBusy(false); }
              }}>
        {busy ? "저장하는 중…" : label ?? "이 미리보기를 저장하기"}
      </button>
      <p className="pg-help">{why ?? "지금 본 미리보기를 한 번 저장해요. 주문은 나가지 않아요."}</p>
      {msg && <p className={`pg-save-msg${msg.ok ? "" : " pg-save-msg--err"}`} role="status">{msg.text}</p>}
      {followUp && savedId && (
        <button type="button" className="pg-btn pg-btn--primary pg-save-follow" onClick={() => followUp.run(savedId)}>{followUp.label}</button>
      )}
    </div>
  );
}

/** 기본 층 질문들 — 설정 탭과 간단히 보기(BM C4)가 같은 위젯을 쓴다(고르는 칸이 먼저, 나머지는 서버 순서). */
export function BasicFields({ entry, params, onChange }: {
  entry: NodeCatalogEntry | undefined; params: Params; onChange: (p: Params) => void;
}) {
  const basic = basicFieldsOf(entry?.params_schema ?? null, params);
  return (
    <>
      {basic.map((f) => <BasicField key={f.name} f={f} value={params[f.name]} root={entry?.params_schema ?? null}
                                    onChange={(v) => onChange(setOrClear(params, f.name, v))} />)}
    </>
  );
}

export function SettingsPanel({ node, entry, nodes, edges, catalog, expert, onExpert, onChange, onRemove, onDuplicate,
  result, stale, onSave, saveFollowUp }: {
  node: PgNode;
  entry: NodeCatalogEntry | undefined;
  nodes: PgNode[];
  edges: Edge[];
  catalog: NodeCatalogEntry[];
  expert: boolean;
  onExpert: (v: boolean) => void;
  onChange: (p: Params) => void;
  onRemove: () => void;
  onDuplicate: () => void;
  result?: NodeRunResult;
  stale: boolean;
  onSave: () => Promise<SaveResult>;
  /** 저장 뒤 이어서 할 일(BL3 W1 — 백테스트를 시작하면 '결과 불러오기 노드 추가'). */
  saveFollowUp?: { label: string; run: (savedId: string) => void } | null;
}) {
  const params = node.data.params ?? {};
  const plainOf = (id: string) => {
    const k = nodes.find((n) => n.id === id)?.data.kind;
    return catalog.find((c) => c.type === k)?.plain_label ?? k ?? id;
  };
  const incoming = edges.filter((e) => e.target === node.id);
  const receives = (entry?.inputs ?? []).map((p) => {
    const e = incoming.find((x) => x.targetHandle === p.name);
    const nm = PORT_PLAIN[p.type] ?? p.name;
    return e ? `${nm} ← ${plainOf(e.source)}` : p.required === false ? `${nm}(선택, 비어 있음)` : `${nm}(아직 연결 안 됨)`;
  });
  // 고르는 칸(카드)이 먼저 — "어떤 방식으로" 가 "얼마나" 보다 앞선 질문이다. 나머지는 서버 순서.
  // `show_if` 로 지금 방식에서 뜻이 없는 칸은 숨긴다(BO O1).
  const basic = basicFieldsOf(entry?.params_schema ?? null, params);
  const basicRendered = basic.map((f) => ({ f, el: <BasicField key={f.name} f={f} value={params[f.name]}
                                                               root={entry?.params_schema ?? null}
                                                               onChange={(v) => onChange(setOrClear(params, f.name, v))} /> }));

  return (
    <section className="pg-settings">
      {entry && (
        <dl className="pg-io">
          <div><dt>받는 것</dt><dd>{receives.length ? receives.join(", ") : "없어요 — 여기서 시작해요."}</dd></div>
          <div><dt>내는 것</dt><dd>{entry.outputs.map((o) => PORT_PLAIN[o.type] ?? o.name).join(", ") || "없어요"}</dd></div>
        </dl>
      )}
      {!expert && entry && (
        <div className="pg-basic">
          {basicRendered.map((x) => x.el)}
          {basic.length === 0 && <p className="pg-help">바꿀 설정이 없어요.</p>}
          <p className="pg-help">바꾸지 않은 칸은 서버 기본값을 써요.</p>
        </div>
      )}
      {entry?.savable && <SaveBox key={node.id} result={result} stale={stale} onSave={onSave} label={entry.save_label}
                                         followUp={saveFollowUp} />}
      <div className="pg-actions">
        <button type="button" className="pg-btn pg-dup" onClick={onDuplicate} title="같은 입력으로 하나 더 (Ctrl+D)">
          <Copy size={14} /> 복제해서 비교하기
        </button>
      </div>
      <label className="pg-mode">
        <span>전문가 설정 보기</span>
        <input type="checkbox" role="switch" className="pg-switch" checked={expert} onChange={(e) => onExpert(e.target.checked)} />
      </label>
      {(expert || !entry) && <NodeInspector node={node} entry={entry} onChange={onChange} onRemove={onRemove} />}
    </section>
  );
}
