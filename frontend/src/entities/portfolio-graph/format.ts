/**
 * 파일 포맷 ↔ 캔버스 — ★순수 함수만★ (BI3)
 * ==========================================================================
 * 스펙 §4.1. 두 약속:
 *   1. **왕복** — `toDoc(fromDoc(doc))` 는 같은 노드 id·타입·파라미터·위치·링크를 돌려준다.
 *   2. **아무것도 버리지 않는다** — 카탈로그에 없는 노드 타입도, 없는 포트를 가리키는
 *      링크도 캔버스에 뜬다. 모르는 노드는 원본 type·params 를 그대로 들고 빨갛게 그려지고,
 *      없는 포트는 그 노드에 "미상 포트" 로 붙는다. 조용히 빠지면 다음에 내보낼 때
 *      사용자가 모르는 사이 그래프가 줄어든다.
 */
import type { Edge, Node } from "@xyflow/react";
import { isGoalKey } from "./goals";
import { slotBase, slotHeight, SLOT_MAX_K } from "./size";
import {
  GRAPH_FORMAT,
  GRAPH_VERSION,
  type CatalogPort,
  type GraphDoc,
  type GraphDocEdge,
  type GraphBranch,
  type GraphDocNode,
  type GraphGroup,
  type NodeCatalogEntry,
} from "./types";

/** React Flow 노드 타입 — 모든 그래프 노드는 카탈로그로 그리는 범용 노드 하나다. */
export const PG_NODE_TYPE = "pg";

export type PgNodeData = {
  /** 그래프 노드 타입(`optimizer` 등) — React Flow 의 `type` 과 다른 칸이다. */
  kind: string;
  params: Record<string, unknown>;
  /** 카탈로그에 없는 타입이면 사유. 원본은 `kind`·`params` 에 그대로 있다. */
  unknownReason?: string | null;
  /** 카탈로그에 없는 포트를 가리키는 링크가 있을 때 — 버리지 않고 여기 붙인다. */
  extraInputs?: string[];
  extraOutputs?: string[];
  /** 말로 설계(AI4) — 칸 → 그 값을 말한 말씀 조각(설정 탭의 '말씀에서' 칩). 사람이 그 칸을 고치면 지운다. */
  said?: Record<string, string>;
  /** 결과 칸 높이(R3) — 기본보다 늘렸을 때만. 문서의 `size.slot_h`. */
  slotH?: number;
}

export type PgNode = Node<PgNodeData>;

export interface ParseResult {
  doc: GraphDoc | null;
  problems: string[];
}

const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/** 말로 설계의 출처(AI4) — 칸 이름 → 말씀 조각(글, 300자 이하). 하나라도 망가졌으면 통째로 버린다(값은 그대로 — 출처만 모른다). */
const MAX_SAID = 300;
function saidOf(v: unknown): { ok: Record<string, string> | null; bad: boolean } {
  if (v === undefined) return { ok: null, bad: false };
  if (!isObj(v) || !Object.entries(v).every(([k, x]) => k && typeof x === "string" && x.length <= MAX_SAID)) return { ok: null, bad: true };
  return { ok: Object.keys(v).length ? { ...(v as Record<string, string>) } : null, bad: false };
}

/** 경유점(CF4c) — 점마다 유한한 x·y 가 있어야 한다. 하나라도 망가졌으면 그 선의 경유점은 통째로 버린다(지어내지 않는다). 없으면 `null`. */
function waypointsOf(v: unknown): { ok: { x: number; y: number }[] | null; bad: boolean } {
  if (v === undefined) return { ok: null, bad: false };
  if (!Array.isArray(v) || !v.every((p) => isObj(p) && Number.isFinite(p.x) && Number.isFinite(p.y))) return { ok: null, bad: true };
  return { ok: v.length ? v.map((p) => ({ x: Number(p.x), y: Number(p.y) })) : null, bad: false };
}

/**
 * 파일 텍스트 → 문서. ★다른 포맷·버전은 불러오지 않는다★ — 이 파일이 무엇을 뜻하는지 모르면
 * 캔버스에 그리는 것 자체가 추측이다. 노드 타입이 모르는 것인지는 여기서 보지 않는다
 * (그것은 `fromDoc` 이 미상 노드로 그린다).
 */
export function parseFile(text: string): ParseResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    return { doc: null, problems: [`JSON 형식이 아니에요 — ${(e as Error).message}. 파일이 잘렸거나 다른 형식인지 확인해 주세요`] };
  }
  if (!isObj(raw)) return { doc: null, problems: ["문서가 객체가 아닙니다."] };
  const problems: string[] = [];
  if (raw.format !== GRAPH_FORMAT) {
    problems.push(`포트폴리오 그래프 파일이 아닙니다 — format=${JSON.stringify(raw.format)}, `
      + `기대값 "${GRAPH_FORMAT}".`);
  }
  if (raw.version !== GRAPH_VERSION) {
    problems.push(`지원하지 않는 버전입니다 — version=${JSON.stringify(raw.version)}, `
      + `이 화면은 ${GRAPH_VERSION} 만 읽습니다.`);
  }
  if (!Array.isArray(raw.nodes) || !Array.isArray(raw.edges)) {
    problems.push("nodes·edges 가 목록이 아닙니다.");
  }
  if (problems.length) return { doc: null, problems };

  const nodes: GraphDocNode[] = [];
  const seen = new Set<string>();
  for (const [i, n] of (raw.nodes as unknown[]).entries()) {
    if (!isObj(n) || typeof n.id !== "string" || !n.id || typeof n.type !== "string") {
      problems.push(`노드 #${i + 1} 에 id·type 이 없습니다.`);
      continue;
    }
    if (seen.has(n.id)) {
      problems.push(`노드 id 중복: ${n.id}`);
      continue;
    }
    seen.add(n.id);
    const pos = isObj(n.position) ? n.position : {};
    const said = saidOf(n.said);
    if (said.bad) problems.push(`노드 ${n.id} 의 ‘말씀에서’ 출처가 형식에 맞지 않아 뺐어요 — 값은 그대로예요.`);
    // 결과 칸 높이(R3) — 숫자가 아니면 빼고, 범위 밖이면 맞춘다. 둘 다 말한다(말없이 고치지 않음). 기본이면 쓰지 않는다.
    let slot: number | null = null;
    if (n.size !== undefined) {
      const raw = isObj(n.size) ? n.size.slot_h : undefined;
      if (typeof raw !== "number" || !Number.isFinite(raw)) {
        problems.push(`노드 ${n.id} 의 결과 칸 높이가 숫자가 아니라 뺐어요 — 기본 높이로 보여요.`);
      } else {
        slot = slotHeight(n.type, raw);
        if (slot !== Math.round(raw)) {
          problems.push(`노드 ${n.id} 의 결과 칸 높이 ${raw} 은 범위(${slotBase(n.type)}~${slotBase(n.type) * SLOT_MAX_K}) 밖이라 ${slot} 으로 맞췄어요.`);
        }
        if (slot <= slotBase(n.type)) slot = null;
      }
    }
    nodes.push({
      id: n.id,
      type: n.type,
      params: isObj(n.params) ? n.params : {},
      position: {
        x: typeof pos.x === "number" ? pos.x : 0,
        y: typeof pos.y === "number" ? pos.y : i * 140,
      },
      ...(said.ok ? { said: said.ok } : {}),
      ...(slot ? { size: { slot_h: slot } } : {}),
    });
  }
  const edges: GraphDocEdge[] = [];
  for (const [i, e] of (raw.edges as unknown[]).entries()) {
    if (!isObj(e) || [e.source, e.source_port, e.target, e.target_port]
      .some((v) => typeof v !== "string" || !v)) {
      problems.push(`링크 #${i + 1} 에 source·source_port·target·target_port 가 없습니다.`);
      continue;
    }
    if (!seen.has(e.source as string) || !seen.has(e.target as string)) {
      problems.push(`링크 #${i + 1} 이 없는 노드를 가리킵니다 (${e.source} → ${e.target}).`);
      continue;
    }
    const wp = waypointsOf(e.waypoints);
    if (wp.bad) problems.push(`링크 #${i + 1} 의 경유점이 숫자 자리가 아니라 버렸어요 — 선은 그대로 이어요.`);
    edges.push({
      id: typeof e.id === "string" && e.id ? e.id
        : `${e.source}.${e.source_port}->${e.target}.${e.target_port}`,
      source: e.source as string, source_port: e.source_port as string,
      target: e.target as string, target_port: e.target_port as string,
      ...(wp.ok ? { waypoints: wp.ok } : {}),
    });
  }
  // 묶음 상자(BL1) — 없는 노드를 가리키는 구성원은 빼고, 비면 묶음도 뺀다(말하고).
  const groups: GraphGroup[] = [];
  if (Array.isArray(raw.groups)) {
    for (const [i, g] of (raw.groups as unknown[]).entries()) {
      if (!isObj(g) || typeof g.id !== "string" || !Array.isArray(g.members)) {
        problems.push(`묶음 #${i + 1} 에 id·members 가 없어 건너뛰었어요.`);
        continue;
      }
      const members = (g.members as unknown[]).filter((m): m is string => typeof m === "string" && seen.has(m));
      if (!members.length) { problems.push(`묶음 "${String(g.label ?? g.id)}" 에 남은 노드가 없어 건너뛰었어요.`); continue; }
      const strategy = g.kind === "strategy";
      groups.push({ id: g.id, label: typeof g.label === "string" ? g.label : g.id, members, collapsed: g.collapsed === true,
                    // 전략 상자(BM C2) — 선택 칸. 모르는 값은 버리고 그냥 묶음으로 읽는다(옛 문서는 그대로).
                    ...(strategy ? {
                      kind: "strategy" as const,
                      color: Number.isInteger(g.color) && (g.color as number) >= 0 ? (g.color as number) % 6 : 0,
                      output: typeof g.output === "string" && members.includes(g.output) ? g.output : null,
                    } : {}) });
    }
  }
  // 갈래(BM C3) — 없는 노드를 가리키는 짝은 빼고, 뿌리가 없으면 갈래를 뺀다(말하고). 옛 문서에는 없다.
  const branches: GraphBranch[] = [];
  if (Array.isArray(raw.branches)) {
    for (const [i, b] of (raw.branches as unknown[]).entries()) {
      if (!isObj(b) || typeof b.id !== "string" || typeof b.root !== "string" || typeof b.of_root !== "string" || !isObj(b.map)) {
        problems.push(`갈래 #${i + 1} 에 id·root·of_root·map 이 없어 건너뛰었어요.`);
        continue;
      }
      const map = Object.fromEntries(Object.entries(b.map as Record<string, unknown>)
        .filter(([c, o]) => typeof o === "string" && seen.has(c) && seen.has(o)) as [string, string][]);
      if (!(b.root in map) || !seen.has(b.of_root)) { problems.push(`갈래 "${String(b.label ?? b.id)}" 의 뿌리가 없어 건너뛰었어요.`); continue; }
      branches.push({ id: b.id, label: typeof b.label === "string" ? b.label : b.id, root: b.root, of_root: b.of_root, map });
    }
  }
  // 그림 고정(BN N2) — 문서에 있는 노드만. 없는 노드를 가리키는 고정은 빼고 말한다(갈래와 같은 규칙).
  const pinRaw = Array.isArray(raw.pinned) ? (raw.pinned as unknown[]) : [];
  const pinned = [...new Set(pinRaw.filter((x): x is string => typeof x === "string" && seen.has(x)))];
  if (pinRaw.length > pinned.length) problems.push(`없는 노드를 가리키는 그림 고정 ${pinRaw.length - pinned.length}개는 뺐어요.`);
  // 접기(CF1) — 고정과 같은 규칙. 없는 노드를 가리키면 빼고 말한다.
  const foldRaw = Array.isArray(raw.folded) ? (raw.folded as unknown[]) : [];
  const folded = [...new Set(foldRaw.filter((x): x is string => typeof x === "string" && seen.has(x)))];
  if (foldRaw.length > folded.length) problems.push(`없는 노드를 가리키는 접기 ${foldRaw.length - folded.length}개는 뺐어요.`);
  // 목표(AI1) — 네 키만. 모르는 값은 빼고 말한다(화면이 보낸 글이 AI 근거가 되지 않게 — 서버도 키로만 받는다).
  const rawGoal = isObj(raw.meta) ? raw.meta.goal : undefined;
  if (rawGoal !== undefined && !isGoalKey(rawGoal)) {
    problems.push(`모르는 목표 ‘${typeof rawGoal === "string" ? rawGoal : "형식이 틀린 값"}’는 뺐어요.`);
  }
  const meta = isObj(raw.meta) ? {
    name: typeof raw.meta.name === "string" ? raw.meta.name : undefined,
    exported_at: typeof raw.meta.exported_at === "string" ? raw.meta.exported_at : undefined,
    ...(isGoalKey(rawGoal) ? { goal: rawGoal } : {}),
  } : undefined;
  return {
    doc: { format: GRAPH_FORMAT, version: GRAPH_VERSION, meta, nodes, edges, ...(groups.length ? { groups } : {}),
           ...(branches.length ? { branches } : {}), ...(pinned.length ? { pinned } : {}), ...(folded.length ? { folded } : {}) },
    problems,
  };
}

const portNames = (ps: CatalogPort[] | undefined) => new Set((ps ?? []).map((p) => p.name));

/** 출처 칩은 ★값이 있는 칸★에만(값 없이 출처만 남은 칸은 말이 안 된다) · 아는 종류면 그 종류에 있는 칸만. */
function saidKept(n: GraphDocNode, entry: NodeCatalogEntry | undefined): Record<string, string> | null {
  if (!n.said) return null;
  const props = (entry?.params_schema as { properties?: Record<string, unknown> } | undefined)?.properties;
  const kept = Object.entries(n.said).filter(([f]) => f in n.params && (!entry || !!props?.[f]));
  return kept.length ? Object.fromEntries(kept) : null;
}

/** 문서 → React Flow. 모르는 타입·포트는 표시해서 남긴다. */
export function fromDoc(doc: GraphDoc, catalog: NodeCatalogEntry[]): { nodes: PgNode[]; edges: Edge[] } {
  const byType = new Map(catalog.map((c) => [c.type, c]));
  const extraIn = new Map<string, Set<string>>();
  const extraOut = new Map<string, Set<string>>();
  const kindOf = new Map(doc.nodes.map((n) => [n.id, n.type]));
  for (const e of doc.edges) {
    const src = byType.get(kindOf.get(e.source) ?? "");
    const dst = byType.get(kindOf.get(e.target) ?? "");
    if (!portNames(src?.outputs).has(e.source_port)) {
      extraOut.set(e.source, (extraOut.get(e.source) ?? new Set()).add(e.source_port));
    }
    if (!portNames(dst?.inputs).has(e.target_port)) {
      extraIn.set(e.target, (extraIn.get(e.target) ?? new Set()).add(e.target_port));
    }
  }
  const nodes: PgNode[] = doc.nodes.map((n) => {
    const said = saidKept(n, byType.get(n.type));
    return {
      id: n.id,
      type: PG_NODE_TYPE,
      position: { ...n.position },
      data: {
        kind: n.type,
        params: { ...n.params },
        unknownReason: byType.has(n.type) ? null
          : `모르는 노드 타입 "${n.type}" — 이 서버에 없는 노드입니다(다른 버전에서 만든 파일일 수 `
            + "있습니다). 원본 설정은 보존되고, 내보내면 그대로 다시 저장됩니다.",
        extraInputs: [...(extraIn.get(n.id) ?? [])],
        extraOutputs: [...(extraOut.get(n.id) ?? [])],
        ...(said ? { said } : {}),
        ...(n.size ? { slotH: slotHeight(n.type, n.size.slot_h) } : {}),
      },
    };
  });
  const edges: Edge[] = doc.edges.map((e) => ({
    id: e.id,
    source: e.source,
    sourceHandle: e.source_port,
    target: e.target,
    targetHandle: e.target_port,
    ...(e.waypoints?.length ? { data: { waypoints: e.waypoints.map((p) => ({ x: p.x, y: p.y })) } } : {}),
  }));
  return { nodes, edges };
}

/** React Flow → 문서. 실행 결과는 넣지 않는다(파라미터·위치만). */
export function toDoc(nodes: PgNode[], edges: Edge[], meta?: GraphDoc["meta"], groups?: GraphGroup[], branches?: GraphBranch[],
                      pinned?: string[], folded?: string[]): GraphDoc {
  const ids = new Set(nodes.map((n) => n.id));
  const live = pruneBranches(branches ?? [], ids);
  return {
    format: GRAPH_FORMAT,
    version: GRAPH_VERSION,
    ...(meta ? { meta } : {}),
    ...(groups?.length ? { groups: groups.map((g) => ({ ...g, members: [...g.members] })) } : {}),
    ...(live.length ? { branches: live } : {}),
    ...(pinned?.some((id) => ids.has(id)) ? { pinned: pinned.filter((id) => ids.has(id)) } : {}),
    ...(folded?.some((id) => ids.has(id)) ? { folded: folded.filter((id) => ids.has(id)) } : {}),
    nodes: nodes.map((n) => ({
      id: n.id,
      type: n.data.kind,
      params: { ...n.data.params },
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) },
      ...(n.data.said && Object.keys(n.data.said).length ? { said: { ...n.data.said } } : {}),
      ...(slotHeight(n.data.kind, n.data.slotH) > slotBase(n.data.kind) ? { size: { slot_h: slotHeight(n.data.kind, n.data.slotH) } } : {}),
    })),
    edges: edges.map((e) => {
      const wp = viaOf(e);
      return {
        id: e.id,
        source: e.source,
        source_port: e.sourceHandle ?? "",
        target: e.target,
        target_port: e.targetHandle ?? "",
        ...(wp.length ? { waypoints: wp.map((p) => ({ x: Math.round(p.x), y: Math.round(p.y) })) } : {}),
      };
    }),
  };
}

/** 선의 경유점(CF4c) — 화면 선(`Edge.data.waypoints`)에 둔다. 없으면 빈 목록. */
export function viaOf(e: { data?: unknown }): { x: number; y: number }[] {
  const wp = (e.data as { waypoints?: { x: number; y: number }[] } | undefined)?.waypoints;
  return Array.isArray(wp) ? wp : [];
}

/** 지워진 노드를 가리키는 갈래 짝을 뺀다 — 뿌리가 사라진 갈래는 통째로 뺀다. */
export function pruneBranches(branches: GraphBranch[], ids: Set<string>): GraphBranch[] {
  return branches.map((b) => ({ ...b, map: Object.fromEntries(Object.entries(b.map).filter(([c, o]) => ids.has(c) && ids.has(o))) }))
    .filter((b) => b.root in b.map);
}

/** 사람이 읽는 파일 이름 — `이름.portfolio-graph.json`. */
export function exportFileName(name: string | undefined, now = new Date()): string {
  const base = (name || `portfolio-${now.toISOString().slice(0, 10)}`)
    .replace(/[\\/:*?"<>|\s]+/g, "-").replace(/^-+|-+$/g, "") || "portfolio";
  return `${base}.portfolio-graph.json`;
}
