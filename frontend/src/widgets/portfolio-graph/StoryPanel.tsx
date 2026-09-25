"use client";
/**
 * 이야기 탭 — 같은 그래프를 위→아래로 읽는 렌즈 (BJ3 · 목업 승인본)
 * ==========================================================================
 * 번호는 캔버스 노드 번호와 같다(그래프 순서 하나). 문장은 서버 `explain` 을 그대로 그린다 —
 * 화면이 문장을 짓지 않는다(사용자 결정). "믿어도 되나요?" 는 확인·가정·몰라요·실패를 한 줄씩.
 * 연습용 데이터가 하나라도 있으면 맨 위에 경고를 먼저 놓는다.
 */
import type { NodeCatalogEntry, NodeRunResult, PgNode } from "@/entities/portfolio-graph";

const TRUST_TEXT = { confirmed: "확인", assumed: "가정", unknown: "몰라요", failed: "실패" } as const;

function Bars({ weights, labels }: { weights: Record<string, number>; labels?: Record<string, string> }) {
  const rows = Object.entries(weights).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  return (
    <div className="pg-bars">
      {rows.map(([k, v]) => (
        <div key={k} className="pg-bar-row">
          <span className="pg-bar-name">{labels?.[k] ?? k}</span>
          <span className="pg-bar-track"><i className={v < 0 ? "neg" : ""} style={{ width: `${Math.min(100, Math.abs(v))}%` }} /></span>
          <span className="pg-bar-pct">{v.toFixed(1)}%</span>
        </div>
      ))}
    </div>
  );
}

function Step({ n, node, entry, result, stale, current, onSelect, onDetail }: {
  n: number; node: PgNode; entry?: NodeCatalogEntry; result?: NodeRunResult; stale: boolean; current: boolean;
  onSelect: () => void; onDetail: () => void;
}) {
  const ex = result && !stale ? result.explain : null;
  const view = (result?.view ?? {}) as Record<string, unknown>;
  const title = ex?.title ?? `${entry?.plain_label ?? node.data.kind}`;
  const trust = ex?.trust ?? [];
  return (
    <li className={`pg-step${current ? " pg-step--cur" : ""}${result && !stale ? ` pg-step--${result.status}` : ""}`}
        data-node-id={node.id}>
      <button type="button" className="pg-step-num" onClick={onSelect} aria-label={`${n}번 노드 선택`}>{n}</button>
      <div className="pg-step-body">
        <h3 className="pg-step-title"><button type="button" onClick={onSelect}>{title}</button></h3>
        {!ex && <p className="pg-step-p">{stale && result ? "설정을 바꿔서 다시 계산해야 해요." : "계산하면 여기서 설명해 드려요."}</p>}
        {ex && result?.status === "ok" && node.data.kind === "optimizer" && view.weights ? (
          <Bars weights={view.weights as Record<string, number>} labels={view.labels as Record<string, string>} />
        ) : ex?.headline && ex.headline.value !== null ? (
          <div className="pg-step-big">{ex.headline.text}<small>{ex.headline.label}</small></div>
        ) : null}
        {(ex?.facts ?? []).map((f, i) => <p key={i} className="pg-step-p">{f}</p>)}
        {trust.length > 0 && (
          <div className="pg-trust">
            <div className="pg-trust-q">믿어도 되나요?</div>
            {trust.map((t, i) => (
              <div key={i} className="pg-trust-a"><span className={`pg-tag pg-tag--${t.state}`}>{TRUST_TEXT[t.state]}</span><span>{t.text}</span></div>
            ))}
          </div>
        )}
        {(ex?.unmeasured ?? []).length > 0 && (
          <details className="pg-unmeasured">
            <summary>재지 않은 것 {ex!.unmeasured!.length}가지</summary>
            <ul>{ex!.unmeasured!.map((u, i) => <li key={i}>{u}</li>)}</ul>
          </details>
        )}
        {ex && <button type="button" className="pg-more" onClick={onDetail}>숫자 자세히 보기</button>}
      </div>
    </li>
  );
}

export function StoryPanel({ order, nodes, catalog, results, stale, selectedId, onSelect, onDetail }: {
  order: string[];
  nodes: PgNode[];
  catalog: NodeCatalogEntry[];
  results: Record<string, NodeRunResult> | null;
  stale: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDetail: (id: string) => void;
}) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const practice = !stale && Object.values(results ?? {}).some((r) =>
    (r.explain?.trust ?? []).some((t) => t.state === "unknown" && t.text.includes("연습용")));
  if (!nodes.length) {
    return <p className="pg-empty">캔버스가 비어 있어요. 왼쪽에서 노드를 끌어 오거나 ‘빠른 시작’을 눌러 보세요.</p>;
  }
  return (
    <div className="pg-story">
      {practice && (
        <div className="pg-notice" role="note">
          <b>연습용 결과예요.</b> 실제 시세가 아니라 합성 데이터로 계산했어요. 투자 판단에 쓰기 전에 실데이터로 다시 계산해 주세요.
        </div>
      )}
      {stale && results && <div className="pg-notice pg-notice--stale" role="note">그래프가 바뀌었어요. ‘계산하기’를 누르면 설명이 새로 나와요.</div>}
      <ol className="pg-steps">
        {order.map((id, i) => {
          const node = byId.get(id);
          if (!node) return null;
          return (
            <Step key={id} n={i + 1} node={node} entry={catalog.find((c) => c.type === node.data.kind)}
                  result={results?.[id]} stale={stale} current={selectedId === id}
                  onSelect={() => onSelect(id)} onDetail={() => onDetail(id)} />
          );
        })}
      </ol>
    </div>
  );
}
