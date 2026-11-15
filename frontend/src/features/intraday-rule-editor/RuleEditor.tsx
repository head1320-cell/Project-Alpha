"use client";
/**
 * 분봉 규칙 '직접 구성' 편집기 — 조건 줄로 조건 나무를 그대로 고친다 (자유 조건식 설계 §6.2)
 * ==========================================================================
 * 자리는 셋이다: 진입 조건(판단) · 미리 건 매수 가격(수) · 청산 조건(판단). 진입 조건과 미리 건 매수 가격 가운데 하나는 있어야 한다.
 * ★도구는 조건을 추천하지 않는다★ — 지표 · 연산 · 값은 사용자가 고른다. 지표와 연산의 이름 · 범위 · 출발값은 서버의 문법 표가 준 것이고,
 * 상수 · 연산 · 봉 수 · 시각은 비어서 시작한다. 빈 칸은 그 칸에 표시한다(`aria-invalid`) — 몇 곳인지는 `issuesOf` 가 말한다.
 * 한 줄 = `[수] [연산] [수]`. 줄 앞의 '아님' · '직전 M봉 동안'은 그 줄(또는 묶음)을 감싼다. 감싼 순서가 뜻이다(바깥이 앞에 온다).
 * 화면(백테스트 › 분봉 규칙)과 캔버스의 분봉 설정 노드가 이 부품을 함께 쓴다.
 */
import { useState } from "react";
import type { Grammar, OpNode, Tree } from "@/entities/intraday";
import {
  ARITH, COMPARES, GROUPS, WRAPS, append, arithmetic, compare, conditional, constant, group, heldBefore, indicator, isConst, isInd, isOp,
  negate, removeAt, setAt, timeWindow, type Draft, type Drafts, type Path,
} from "./tree";

/** 자리 하나의 편집 맥락 — 뿌리와 그것을 바꾸는 길. */
type Ctx = { g: Grammar; root: Draft; put: (next: Draft) => void };

const opLabel = (g: Grammar, name: string): string => g.ops.find((o) => o.name === name)?.label ?? name;
const opSymbol = (g: Grammar, name: string): string => g.ops.find((o) => o.name === name)?.symbol ?? opLabel(g, name);
/** '직전 M봉 동안'의 봉 수 범위 — 서버의 문법 표가 준 것이다(없으면 범위를 지어내지 않는다 — 판정은 서버가 한다). */
const barsOf = (g: Grammar) => g.ops.find((o) => o.name === "held_before")?.extra.find((e) => e.key === "bars");
const parse = (raw: string): number | null => (/^-?\d+(\.\d+)?$/.test(raw.trim()) ? Number(raw.trim()) : null);
const toClock = (hhmm: string | undefined): string => (hhmm && /^\d{4}$/.test(hhmm) ? `${hhmm.slice(0, 2)}:${hhmm.slice(2)}` : "");
const fromClock = (clock: string): string => clock.replace(":", "");

/** 수를 적는 칸 — 치는 동안에만 글자를 따로 들고, 칸을 떠나면 나무의 값으로 돌아간다(줄을 지워 자리가 바뀌어도 낡은 글자가 남지 않는다). */
function NumInput({ label, value, onChange, integer, min, max }: {
  label: string; value: number | null; onChange: (v: number | null) => void; integer?: boolean; min?: number; max?: number;
}) {
  const [typing, setTyping] = useState<string | null>(null);
  const shown = typing ?? (value === null ? "" : String(value));
  const bad = value === null || (integer === true && !Number.isInteger(value)) || (min !== undefined && value < min) || (max !== undefined && value > max);
  return (
    <input className="ire-input" inputMode={integer ? "numeric" : "decimal"} autoComplete="off" aria-label={label} aria-invalid={bad}
           value={shown} onFocus={() => setTyping(shown)} onBlur={() => setTyping(null)}
           onChange={(e) => { setTyping(e.target.value); onChange(parse(e.target.value)); }} />
  );
}

/** 무엇을 놓을지 고르는 단추 셋 — 비교 한 줄 · 시각 창 · 묶음. */
function AddRow({ onAdd, label }: { onAdd: (node: Tree) => void; label: string }) {
  return (
    <span className="ire-add-row" role="group" aria-label={`${label}에 추가`}>
      <button type="button" className="ire-add" data-add="compare" onClick={() => onAdd(compare())}>조건 추가</button>
      <button type="button" className="ire-add" data-add="time" onClick={() => onAdd(timeWindow())}>시각 창 추가</button>
      <button type="button" className="ire-add" data-add="group" onClick={() => onAdd(group())}>묶음 추가</button>
    </span>
  );
}

/** 수 하나 — 지표 · 상수 · 계산 · 조건부 값. `optional` 이면 비워 둘 수 있는 자리다(쓰지 않는 자리 — 빈 칸으로 표시하지 않는다). */
function Num({ node, path, ctx, label, optional }: { node: Draft; path: Path; ctx: Ctx; label: string; optional?: boolean }) {
  const { g } = ctx;
  const set = (next: Draft) => ctx.put(setAt(ctx.root, path, next));
  const kind = node === null ? "" : isInd(node) ? `ind:${node.ind}` : isConst(node) ? "const" : node.op;
  const pick = (v: string) => {
    if (v === "") return set(null);
    if (v.startsWith("ind:")) return set(indicator(g, v.slice(4)));
    if (v === "const") return set(constant());
    if (v === "where") return set(node && isOp(node) && node.op === "where" ? node : conditional(node));
    return set(node && isOp(node) && ARITH.includes(node.op) ? { ...node, op: v } : arithmetic(v, node));
  };
  const spec = node && isInd(node) ? g.indicators.find((i) => i.name === node.ind) : undefined;
  return (
    <span className="ire-num" data-kind={kind || "empty"}>
      <select className="ire-select ire-num-kind" aria-label={label} aria-invalid={node === null && !optional} value={kind} onChange={(e) => pick(e.target.value)}>
        <option value="">값 선택</option>
        <optgroup label="지표">
          {g.indicators.map((i) => <option key={i.name} value={`ind:${i.name}`}>{i.label}</option>)}
        </optgroup>
        <optgroup label="값과 계산">
          <option value="const">상수</option>
          {ARITH.map((name) => <option key={name} value={name}>{opLabel(g, name)}</option>)}
          <option value="where">{opLabel(g, "where")}</option>
        </optgroup>
      </select>
      {node && isInd(node) && spec ? spec.params.map((p) => {
        const raw = node[p.key];
        return (
          <span key={p.key} className="ire-param" data-param={p.key}>
            <NumInput label={`${spec.label} ${p.label}`} integer={p.type === "int"} min={p.min} max={p.max}
                      value={typeof raw === "number" ? raw : null} onChange={(v) => set({ ...node, [p.key]: v })} />
            <span className="ire-unit">{p.unit}</span>
          </span>
        );
      }) : null}
      {node && isConst(node) ? <NumInput label={`${label} 상수`} value={node.const} onChange={(v) => set({ const: v })} /> : null}
      {node && isOp(node) && ARITH.includes(node.op) ? (
        <span className="ire-calc">
          <span className="ire-paren" aria-hidden="true">(</span>
          <Num node={node.args[0] ?? null} path={[...path, 0]} ctx={ctx} label={`${label} 계산의 왼쪽 값`} />
          <span className="ire-sym">{opSymbol(g, node.op)}</span>
          <Num node={node.args[1] ?? null} path={[...path, 1]} ctx={ctx} label={`${label} 계산의 오른쪽 값`} />
          <span className="ire-paren" aria-hidden="true">)</span>
        </span>
      ) : null}
      {node && isOp(node) && node.op === "where" ? (
        <span className="ire-calc ire-where">
          <Cond node={node.args[0] ?? null} path={[...path, 0]} ctx={ctx} label={`${label} 조건부 값의 조건`} />
          <span className="ire-sym">충족 시</span>
          <Num node={node.args[1] ?? null} path={[...path, 1]} ctx={ctx} label={`${label} 조건부 값`} />
        </span>
      ) : null}
    </span>
  );
}

/** 판단 하나 — 감싼 것(아님 · 직전 M봉 동안)을 바깥부터 줄 앞에 놓고, 그 안의 비교 · 시각 창 · 묶음을 그린다. */
function Cond({ node, path, ctx, label }: { node: Draft; path: Path; ctx: Ctx; label: string }) {
  const { g } = ctx;
  const put = (p: Path, next: Draft) => ctx.put(setAt(ctx.root, p, next));
  if (node === null) {
    return <span className="ire-cond ire-cond--empty" data-op="empty"><AddRow label={label} onAdd={(n) => put(path, n)} /></span>;
  }
  const wraps: { node: OpNode; path: Path }[] = [];
  let core: Draft = node;
  let corePath = path;
  while (core && isOp(core) && WRAPS.includes(core.op)) {
    wraps.push({ node: core, path: corePath });
    corePath = [...corePath, 0];
    core = core.args[0] ?? null;
  }
  const isGroup = core !== null && isOp(core) && GROUPS.includes(core.op);
  const here = core;
  return (
    <div className="ire-cond" data-op={core && isOp(core) ? core.op || "pending" : "empty"}>
      <div className="ire-line">
        {wraps.map((w) => (w.node.op === "not" ? (
          <span key={w.path.join(".") || "root"} className="ire-wrap" data-wrap="not">
            <span>{opLabel(g, "not")}</span>
            <button type="button" className="ire-x" aria-label={`${label}: 아님 해제`} onClick={() => put(w.path, w.node.args[0] ?? null)}>×</button>
          </span>
        ) : (
          <span key={w.path.join(".") || "root"} className="ire-wrap" data-wrap="held_before">
            <span>직전</span>
            <NumInput label={`${label}: 직전 봉 수`} integer min={barsOf(g)?.min} max={barsOf(g)?.max} value={w.node.bars ?? null} onChange={(v) => put(w.path, { ...w.node, bars: v })} />
            <span>봉 동안 계속</span>
            <button type="button" className="ire-x" aria-label={`${label}: 직전 봉 동안 해제`} onClick={() => put(w.path, w.node.args[0] ?? null)}>×</button>
          </span>
        )))}
        {here === null ? <AddRow label={label} onAdd={(n) => put(corePath, n)} /> : null}
        {here !== null && isOp(here) && isGroup ? (
          <select className="ire-select ire-group-op" aria-label={`${label}: 묶음의 조건`} value={here.op} onChange={(e) => put(corePath, { ...here, op: e.target.value })}>
            {GROUPS.map((name) => <option key={name} value={name}>{opLabel(g, name)}</option>)}
          </select>
        ) : null}
        {here !== null && isOp(here) && here.op === "time_between" ? (
          <span className="ire-time">
            <span>시각</span>
            <input type="time" className="ire-input ire-clock" aria-label={`${label}: 시작 시각`} aria-invalid={!here.from || (!!here.to && here.from > here.to)}
                   value={toClock(here.from)} onChange={(e) => put(corePath, { ...here, from: fromClock(e.target.value) })} />
            <span aria-hidden="true">~</span>
            <input type="time" className="ire-input ire-clock" aria-label={`${label}: 종료 시각`} aria-invalid={!here.to || (!!here.from && here.from > here.to)}
                   value={toClock(here.to)} onChange={(e) => put(corePath, { ...here, to: fromClock(e.target.value) })} />
          </span>
        ) : null}
        {here !== null && isOp(here) && !isGroup && here.op !== "time_between" ? (
          <>
            <Num node={here.args[0] ?? null} path={[...corePath, 0]} ctx={ctx} label={`${label}: 왼쪽 값`} />
            <select className="ire-select ire-op" aria-label={`${label}: 연산`} aria-invalid={here.op === ""} value={here.op}
                    onChange={(e) => put(corePath, { ...here, op: e.target.value })}>
              <option value="">연산 선택</option>
              {COMPARES.map((name) => <option key={name} value={name}>{opLabel(g, name)}</option>)}
            </select>
            <Num node={here.args[1] ?? null} path={[...corePath, 1]} ctx={ctx} label={`${label}: 오른쪽 값`} />
          </>
        ) : null}
        <span className="ire-tools">
          <button type="button" className="ire-tool" data-act="not" aria-label={`${label}: 아님으로 감싸기`} onClick={() => put(path, negate(node))}>{opLabel(g, "not")}</button>
          <button type="button" className="ire-tool" data-act="held" aria-label={`${label}: 직전 M봉 동안으로 감싸기`} onClick={() => put(path, heldBefore(node))}>직전 M봉 동안</button>
          <button type="button" className="ire-tool ire-tool--del" data-act="remove" aria-label={`${label}: 삭제`} onClick={() => ctx.put(removeAt(ctx.root, path))}>삭제</button>
        </span>
      </div>
      {here !== null && isOp(here) && isGroup ? (
        <div className="ire-group">
          <ul className="ire-group-list">
            {here.args.map((child, i) => (
              // 줄에는 고유한 이름이 없다 — 자리(순번)가 곧 이름이다. 칸의 글자는 나무에서 다시 읽으므로 줄이 빠져도 어긋나지 않는다.
              <li key={i}><Cond node={child} path={[...corePath, i]} ctx={ctx} label={`${label} ${i + 1}번째 줄`} /></li>
            ))}
          </ul>
          <AddRow label={`${label} 묶음`} onAdd={(n) => put(corePath, { ...here, args: [...here.args, n] })} />
        </div>
      ) : null}
    </div>
  );
}

export function RuleEditor({ grammar, value, onChange }: { grammar: Grammar; value: Drafts; onChange: (next: Drafts) => void }) {
  return (
    <div className="ire">
      {grammar.slots.map((slot) => {
        const root = value[slot.key];
        const put = (next: Draft) => onChange({ ...value, [slot.key]: next });
        const ctx: Ctx = { g: grammar, root, put };
        const rootIsGroup = root !== null && isOp(root) && GROUPS.includes(root.op);
        return (
          <section key={slot.key} className="ire-slot" data-slot={slot.key} data-used={root !== null} aria-label={slot.label}>
            <h3 className="ire-slot-title">{slot.label}</h3>
            {slot.kind === "bool" ? (
              <>
                {root === null ? <p className="ire-empty">조건 없음</p> : <Cond node={root} path={[]} ctx={ctx} label={slot.label} />}
                {/* 뿌리가 묶음이면 묶음의 단추가 줄을 잇는다. 그 밖에는 여기서 더한다 — 조건 하나에 더하면 '모두 충족'으로 묶인다. */}
                {rootIsGroup ? null : <AddRow label={slot.label} onAdd={(n) => put(append(root, n))} />}
              </>
            ) : (
              <div className="ire-line">
                <Num node={root} path={[]} ctx={ctx} label={slot.label} optional />
                {root === null ? <span className="ire-empty">사용 안 함</span>
                  : <button type="button" className="ire-tool ire-tool--del" data-act="remove" aria-label={`${slot.label}: 삭제`} onClick={() => put(null)}>삭제</button>}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
