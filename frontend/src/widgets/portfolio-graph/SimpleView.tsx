"use client";
/**
 * 간단히 보기 (BM C4 · Figma Weave 의 App Mode · 토스식) — 노드 없이 "정할 것 → 결과" 한 줄 흐름
 * ==========================================================================
 * 전략마다(없으면 흐름 하나) ① 정할 것: 각 노드의 **기본 층 질문**(설정 탭과 같은 위젯) ② 결과: 서버 explain 제목 · 헤드라인 · 작은 그림 ·
 * 믿어도 되나요(trust) · 재지 않은 것. ★여기서 바꾸면 노드 설정이 바뀐다★(같은 스토어) — 캔버스로 돌아가도 그대로다.
 * 막힘·실패는 서버 사유 그대로 + "캔버스에서 원인 보기". 이야기 탭을 대신하지 않는다(그건 노드 번호 순서의 전체 설명).
 */
import type { Edge } from "reactflow";
import { Loader2, Route } from "lucide-react";
import {
  fieldsOf,
  portfolioLane,
  topoOrder,
  type GraphGroup,
  type NodeCatalogEntry,
  type NodeRunResult,
  type PgNode,
  type TrustState,
} from "@/entities/portfolio-graph";
import { Glance } from "./Glance";
import { BasicFields } from "./SettingsPanel";

const TRUST_WORD: Record<TrustState, string> = { confirmed: "확인", assumed: "가정", unknown: "모름", failed: "못 지킴" };

function ResultCard({ id, entry, r, onCause }: { id: string; entry: NodeCatalogEntry | undefined; r: NodeRunResult; onCause: () => void }) {
  const ex = r.explain;
  const h = r.status === "ok" ? ex?.headline : null;
  return (
    <article className={`pg-simple-result pg-simple-result--${r.status}`} data-node-id={id}>
      <p className="pg-simple-kind">{entry?.plain_label ?? r.type}</p>
      <h3 className="pg-simple-title">{ex?.title ?? (r.status === "ok" ? "계산했어요" : "계산하지 못했어요")}</h3>
      {h && h.value !== null && (
        <p className="pg-simple-headline"><b>{Number.isInteger(Number(h.value)) ? Number(h.value) : Number(h.value).toFixed(1)}</b>
          <span>{h.unit} {h.label}</span></p>
      )}
      {r.status !== "ok" && (
        <>
          <p className="pg-simple-why">{ex?.facts?.[0] ?? r.reason}</p>
          <button type="button" className="pg-cause-btn" onClick={onCause}><Route size={12} aria-hidden="true" /> 캔버스에서 원인 보기</button>
        </>
      )}
      {r.status === "ok" && r.glance && <Glance glance={r.glance} />}
      {r.status === "ok" && (ex?.trust?.length ?? 0) > 0 && (
        <ul className="pg-simple-trust" aria-label="믿어도 되나요">
          {ex!.trust!.map((t, i) => (
            <li key={i}><span className={`pg-tag pg-tag--${t.state}`}>{TRUST_WORD[t.state]}</span> {t.text}</li>
          ))}
        </ul>
      )}
      {r.status === "ok" && (ex?.unmeasured?.length ?? 0) > 0 && (
        <details className="pg-simple-unmeasured"><summary>재지 않은 것 {ex!.unmeasured!.length}가지</summary>
          <ul>{ex!.unmeasured!.map((u) => <li key={u}>{u}</li>)}</ul>
        </details>
      )}
    </article>
  );
}

export function SimpleView({ nodes, edges, groups, catalog, results, staleIds, running, onRun, onChange, onCause }: {
  nodes: PgNode[]; edges: Edge[]; groups: GraphGroup[]; catalog: NodeCatalogEntry[];
  results: Record<string, NodeRunResult> | null; staleIds: ReadonlySet<string>; running: boolean;
  onRun: () => void; onChange: (id: string, params: Record<string, unknown>) => void; onCause: (id: string) => void;
}) {
  const order = topoOrder(nodes.map((n) => n.id), edges);
  const entryOf = (id: string) => catalog.find((c) => c.type === nodes.find((n) => n.id === id)?.data.kind);
  const hasQuestions = (id: string) => fieldsOf(entryOf(id)?.params_schema ?? null).some((f) => f.ui.tier === "basic");
  const strategies = groups.filter((g) => g.kind === "strategy");
  const lane = portfolioLane(nodes, edges, groups);
  const sections: { key: string; title: string; ids: string[] }[] = strategies.length
    ? [...strategies.map((g) => ({ key: g.id, title: g.label, ids: order.filter((id) => g.members.includes(id)) })),
       ...(lane.size ? [{ key: "portfolio", title: "합친 포트폴리오", ids: order.filter((id) => lane.has(id)) }] : []),
       ...(() => {
         const rest = order.filter((id) => !lane.has(id) && !strategies.some((g) => g.members.includes(id)));
         return rest.length ? [{ key: "rest", title: "전략 밖", ids: rest }] : [];
       })()]
    : [{ key: "all", title: "이 흐름", ids: order }];
  // 낡은 노드(BT5)의 결과만 거둔다 — 바뀌지 않은 상류의 결과는 그대로 보인다.
  const live = results ? Object.fromEntries(Object.entries(results).filter(([id]) => !staleIds.has(id))) : null;
  const stale = staleIds.size > 0 && !!results;

  return (
    <div className="pg-simple" aria-label="간단히 보기">
      <header className="pg-simple-top">
        <div>
          <h2 className="pg-simple-h">정할 것만 고르고, 결과만 봐요</h2>
          <p className="pg-simple-sub">여기서 바꾼 값은 캔버스의 노드 설정에 그대로 들어가요. 바꾸지 않은 칸은 서버 기본값이에요.</p>
        </div>
        <button type="button" className="pg-btn pg-btn--primary pg-simple-run" disabled={running || !nodes.length} onClick={onRun}>
          {running ? <><Loader2 size={14} className="spin" /> 계산하는 중</> : "계산하기"}
        </button>
      </header>
      {stale && <p className="pg-simple-stale">설정이 바뀌었어요 — 바뀐 곳 {staleIds.size}개는 다시 계산하면 결과가 새로 나와요.</p>}
      {sections.map((sec) => {
        const asks = sec.ids.filter(hasQuestions);
        const outs = sec.ids.filter((id) => live?.[id] && (live[id].status !== "ok" || live[id].explain?.headline || live[id].glance));
        return (
          <section key={sec.key} className="pg-simple-sec" data-section={sec.key}>
            <h2 className="pg-simple-sec-h">{sec.title}</h2>
            <h3 className="pg-simple-step">① 정할 것</h3>
            {asks.length === 0 && <p className="pg-help">정할 것이 없어요.</p>}
            {asks.map((id) => {
              const n = nodes.find((x) => x.id === id)!;
              const entry = entryOf(id);
              return (
                <div key={id} className="pg-simple-ask" data-node-id={id}>
                  <p className="pg-simple-kind">{entry?.plain_label ?? n.data.kind}</p>
                  <BasicFields entry={entry} params={n.data.params ?? {}} onChange={(p) => onChange(id, p)} />
                </div>
              );
            })}
            <h3 className="pg-simple-step">② 결과</h3>
            {!live && <p className="pg-help">아직 계산하지 않았어요 — 위의 ‘계산하기’를 눌러 주세요.</p>}
            {live && outs.length === 0 && <p className="pg-help">이 묶음에서 보여 줄 결과가 없어요.</p>}
            {outs.map((id) => <ResultCard key={id} id={id} entry={entryOf(id)} r={live![id]} onCause={() => onCause(id)} />)}
          </section>
        );
      })}
    </div>
  );
}
