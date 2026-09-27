"use client";
/**
 * 묶음 상자 · 전략 상자 (BL1 → BM C2 · KNIME 메타노드 · ComfyUI 서브그래프 · Dataiku 구역)
 * ==========================================================================
 * 계산에는 끼지 않는 **화면 정보**다 — 서버로 가는 그래프에는 없고 파일의 `groups` 에만 남는다. 상자를 끌면 안의
 * 노드가 함께 움직이고, 접으면 안의 노드를 숨긴다. 접어도 계산은 그대로다.
 *
 * BM C2 — **전략 상자**(`kind: "strategy"`)는 한 전략의 흐름이다: 띠 색 · 결과 요약(완료/막힘/실패 · 계산 시간 합) · 전략이 낸
 * 비중의 헤드라인. ★접으면 포트 달린 노드★(ComfyUI) — 경계를 넘는 선은 상자 가장자리의 대리 포트로 이어 그린다(실제 링크는
 * 그대로). 두 번 누르면(또는 ‘들어가기’) 그 전략만 밝히고 나머지는 흐린다. 상자는 ‘내 블록’으로 저장할 수 있다.
 */
import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { BookmarkPlus, ChevronDown, Download, LogIn, Ungroup } from "lucide-react";
import { fmtElapsed, type GraphBlock } from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "./store";

export const PG_GROUP_TYPE = "pgGroup";

export interface ProxyPort { id: string; label: string; color: string }

export interface GroupFrameData {
  groupId: string; label: string; collapsed: boolean; members: string[]; width: number; height: number;
  kind: "group" | "strategy"; color: number;
  /** 접혔을 때 경계를 넘는 선의 대리 포트 — 들어오는 것(왼쪽)·나가는 것(오른쪽). */
  proxyIn: ProxyPort[]; proxyOut: ProxyPort[];
  output: string | null;
}

/** 블록 파일 받기 — `이름.pgblock.json`. */
export function downloadBlock(b: GraphBlock) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(b, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${b.label.replace(/[\\/:*?"<>|\s]+/g, "_") || "block"}.pgblock.json`;
  document.body.appendChild(a);             // 문서에 붙어 있어야 파일 이름(download)이 지켜진다(내보내기와 같은 방식)
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

const PROXY_TOP = 58;
const PROXY_GAP = 22;

function GroupFrameImpl({ data }: NodeProps<GroupFrameData>) {
  const results = usePortfolioGraph((s) => (s.reportStale ? null : s.report?.nodes ?? null));
  const toggle = usePortfolioGraph((s) => s.toggleGroup);
  const rename = usePortfolioGraph((s) => s.renameGroup);
  const ungroup = usePortfolioGraph((s) => s.ungroup);
  const dive = usePortfolioGraph((s) => s.setFocusGroup);
  const saveBlock = usePortfolioGraph((s) => s.saveBlock);
  const strategy = data.kind === "strategy";
  const ok = data.members.filter((m) => results?.[m]?.status === "ok").length;
  const blocked = data.members.filter((m) => results?.[m]?.status === "blocked").length;
  const failed = data.members.filter((m) => results?.[m]?.status === "failed").length;
  const times = data.members.map((m) => results?.[m]?.elapsed_ms).filter((x): x is number => typeof x === "number");
  const total = times.reduce((a, b) => a + b, 0);
  const out = data.output ? results?.[data.output] : undefined;
  const head = out?.status === "ok" ? out.explain?.headline : null;
  const noun = strategy ? "전략" : "묶음";
  const minH = PROXY_TOP + Math.max(data.proxyIn.length, data.proxyOut.length) * PROXY_GAP + 10;
  return (
    <div className={`pg-group${strategy ? ` pg-group--strategy pg-band-${data.color}` : ""}${data.collapsed ? " pg-group--collapsed" : ""}`}
         data-group-id={data.groupId} data-kind={data.kind}
         style={{ width: data.collapsed ? 280 : data.width, height: data.collapsed ? undefined : data.height,
                  minHeight: data.collapsed ? minH : undefined }}>
      <div className="pg-group-head">
        <button type="button" className="pg-group-toggle nodrag" aria-expanded={!data.collapsed}
                aria-label={data.collapsed ? `${noun} 펼치기` : `${noun} 접기`} onClick={() => toggle(data.groupId)}>
          <ChevronDown size={14} aria-hidden="true" className={data.collapsed ? "pg-palette-chev--closed" : undefined} />
        </button>
        <input className="pg-group-label nodrag" value={data.label} aria-label={`${noun} 이름`}
               onChange={(e) => rename(data.groupId, e.target.value)} />
        <span className="pg-group-sum">
          노드 {data.members.length}개{results
            ? ` · 완료 ${ok}${blocked ? ` · 막힘 ${blocked}` : ""}${failed ? ` · 실패 ${failed}` : ""}` : ""}
          {results && times.length > 0 && <span className="pg-group-time"> · 계산 {fmtElapsed(total)}</span>}
        </span>
        <span className="pg-group-tools">
          <button type="button" className="pg-group-x pg-group-dive nodrag" aria-label={`${noun} 안으로 들어가기`}
                  title="이 상자만 밝혀 봐요 (두 번 눌러도 돼요)" onClick={() => dive(data.groupId)}>
            <LogIn size={14} aria-hidden="true" />
          </button>
          <button type="button" className="pg-group-x pg-group-save nodrag" aria-label="내 블록으로 저장"
                  title="이 상자를 내 블록에 넣어요 (이 브라우저)" onClick={() => saveBlock(data.groupId)}>
            <BookmarkPlus size={14} aria-hidden="true" />
          </button>
          <button type="button" className="pg-group-x pg-group-file nodrag" aria-label="블록 파일로 받기"
                  title="이 상자를 .pgblock.json 파일로 받아요"
                  onClick={() => { const b = saveBlock(data.groupId); if (b) downloadBlock(b); }}>
            <Download size={14} aria-hidden="true" />
          </button>
          <button type="button" className="pg-group-x nodrag" aria-label={`${noun} 풀기`} title={`${noun} 풀기 (노드는 남아요)`}
                  onClick={() => ungroup(data.groupId)}>
            <Ungroup size={14} aria-hidden="true" />
          </button>
        </span>
      </div>
      {strategy && head && head.value !== null && (
        <div className="pg-group-out" title={head.label}>
          <b>{Number.isInteger(Number(head.value)) ? Number(head.value) : Number(head.value).toFixed(1)}<small>{head.unit}</small></b>
          <span>{head.label}</span>
        </div>
      )}
      {strategy && data.output === null && <div className="pg-group-warn">비중을 내는 노드가 없어 포트폴리오에 합칠 수 없어요.</div>}
      {data.collapsed && data.proxyIn.map((p, i) => (
        <div key={p.id} className="pg-proxy pg-proxy--in" style={{ top: PROXY_TOP + i * PROXY_GAP }} title={p.label}>
          <Handle type="target" position={Position.Left} id={p.id} className="pg-handle" isConnectable={false}
                  style={{ background: p.color, borderColor: "var(--pg-paper)" }} />
          <span>{p.label}</span>
        </div>
      ))}
      {data.collapsed && data.proxyOut.map((p, i) => (
        <div key={p.id} className="pg-proxy pg-proxy--out" style={{ top: PROXY_TOP + i * PROXY_GAP }} title={p.label}>
          <span>{p.label}</span>
          <Handle type="source" position={Position.Right} id={p.id} className="pg-handle" isConnectable={false}
                  style={{ background: p.color, borderColor: "var(--pg-paper)" }} />
        </div>
      ))}
    </div>
  );
}

export const GroupFrame = memo(GroupFrameImpl);

/** 단계 레인(BM C2) — 전략 지도 정리가 그리는 세로 띠. 끌 수 없고 고를 수 없는 배경이다. */
export const PG_LANE_TYPE = "pgLane";
export interface LaneData { label: string; width: number; height: number; portfolio?: boolean }

function LaneImpl({ data }: NodeProps<LaneData>) {
  return (
    <div className={`pg-lane${data.portfolio ? " pg-lane--portfolio" : ""}`} style={{ width: data.width, height: data.height }}
         aria-hidden="true">
      <span className="pg-lane-label">{data.label}</span>
    </div>
  );
}

export const Lane = memo(LaneImpl);
