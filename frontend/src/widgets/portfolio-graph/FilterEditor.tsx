"use client";
/**
 * 스크리너 조건 편집기 (BK W2) — ★필드 목록은 서버 카탈로그 하나★
 * ==========================================================================
 * `/api/v1/screener/fields`(`filter_ast.FIELD_BY_ID`)에서 필드·연산자를 받아 한 줄씩 조건을 만든다.
 * 이 화면은 규칙을 모른다 — 모르는 필드·잘못된 값은 서버 검증이 노드 위에 사유로 말한다.
 * 기본 편집기는 최상위 조건 목록(그리고/또는)만 다루고, 중첩 묶음은 보존한 채 전문가 JSON 에 맡긴다.
 */
import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { screenerApiAdvanced } from "@/entities/screener";
import type { FieldsCatalog } from "@/shared/model/domain";

type Cond = { field: string; op: string; value?: number | null; value2?: number | null } & Record<string, unknown>;
type Group = { logic?: string; conditions?: Cond[]; groups?: unknown[] };

let catalogPromise: Promise<FieldsCatalog> | null = null;
function loadCatalog(): Promise<FieldsCatalog> {
  catalogPromise ??= screenerApiAdvanced.fields().catch((e) => { catalogPromise = null; throw e; });
  return catalogPromise;
}

export function FilterEditor({ value, onChange }: { value: unknown; onChange: (v: Group) => void }) {
  const [cat, setCat] = useState<FieldsCatalog | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    loadCatalog().then((c) => { if (live) setCat(c); }).catch((e: Error) => { if (live) setErr(e.message); });
    return () => { live = false; };
  }, []);
  const g: Group = (value && typeof value === "object" ? value : {}) as Group;
  const conds = g.conditions ?? [];
  const put = (next: Partial<Group>) => onChange({ logic: g.logic ?? "AND", conditions: conds, groups: g.groups ?? [], ...next });
  const setRow = (i: number, row: Cond) => put({ conditions: conds.map((c, j) => (j === i ? row : c)) });
  const firstField = cat?.categories[0]?.fields[0]?.id ?? "per";

  return (
    <div className="pg-filter">
      {err && <p className="pg-field-err">필드 목록을 불러오지 못했어요 — {err}</p>}
      {conds.length > 1 && (
        <div className="pg-chips pg-filter-logic" role="group" aria-label="조건 묶는 방식">
          {[["AND", "모두 만족"], ["OR", "하나라도"]].map(([k, label]) => (
            <button key={k} type="button" className={`pg-chip${(g.logic ?? "AND") === k ? " on" : ""}`}
                    aria-pressed={(g.logic ?? "AND") === k} onClick={() => put({ logic: k })}>{label}</button>
          ))}
        </div>
      )}
      {conds.map((c, i) => (
        <div key={i} className="pg-filter-row">
          <select className="pg-field-input" aria-label={`${i + 1}번째 조건 필드`} value={c.field}
                  onChange={(e) => setRow(i, { ...c, field: e.target.value })}>
            {!cat && <option value={c.field}>{c.field}</option>}
            {cat?.categories.map((cg) => (
              <optgroup key={cg.id} label={cg.label}>
                {cg.fields.map((f) => <option key={f.id} value={f.id}>{f.label}{f.unit ? ` (${f.unit})` : ""}</option>)}
              </optgroup>
            ))}
          </select>
          <select className="pg-field-input pg-filter-op" aria-label={`${i + 1}번째 조건 비교`} value={c.op}
                  onChange={(e) => setRow(i, { ...c, op: e.target.value })}>
            {(cat?.operators ?? [{ id: c.op, label: c.op, name: c.op }]).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
          </select>
          <input className="pg-field-input pg-filter-v" type="number" step="any" aria-label={`${i + 1}번째 조건 값`}
                 value={c.value ?? ""} onChange={(e) => setRow(i, { ...c, value: e.target.value === "" ? null : Number(e.target.value) })} />
          {c.op === "between" && (
            <input className="pg-field-input pg-filter-v" type="number" step="any" aria-label={`${i + 1}번째 조건 끝값`}
                   value={c.value2 ?? ""} onChange={(e) => setRow(i, { ...c, value2: e.target.value === "" ? null : Number(e.target.value) })} />
          )}
          <button type="button" className="pg-icon-btn" aria-label={`${i + 1}번째 조건 지우기`}
                  onClick={() => put({ conditions: conds.filter((_, j) => j !== i) })}><X size={14} /></button>
        </div>
      ))}
      {(g.groups?.length ?? 0) > 0 && <p className="pg-help">묶음 조건 {g.groups!.length}개는 그대로 두었어요 — 전문가 설정에서 볼 수 있어요.</p>}
      <button type="button" className="pg-add" onClick={() => put({ conditions: [...conds, { field: firstField, op: "gt", value: null }] })}>
        <Plus size={14} /> 조건 추가
      </button>
    </div>
  );
}
