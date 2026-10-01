"use client";
/**
 * 선 탭 (BT4) — ★링크는 관계다★ 선을 누르면 무엇이 · 어디서 어디로 · 무엇에 쓰이려고 흐르는지, 믿을 수 있는지,
 * 끊으면 무엇이 멈추는지를 **서버 값만으로** 말한다.
 * ==========================================================================
 * - 무엇이 흐르나요 — 포트 타입 쉬운 이름 + 서버 선 요약(`briefs`, 계산한 뒤에만). 값을 지어내지 않는다(BM 기각: 선 위 값 미리보기).
 * - 무엇에 쓰이나요 — 받는 포트의 `role`(BT1). 서버가 확인하지 못한 포트는 이 줄이 없다.
 * - 믿을 수 있나요 — 보내는 노드의 계보(연습용 · 지금 시점 전용 · 노출 조절). ★"실데이터"라고 부르지 않는다★(BM :44).
 * - 끊으면 — 받는 입력이 필수면 받는 노드부터 하류가 멈춘다. 선택 입력이면 그렇다고 말한다.
 * - 사이에 넣기 — 같은 타입을 받아 같은 타입을 내는 노드만. 끊기·넣기는 되돌리기 한 번.
 */
import type { Edge } from "reactflow";
import type { GraphError, NodeCatalogEntry, NodeRunResult, PgNode } from "@/entities/portfolio-graph";
import { descendantsOf } from "./store";

/** 받침에 맞는 조사 — `pair` 는 [받침 있을 때, 없을 때]. */
function josa(word: string, pair: [string, string]): string {
  const ch = [...word].reverse().find((c) => c >= "가" && c <= "힣");
  return word + (ch && (ch.charCodeAt(0) - 0xac00) % 28 ? pair[0] : pair[1]);
}

const LINEAGE_TEXT = {
  practice: "연습용(합성) 값이 흘러요",
  forward: "지금 시점 전용이에요 — 과거 검증에 쓸 수 없어요",
  overlay: "오늘 판단한 노출 조절이 얹힌 비중이에요",
};

export function WirePanel({ edge, nodes, edges, catalog, results, stale, errors, plain, order, onFocus, onCut, onInsert }: {
  edge: Edge;
  nodes: PgNode[];
  edges: Edge[];
  catalog: NodeCatalogEntry[];
  results: Record<string, NodeRunResult> | null;
  stale: boolean;
  errors: GraphError[];
  plain: Record<string, string>;
  order: string[];
  onFocus: (id: string) => void;
  onCut: () => void;
  onInsert: (kind: string, inPort: string, outPort: string) => void;
}) {
  const entryOf = (id: string) => catalog.find((c) => c.type === nodes.find((n) => n.id === id)?.data.kind);
  const src = entryOf(edge.source);
  const dst = entryOf(edge.target);
  const out = src?.outputs.find((p) => p.name === edge.sourceHandle);
  const inp = dst?.inputs.find((p) => p.name === edge.targetHandle);
  const label = (id: string) => `${order.indexOf(id) + 1}. ${entryOf(id)?.plain_label ?? id}`;
  const typeName = out ? plain[out.type] ?? out.type : "모르는 값";
  const live = results && !stale ? results[edge.source] : undefined;
  const brief = live?.status === "ok" && edge.sourceHandle ? live.briefs?.[edge.sourceHandle] ?? null : null;
  const lin = live?.status === "ok" ? live.lineage : undefined;
  const chips = [lin?.practice && "practice", lin?.pit === "forward_only" && "forward", lin?.overlay && "overlay"]
    .filter(Boolean) as (keyof typeof LINEAGE_TEXT)[];
  const required = inp?.required !== false;
  const stops = required ? [edge.target, ...descendantsOf([edge.target], edges)] : [];
  const problem = errors.find((e) => e.edge_id === edge.id && e.code === "needs_unmet");
  const inserts = out ? catalog.filter((c) => c.inputs.some((i) => i.type === out.type) && c.outputs.some((o) => o.type === out.type)) : [];

  return (
    <section className="pg-wire-sheet" aria-label="선">
      <div className="pg-wire-row" data-row="what">
        <h3>무엇이 흐르나요</h3>
        <p><b className="pg-wire-type-name">{typeName}</b>{brief ? <> · <span className="pg-wire-brief-text">{brief}</span></>
          : <span className="pg-wire-muted"> — {live ? "요약할 수 없는 값이에요" : "계산하면 무엇이 흘렀는지 보여 드려요"}</span>}</p>
      </div>
      <div className="pg-wire-row" data-row="route">
        <h3>어디서 어디로</h3>
        <p>
          <button type="button" className="pg-wire-node" onClick={() => onFocus(edge.source)}>{label(edge.source)}</button>
          <span aria-hidden="true"> → </span><span className="pg-sr">에서 </span>
          <button type="button" className="pg-wire-node" onClick={() => onFocus(edge.target)}>{label(edge.target)}</button>
          <span className="pg-wire-muted">의 ‘{inp ? plain[inp.type] ?? inp.name : edge.targetHandle}’ 자리</span>
        </p>
      </div>
      {inp?.role && (
        <div className="pg-wire-row" data-row="role">
          <h3>무엇에 쓰이나요</h3>
          <p>{inp.role}</p>
        </div>
      )}
      <div className="pg-wire-row" data-row="trust">
        <h3>믿을 수 있나요</h3>
        {!live ? <p className="pg-wire-muted">계산하면 이 값의 출처를 보여 드려요.</p>
          : live.status !== "ok" ? <p className="pg-wire-muted">보내는 노드가 계산되지 않아 값이 흐르지 않았어요.</p>
          : chips.length ? (
            <ul className="pg-wire-chips">{chips.map((k) => <li key={k} className={`pg-wire-chip pg-wire-chip--${k}`}>{LINEAGE_TEXT[k]}</li>)}</ul>
          ) : <p>연습용 합성이 아니에요 — 데이터 등급은 ‘{src?.plain_label}’ 노드에서 확인해요.</p>}
        {problem && <p className="pg-wire-warn" role="note">{problem.message}{problem.fix ? ` ${problem.fix}` : ""}</p>}
      </div>
      <div className="pg-wire-row" data-row="cut">
        <h3>끊으면</h3>
        <p>{required ? `‘${dst?.plain_label}’부터 ${stops.length}개 노드가 계산되지 않아요.`
          : `이 입력은 없어도 돼요 — ${josa(`‘${dst?.plain_label ?? ""}’`, ["은", "는"])} 이 값 없이 계산해요.`}</p>
        {stops.length > 1 && <p className="pg-wire-muted pg-wire-stops">{stops.map(label).join(", ")}</p>}
      </div>
      <div className="pg-wire-actions">
        <button type="button" className="pg-btn pg-wire-cut" onClick={onCut}>선 끊기</button>
      </div>
      {inserts.length > 0 && (
        <div className="pg-wire-row" data-row="insert">
          <h3>사이에 넣기</h3>
          <p className="pg-wire-muted">{josa(typeName, ["을", "를"])} 받아 {josa(typeName, ["을", "를"])} 내는 노드만 보여요.</p>
          <ul className="pg-wire-inserts">
            {inserts.map((c) => {
              const i = c.inputs.find((x) => x.type === out!.type)!;
              const o = c.outputs.find((x) => x.type === out!.type)!;
              return (
                <li key={c.type}>
                  <button type="button" className="pg-wire-insert" data-kind={c.type} onClick={() => onInsert(c.type, i.name, o.name)}>
                    <b>{c.plain_label}</b><span>{c.plain_description}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
