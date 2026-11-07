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
 * - (CF3b2) 맨 위 관계 문장(서버) · 건너간 것(잰 값만) · 빠지거나 바뀐 것(전달 점검) — ★`[]` 은 "점검했고 찾지 못함", `null` 은 사유★.
 */
import type { Edge } from "@xyflow/react";
import { insertCandidates, josa, type EdgeRecord, type EdgeRelation, type GraphError, type IssueLevel, type NodeCatalogEntry, type NodeRunResult,
         type PgNode } from "@/entities/portfolio-graph";
import { descendantsOf } from "./store";

const LINEAGE_TEXT = {
  practice: "연습용(합성) 값이 흘러요",
  forward: "지금 시점 전용이에요 — 과거 검증에 쓸 수 없어요",
  overlay: "오늘 판단한 노출 조절이 얹힌 비중이에요",
};
const LEVEL_TEXT: Record<IssueLevel, string> = { lost: "빠짐", changed: "바뀜", structural: "구조", unused: "쓰지 않음" };

export function WirePanel({ edge, nodes, edges, catalog, results, stale, errors, plain, order, onFocus, onCut, onInsert,
                            relation, record, recordGap }: {
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
  /** 서버 관계 문장 — 계산한 뒤면 그 계산의, 아니면 검증의 것(요약 괄호 없음). */
  relation?: EdgeRelation | null;
  /** 이 선의 전달 점검 — 지금 그래프의 결과일 때만. */
  record?: EdgeRecord | null;
  /** 계산은 했는데 이 선의 기록이 없을 때 그 까닭(받는 쪽이 예전 결과 · 보내는 쪽이 계산되지 않음). */
  recordGap?: string | null;
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
  const inserts = insertCandidates(out?.type, catalog);

  return (
    <section className="pg-wire-sheet" aria-label="선">
      {relation && (
        <div className="pg-wire-row" data-row="relation">
          <p className="pg-wire-relation">{relation.text}</p>
        </div>
      )}
      {record && (
        <div className="pg-wire-row" data-row="facts">
          <h3>건너간 것</h3>
          {record.facts ? (
            <table className="pg-wire-facts"><tbody>
              {record.facts.map((f) => <tr key={f.key} data-key={f.key}><th scope="row">{f.label}</th><td>{f.text}</td></tr>)}
            </tbody></table>
          ) : <p className="pg-wire-muted">{record.facts_reason ?? "건너간 값을 재지 못했어요."}</p>}
        </div>
      )}
      {(record || recordGap) && (
        <div className="pg-wire-row" data-row="issues">
          <h3>빠지거나 바뀐 것</h3>
          {!record ? <p className="pg-wire-muted">{recordGap}</p>
            : record.issues === null ? <p className="pg-wire-muted">{record.issues_reason ?? "이 선은 점검하지 않았어요."}</p>
            : record.issues.length ? (
              <ul className="pg-wire-issues">
                {record.issues.map((i) => (
                  <li key={i.code} className="pg-wire-issue" data-level={i.level} data-code={i.code}>
                    <span className="pg-wire-issue-lv">{LEVEL_TEXT[i.level]}</span>
                    <span>{i.text}{i.fix && <span className="pg-wire-issue-fix"> {i.fix}</span>}</span>
                  </li>
                ))}
              </ul>
            ) : <p>점검한 것: {record.checks.join(" · ")} — 잃거나 바뀐 것을 찾지 못했어요.</p>}
        </div>
      )}
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
            {inserts.map((c) => (
              <li key={c.kind}>
                <button type="button" className="pg-wire-insert" data-kind={c.kind} onClick={() => onInsert(c.kind, c.inPort, c.outPort)}>
                  <b>{c.label}</b><span>{c.sub}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
