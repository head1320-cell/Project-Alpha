"use client";
/**
 * 갈래 틀 · 갈래 비교 (BM C3 · "이 조건이면?" — 사람이 정한 갈래 ≤ 4)
 * ==========================================================================
 * 틀: 복제 노드를 감싼 점선 상자 — 이름("갈래 B") · **바꾼 설정만**(칩) · 이 갈래를 원본으로(BN N2 승격) · 지우기.
 * 비교: 원본과 갈래들을 열로, ★값이 다른 행만★ — 바꾼 설정 행 + 결과(헤드라인) 행. 계산하지 못한 칸은 "—"(0 이 아니다).
 * ★다중 비교 정직성★ — 표 위에 늘 한 줄: 같은 과거로 여러 갈래를 고르면 우연히 좋아 보이는 쪽을 고를 위험이 커진다.
 * 가장 좋은 갈래를 고르거나 추천하지 않는다(정렬도 하지 않는다 — 갈래 순서 그대로).
 */
import { memo } from "react";
import type { NodeProps } from "reactflow";
import { ArrowUpToLine, Trash2 } from "lucide-react";
import {
  fieldsOf,
  paramDiff,
  shortValue,
  type GraphBranch,
  type NodeCatalogEntry,
  type NodeRunResult,
  type PgNode,
} from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "./store";

export const PG_BRANCH_TYPE = "pgBranch";

export interface BranchFrameData { branchId: string; label: string; width: number; height: number; diffs: string[]; rootName: string }

function fieldLabel(entry: NodeCatalogEntry | undefined, key: string): string {
  return fieldsOf(entry?.params_schema ?? null).find((f) => f.name === key)?.ui.label ?? key;
}

/** 갈래의 바꾼 설정 — "비중 계산 · 위험 성향 2.5 → 6". */
export function branchDiffs(b: GraphBranch, nodes: PgNode[], catalog: NodeCatalogEntry[]): string[] {
  const out: string[] = [];
  for (const [copy, orig] of Object.entries(b.map)) {
    const c = nodes.find((n) => n.id === copy);
    const o = nodes.find((n) => n.id === orig);
    if (!c || !o) continue;
    const entry = catalog.find((x) => x.type === o.data.kind);
    for (const d of paramDiff(o.data.params ?? {}, c.data.params ?? {})) {
      out.push(`${entry?.plain_label ?? o.data.kind} · ${fieldLabel(entry, d.key)} ${shortValue(d.from)} → ${shortValue(d.to)}`);
    }
  }
  return out;
}

function BranchFrameImpl({ data }: NodeProps<BranchFrameData>) {
  const remove = usePortfolioGraph((s) => s.removeBranch);
  return (
    <div className="pg-branch" data-branch-id={data.branchId} style={{ width: data.width, height: data.height }}>
      <div className="pg-branch-head">
        <b className="pg-branch-name">{data.label}</b>
        <span className="pg-branch-of">‘{data.rootName}’에서 갈라짐</span>
        <button type="button" className="pg-branch-promote nodrag" disabled={data.diffs.length === 0}
                title="이 갈래의 바꾼 설정을 원본에 옮기고 갈래를 지워요 (되돌리기 가능)"
                onClick={() => { const st = usePortfolioGraph.getState(); st.setNote(st.promoteBranch(data.branchId)); }}>
          <ArrowUpToLine size={13} aria-hidden="true" /> 이 갈래를 원본으로
        </button>
        <button type="button" className="pg-group-x pg-branch-x nodrag" aria-label={`${data.label} 지우기`}
                title="갈래와 복제한 노드를 지워요" onClick={() => remove(data.branchId)}>
          <Trash2 size={14} aria-hidden="true" />
        </button>
      </div>
      <div className="pg-branch-diffs">
        {data.diffs.length === 0
          ? <span className="pg-branch-same">아직 원본과 같아요 — 설정을 바꿔 보세요</span>
          : data.diffs.slice(0, 3).map((d) => <span key={d} className="pg-branch-chip">{d}</span>)}
        {data.diffs.length > 3 && <span className="pg-branch-chip">외 {data.diffs.length - 3}개</span>}
      </div>
    </div>
  );
}

export const BranchFrame = memo(BranchFrameImpl);

function headlineText(r: NodeRunResult | undefined, previous: boolean): string {
  if (!r || previous) return "—";
  if (r.status !== "ok") return r.status === "blocked" ? "막힘" : "실패";
  const h = r.explain?.headline;
  if (!h) return "—";
  if (h.value === null || h.value === undefined) return h.text || "—";
  const v = Number(h.value);
  return `${Number.isInteger(v) ? v : v.toFixed(2)}${h.unit ?? ""}`;
}

/** 오른쪽 패널 "갈래" 탭 — 원본 뿌리마다 표 하나. */
export function BranchCompare({ branches, nodes, catalog, results, stale }: {
  branches: GraphBranch[]; nodes: PgNode[]; catalog: NodeCatalogEntry[];
  results: Record<string, NodeRunResult> | null; stale: boolean;
}) {
  const roots = [...new Set(branches.map((b) => b.of_root))];
  if (!roots.length) return <p className="pg-empty">노드를 골라 ‘갈래 만들기’를 누르면 여기서 원본과 나란히 봐요.</p>;
  return (
    <div className="pg-branch-compare">
      {roots.map((root) => {
        const bs = branches.filter((b) => b.of_root === root);
        const rootNode = nodes.find((n) => n.id === root);
        const rootEntry = catalog.find((c) => c.type === rootNode?.data.kind);
        const origIds = [...new Set(bs.flatMap((b) => Object.values(b.map)))];
        const copyOf = (b: GraphBranch, orig: string) => Object.entries(b.map).find(([, o]) => o === orig)?.[0];
        const node = (id: string | undefined) => nodes.find((n) => n.id === id);
        const res = (id: string | undefined) => (id && results && !stale ? results[id] : undefined);
        type Row = { key: string; kind: "set" | "out"; name: string; cells: string[] };
        const rows: Row[] = [];
        for (const orig of origIds) {
          const o = node(orig);
          const entry = catalog.find((c) => c.type === o?.data.kind);
          const keys = new Set(bs.flatMap((b) => paramDiff(o?.data.params ?? {}, node(copyOf(b, orig))?.data.params ?? {}).map((d) => d.key)));
          for (const k of keys) {
            rows.push({ key: `set:${orig}:${k}`, kind: "set", name: `${entry?.plain_label ?? orig} · ${fieldLabel(entry, k)}`,
                        cells: [shortValue(o?.data.params?.[k]), ...bs.map((b) => shortValue(node(copyOf(b, orig))?.data.params?.[k]))] });
          }
        }
        for (const orig of origIds) {
          const o = node(orig);
          const entry = catalog.find((c) => c.type === o?.data.kind);
          const cells = [headlineText(res(orig), !!res(orig)?.previous),
                         ...bs.map((b) => { const id = copyOf(b, orig); return headlineText(res(id), !!res(id)?.previous); })];
          // ★값이 다른 행만★ — 모두 같으면(모두 "—" 포함) 보이지 않는다.
          if (new Set(cells).size > 1) {
            const h = res(orig)?.explain?.headline ?? bs.map((b) => res(copyOf(b, orig))?.explain?.headline).find(Boolean);
            rows.push({ key: `out:${orig}`, kind: "out", name: `${entry?.plain_label ?? orig}${h?.label ? ` · ${h.label}` : ""}`, cells });
          }
        }
        return (
          <section key={root} className="pg-branch-table-wrap" data-root={root}>
            <h4 className="pg-h4">‘{rootEntry?.plain_label ?? root}’ 갈래 {bs.length}개</h4>
            <p className="pg-branch-honest" role="note">
              갈래 {bs.length}개를 같은 과거로 비교했어요 — 여러 번 고를수록 우연히 좋아 보이는 쪽을 고를 위험이 커져요.
              표본 밖에서 확인하기 전에는 결론 내리지 마세요.
            </p>
            {rows.length === 0 ? (
              <p className="pg-help">아직 원본과 다른 값이 없어요 — 갈래의 설정을 바꾸고 계산해 보세요.</p>
            ) : (
              <table className="pg-table pg-branch-table">
                <thead><tr><th scope="col">다른 값만</th><th scope="col">원본</th>{bs.map((b) => <th key={b.id} scope="col">{b.label}</th>)}</tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.key} className={`pg-branch-row--${r.kind}`} data-row={r.key}>
                      <th scope="row">{r.kind === "set" ? "설정 · " : "결과 · "}{r.name}</th>
                      {r.cells.map((c, i) => <td key={i} className={`pg-td-num${i > 0 && c !== r.cells[0] ? " pg-branch-diff" : ""}`}>{c}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {stale && <p className="pg-help">설정이 바뀌어서 결과 칸은 비워 두었어요 — 다시 계산해 주세요.</p>}
          </section>
        );
      })}
    </div>
  );
}
