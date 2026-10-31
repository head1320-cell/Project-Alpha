"use client";
/**
 * 제약 편집기 (CF 3부 P2) — 엔진이 받는 열 가지(`ConstraintsInput`)를 질문 카드로
 * ==========================================================================
 * ★값의 모양은 그대로★ — 문서에 쓰는 것은 지금까지와 같은 `constraints` dict(옛 문서가 그대로 열린다).
 * ★범위는 서버 스키마에서★(`rangeOf`) · ★판정은 서버에서★ — 고칠 때마다 `/allocation/constraints/check` 가 엔진의 같은
 * 사전 검사(`_precheck`)로 "풀 수 없어요" 를 계산 전에 말하고, 업종 표가 없으면 업종 상한이 빠진다고 말한다.
 * 기본 칩(한 종목 최대)은 다른 제약을 지우지 않는다. 공매도(음수 하한)는 연구용이라고 말한다.
 */
import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import {
  NUMBER_CARDS, SHAPES, allowsShort, applyShape, asConstraints, capsOf, constraintsSummary, maxPresetActive, mergeMaxPreset,
  portfolioGraphApi, rangeOf, setCap, setConstraint, shapeOf, type ConstraintsCheck, type FieldSpec, type JsonSchema,
} from "@/entities/portfolio-graph";

type Check = { state: "idle" | "wait" } | { state: "done"; data: ConstraintsCheck } | { state: "error"; message: string };

/** 고칠 때마다(잠깐 멈춘 뒤) 서버 확인 — 마지막 요청의 답만 쓴다. */
function useCheck(value: unknown, names: string[], model: string | undefined): Check {
  const [check, setCheck] = useState<Check>({ state: "idle" });
  const key = JSON.stringify([value ?? {}, names, model ?? null]);
  useEffect(() => {
    let live = true;
    setCheck((c) => (c.state === "idle" ? { state: "wait" } : c));
    const t = setTimeout(() => {
      portfolioGraphApi.constraintsCheck(value ?? {}, names, model)
        .then((data) => { if (live) setCheck({ state: "done", data }); })
        .catch((e: Error) => { if (live) setCheck({ state: "error", message: e.message }); });
    }, 300);
    return () => { live = false; clearTimeout(t); };
    // key 가 값·종목·방식을 모두 담는다 — 객체 참조가 바뀌어도 내용이 같으면 다시 묻지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return check;
}

function NumberCard({ k, label, unit, help, value, root, onChange }: {
  k: string; label: string; unit: string; help?: string; value: unknown; root: JsonSchema | null;
  onChange: (v: number | undefined) => void;
}) {
  const r = rangeOf(root, k);
  const [text, setText] = useState(value === undefined || value === null ? "" : String(value));
  useEffect(() => { setText(value === undefined || value === null ? "" : String(value)); }, [value]);
  return (
    <div className="pg-cons-card" data-key={k}>
      <label className="pg-cons-card-row">
        <span className="pg-cons-card-q">{label}</span>
        <span className="pg-cons-card-in">
          <input className="pg-field-input" type="number" inputMode="decimal" step="any" min={r?.min} max={r?.max}
                 aria-label={label} value={text}
                 onChange={(e) => {
                   setText(e.target.value);
                   if (e.target.value === "") return onChange(undefined);
                   const n = Number(e.target.value);
                   if (Number.isFinite(n)) onChange(n);
                 }} />
          <span className="pg-cons-unit">{unit}</span>
        </span>
      </label>
      {help && <p className="pg-help">{help}</p>}
    </div>
  );
}

function SectorCard({ value, check, hasNames, onChange }: {
  value: unknown; check: Check; hasNames: boolean; onChange: (v: unknown) => void;
}) {
  const caps = capsOf(value);
  const [pending, setPending] = useState<string[]>([]);
  const data = check.state === "done" ? check.data : null;
  const rows = [...Object.keys(caps), ...pending.filter((g) => !(g in caps))];
  const free = (data?.group_names ?? []).filter((g) => !rows.includes(g));
  const unknown = (data?.unapplied ?? []).find((u) => u.kind === "unknown_sector");
  return (
    <div className="pg-cons-card pg-cons-card--sectors" data-key="group_caps_pct">
      <span className="pg-cons-card-q">업종마다 최대 얼마까지 둘까요?</span>
      {!hasNames ? <p className="pg-help pg-cons-sectors-wait">종목을 먼저 정하면 업종을 고를 수 있어요.</p>
        : !data ? <p className="pg-help pg-cons-sectors-wait">이 종목들의 업종을 확인하는 중…</p>
        : !data.sectors_readable ? (
          <p className="pg-cons-sectors-none" role="note">이 종목들의 업종을 읽지 못했어요 — 업종 상한을 걸어도 적용되지 않아요.</p>
        ) : free.length > 0 && (
          <div className="pg-chips">
            {free.map((g) => (
              <button key={g} type="button" className="pg-chip pg-cons-sector-chip" onClick={() => setPending((p) => [...p, g])}>{g}</button>
            ))}
          </div>
        )}
      {rows.map((g) => (
        <div key={g} className="pg-cons-cap" data-group={g}>
          <span className="pg-cons-cap-name">{g}</span>
          <input className="pg-field-input" type="number" inputMode="decimal" step="any" min={0} max={100} aria-label={`${g} 최대`}
                 defaultValue={caps[g] ?? ""}
                 onChange={(e) => {
                   const n = Number(e.target.value);
                   if (e.target.value !== "" && Number.isFinite(n)) onChange(setCap(value, g, n));
                 }} />
          <span className="pg-cons-unit">%</span>
          <button type="button" className="pg-cons-cap-x" aria-label={`${g} 상한 지우기`}
                  onClick={() => { setPending((p) => p.filter((x) => x !== g)); onChange(setCap(value, g, undefined)); }}>
            <X size={14} />
          </button>
        </div>
      ))}
      {unknown && rows.length > 0 && <p className="pg-help">{unknown.text}</p>}
    </div>
  );
}

export function ConstraintsEditor({ f, value, root, names, model, onChange }: {
  f: FieldSpec; value: unknown; root: JsonSchema | null;
  /** 이 노드 위쪽 '종목 고르기' 의 종목 — 몇 종목인지·업종이 무엇인지 확인에 쓴다. */
  names: string[];
  /** 지금 계산 방식 — 공분산만 쓰는 방식은 공매도를 풀지 못한다(서버가 판정). */
  model?: string;
  onChange: (v: unknown) => void;
}) {
  const cur = asConstraints(value);
  const check = useCheck(value, names, model);
  const shape = shapeOf(cur);
  const summary = constraintsSummary(cur);
  const assumed = SHAPES.find((s) => s.id === shape)?.assumed;
  const [open, setOpen] = useState(() => Object.keys(cur).some((k) => k !== "max_weight_pct"));
  const data = check.state === "done" ? check.data : null;
  const capWarn = useMemo(() => (data?.unapplied ?? []).filter((u) => u.kind === "group_cap"), [data]);
  return (
    <div className="pg-basic-field pg-cons-field" data-field={f.name}>
      <div className="pg-q">{f.ui.question ?? f.ui.label}</div>
      {f.ui.presets && (
        <div className="pg-chips">
          {f.ui.presets.map((p) => {
            const on = maxPresetActive(cur, p.value);
            return (
              <button key={p.label} type="button" className={`pg-chip pg-cons-max${on ? " on" : ""}`} aria-pressed={on}
                      onClick={() => onChange(mergeMaxPreset(cur, p.value))}>{p.label}</button>
            );
          })}
        </div>
      )}
      {check.state === "error" && <p className="pg-cons-check pg-cons-check--bad" role="alert">확인하지 못했어요 — {check.message}</p>}
      {data?.checked && data.ok === false && (
        <p className="pg-cons-check pg-cons-check--bad" role="alert">이 조합은 풀 수 없어요 — {data.reason}</p>
      )}
      {capWarn.map((u, i) => <p key={i} className="pg-cons-check pg-cons-check--warn">{u.text}</p>)}
      {allowsShort(cur) && (
        <p className="pg-cons-short" role="note">{data?.short_note ?? "공매도가 들어간 비중이에요 — 확인하는 중…"}</p>
      )}
      <details className="pg-cons-more" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary>더 정하기{summary && <span className="pg-cons-more-sum"> · {summary}</span>}</summary>
        <div className="pg-cons-shapes" role="group" aria-label="모양">
          {SHAPES.map((s) => (
            <button key={s.id} type="button" className={`pg-chip pg-cons-shape${shape === s.id ? " on" : ""}`} aria-pressed={shape === s.id}
                    onClick={() => onChange(applyShape(cur, s.id))}>{s.label}</button>
          ))}
        </div>
        {assumed && <p className="pg-cons-assumed"><span className="pg-tag pg-tag--assumed">가정</span> {assumed}</p>}
        <NumberCard k="min_weight_pct" {...NUMBER_CARDS[0]} value={cur.min_weight_pct} root={root}
                    onChange={(v) => onChange(setConstraint(cur, "min_weight_pct", v))} />
        <SectorCard value={cur} check={check} hasNames={names.length > 0} onChange={onChange} />
        {NUMBER_CARDS.slice(1).map((c) => (
          <NumberCard key={c.key} k={c.key} label={c.label} unit={c.unit} help={c.help} value={cur[c.key]} root={root}
                      onChange={(v) => onChange(setConstraint(cur, c.key, v))} />
        ))}
      </details>
      {f.ui.help && <p className="pg-help">{f.ui.help}</p>}
    </div>
  );
}
