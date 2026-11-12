"use client";
/**
 * 갈래 틀 · 갈래 비교 (BM C3 · "이 조건이면?" — 사람이 정한 갈래 ≤ 4)
 * ==========================================================================
 * 틀: 복제 노드를 감싼 점선 상자 — 이름("갈래 B") · **바꾼 설정만**(칩) · 이 갈래를 원본으로(BN N2 승격) · 지우기.
 * 비교: 원본과 갈래들을 열로, ★값이 다른 행만★ — 바꾼 설정 행 + 결과(헤드라인) 행. 계산하지 못한 칸은 "—"(0 이 아니다).
 * ★다중 비교 정직성★ — 표 위에 늘 한 줄: 같은 과거로 여러 갈래를 고르면 우연히 좋아 보이는 쪽을 고를 위험이 커진다.
 * 가장 좋은 갈래를 고르거나 추천하지 않는다(정렬도 하지 않는다 — 갈래 순서 그대로).
 * 과거 성과(백테스트) 노드가 갈래에 들어 있으면 서버가 N(원본 + 갈래 수)으로 보정한 샤프 확률(DSR)을 함께(BO O3) —
 * N 은 지금 남아 있는 갈래만 센 하한이라는 서버 문장도 그대로 보인다.
 */
import { memo, useEffect, useState } from "react";
import type { Node, NodeProps } from "@xyflow/react";
import { ArrowUpToLine, Boxes, Trash2 } from "lucide-react";
import {
  fieldsOf,
  paramDiff,
  portfolioGraphApi,
  type BranchEvidence,
  shortValue,
  type GraphBranch,
  type NodeCatalogEntry,
  type NodeRunResult,
  type PgNode,
} from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "./store";

export const PG_BRANCH_TYPE = "pgBranch";

export type BranchFrameData = { branchId: string; label: string; width: number; height: number; diffs: string[]; rootName: string;
  /** U6 — 복제가 이미 전략 상자 안이면 [전략으로 묶기] 를 보이지 않는다. */
  boxed: boolean };

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

function BranchFrameImpl({ data }: NodeProps<Node<BranchFrameData>>) {
  const remove = usePortfolioGraph((s) => s.removeBranch);
  return (
    <div className="pg-branch" data-branch-id={data.branchId} style={{ width: data.width, height: data.height }}>
      <div className="pg-branch-head">
        <b className="pg-branch-name">{data.label}</b>
        <span className="pg-branch-of">‘{data.rootName}’에서 갈라짐</span>
        <button type="button" className="pg-branch-promote nodrag" disabled={data.diffs.length === 0}
                title="이 대안의 변경 설정을 원본에 반영하고 대안을 삭제합니다 (되돌리기 가능)"
                onClick={() => { const st = usePortfolioGraph.getState(); st.act(() => st.promoteBranch(data.branchId)); }}>
          <ArrowUpToLine size={13} aria-hidden="true" /><span className="pg-branch-btn-t">이 대안을 원본으로</span>
        </button>
        {!data.boxed && (
          <button type="button" className="pg-branch-strategy nodrag" title="이 대안을 전략 상자로 묶습니다 — 비중 출력 노드가 있어야 합니다 (되돌리기 가능)"
                  onClick={() => { const st = usePortfolioGraph.getState(); st.act(() => st.branchStrategy(data.branchId)); }}>
            <Boxes size={13} aria-hidden="true" /><span className="pg-branch-btn-t">전략으로 묶기</span>
          </button>
        )}
        <button type="button" className="pg-group-x pg-branch-x nodrag" aria-label={`${data.label} 삭제`}
                title="대안과 복제한 노드를 삭제합니다" onClick={() => remove(data.branchId)}>
          <Trash2 size={14} aria-hidden="true" />
        </button>
      </div>
      <div className="pg-branch-diffs">
        {data.diffs.length === 0
          ? <span className="pg-branch-same">아직 원본과 동일합니다 — 설정을 변경하십시오</span>
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
/** 확률 한 칸 — 모르면 "—" 와 그 사유(마우스를 올리면). 0 으로 채우지 않는다. */
function probCell(v: number | null | undefined, why: string | null | undefined): { text: string; title?: string } {
  return typeof v === "number" && Number.isFinite(v) ? { text: `${Math.round(v * 100)}%` } : { text: "—", title: why ?? "측정할 수 없습니다" };
}

/**
 * 과거 성과 노드 하나의 보정 행(BO O3) — 원본·갈래의 누적 곡선을 서버에 보내 PSR·DSR 을 받는다.
 * 곡선이 하나라도 없으면 보내지 않고 이유를 말한다(있는 것만으로 N 을 줄이면 보정이 약해진다).
 */
function DsrRows({ name, labels, curves }: { name: string; labels: string[]; curves: (number[] | null)[] }) {
  const [ev, setEv] = useState<BranchEvidence | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const missing = labels.filter((_, i) => !curves[i]);
  const key = JSON.stringify(curves.map((c) => (c ? [c.length, c[c.length - 1]] : null)));
  useEffect(() => {
    setEv(null); setErr(null);
    if (missing.length) return;
    let alive = true;
    portfolioGraphApi.branchEvidence(labels.map((label, i) => ({ label, equity: curves[i]! })))
      .then((r) => { if (alive) setEv(r); })
      .catch((e: Error) => { if (alive) setErr(e.message); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  const colspan = labels.length + 1;
  if (missing.length) {
    return (
      <tr className="pg-branch-row--dsr" data-row={`dsr:${name}`}>
        <th scope="row">보정 · {name}</th>
        <td colSpan={colspan - 1} className="pg-branch-dsr-why">{missing.join(", ")}의 과거 성과가 아직 없습니다 — 모두 계산해야 보정할 수 있습니다.</td>
      </tr>
    );
  }
  if (err || !ev) {
    return (
      <tr className="pg-branch-row--dsr" data-row={`dsr:${name}`}>
        <th scope="row">보정 · {name}</th>
        <td colSpan={colspan - 1} className="pg-branch-dsr-why">{err ?? "보정하는 중…"}</td>
      </tr>
    );
  }
  const row = (key: "psr0" | "dsr" | "dsr_eff", title: string) => (
    <tr className="pg-branch-row--dsr" data-row={`${key}:${name}`}>
      <th scope="row">{title}</th>
      {ev.rows.map((r, i) => {
        const c = probCell(r[key], key === "dsr" ? (r.reason ?? ev.reason)
          : key === "dsr_eff" ? (r.reason ?? ev.reason ?? ev.n_eff_reason) : r.reason);
        return <td key={i} className="pg-td-num" data-value={r[key] ?? ""} title={c.title}>{c.text}</td>;
      })}
    </tr>
  );
  return (
    <>
      {row("psr0", `보정 · ${name} · 샤프가 0보다 클 확률`)}
      {row("dsr", `보정 · ${name} · ${ev.n}회 비교의 우연을 보정한 확률`)}
      {row("dsr_eff", ev.n_eff !== null
        ? `보정 · ${name} · 상관을 감안한 유효 비교 약 ${ev.n_eff.toFixed(1)}회로 보정한 확률(추정)`
        : `보정 · ${name} · 상관을 감안한 유효 비교 횟수로 보정한 확률(추정)`)}
    </>
  );
}

export function BranchCompare({ branches, nodes, catalog, results, staleIds }: {
  branches: GraphBranch[]; nodes: PgNode[]; catalog: NodeCatalogEntry[];
  results: Record<string, NodeRunResult> | null; staleIds: ReadonlySet<string>;
}) {
  const roots = [...new Set(branches.map((b) => b.of_root))];
  if (!roots.length) return <p className="pg-empty">노드를 선택해 ‘대안 만들기’를 누르면 여기서 원본과 비교합니다.</p>;
  return (
    <div className="pg-branch-compare">
      {roots.map((root) => {
        const bs = branches.filter((b) => b.of_root === root);
        const rootNode = nodes.find((n) => n.id === root);
        const rootEntry = catalog.find((c) => c.type === rootNode?.data.kind);
        const origIds = [...new Set(bs.flatMap((b) => Object.values(b.map)))];
        const copyOf = (b: GraphBranch, orig: string) => Object.entries(b.map).find(([, o]) => o === orig)?.[0];
        const node = (id: string | undefined) => nodes.find((n) => n.id === id);
        const res = (id: string | undefined) => (id && results && !staleIds.has(id) ? results[id] : undefined);
        const stale = [root, ...origIds, ...bs.flatMap((b) => Object.keys(b.map))].some((id) => staleIds.has(id));
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
        // 과거 성과 노드(백테스트) — 갈래에 복제된 것만. 곡선은 서버 결과 그대로(`equity_curve`), 낡은 결과는 쓰지 않는다.
        const btests = origIds.filter((id) => node(id)?.data.kind === "backtest");
        const curveOf = (id: string | undefined): number[] | null => {
          const r = res(id);
          const c = r?.status === "ok" && !r.previous ? (r.view as { equity_curve?: unknown } | undefined)?.equity_curve : null;
          return Array.isArray(c) && c.every((x) => typeof x === "number") ? (c as number[]) : null;
        };
        const evNote = btests.length ? "현재 남아 있는 대안만 집계했습니다 — 이전에 시도하고 삭제한 설정까지 포함하면 실제 비교 횟수는 더 많을 수 있습니다." : null;
        return (
          <section key={root} className="pg-branch-table-wrap" data-root={root}>
            <h4 className="pg-h4">‘{rootEntry?.plain_label ?? root}’ 대안 {bs.length}개</h4>
            <p className="pg-branch-honest" role="note">
              대안 {bs.length}개를 같은 과거로 비교했습니다 — 비교 횟수가 늘수록 우연히 좋아 보이는 대안을 선택할 위험(다중 비교)이 커집니다.
              표본 밖에서 확인하기 전에는 결론 내리지 마십시오.
            </p>
            {btests.length > 0 && (
              <p className="pg-branch-n" data-n={bs.length + 1}>
                원본과 대안 {bs.length}개, 모두 {bs.length + 1}번 비교했습니다 — 아래 ‘우연을 보정한 확률’은 이 횟수로 보정한 값입니다.
                {evNote && <> {evNote}</>}
              </p>
            )}
            {btests.length === 0 && (
              <p className="pg-help pg-branch-dsr-none">과거 성과 노드가 대안에 들어 있어야 다중 비교의 우연을 보정할 수 있습니다.</p>
            )}
            {rows.length === 0 && btests.length === 0 ? (
              <p className="pg-help">아직 원본과 다른 값이 없습니다 — 대안의 설정을 바꾸고 계산하십시오.</p>
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
                  {btests.map((orig) => (
                    <DsrRows key={orig} name={catalog.find((c) => c.type === node(orig)?.data.kind)?.plain_label ?? orig}
                             labels={["원본", ...bs.map((b) => b.label)]}
                             curves={[curveOf(orig), ...bs.map((b) => curveOf(copyOf(b, orig)))]} />
                  ))}
                </tbody>
              </table>
            )}
            {stale && <p className="pg-help">설정이 바뀐 칸은 비워 두었습니다 — 재계산하십시오.</p>}
          </section>
        );
      })}
    </div>
  );
}
