"use client";
/**
 * 묶음 상자 (BL1 · KNIME 메타노드 · ComfyUI 서브그래프에서 가져온 패턴)
 * ==========================================================================
 * 계산에는 끼지 않는 **화면 정보**다 — 서버로 가는 그래프에는 없고 파일의 `groups` 에만 남는다. 상자를 끌면 안의
 * 노드가 함께 움직이고, 접으면 안의 노드를 숨기고 한 줄 요약(노드 수 · 완료/실패 수)만 남긴다. 접어도 계산은 그대로다.
 */
import { memo } from "react";
import type { NodeProps } from "reactflow";
import { ChevronDown, Ungroup } from "lucide-react";
import { usePortfolioGraph } from "./store";

export const PG_GROUP_TYPE = "pgGroup";

export interface GroupFrameData { groupId: string; label: string; collapsed: boolean; members: string[]; width: number; height: number }

function GroupFrameImpl({ data }: NodeProps<GroupFrameData>) {
  const results = usePortfolioGraph((s) => (s.reportStale ? null : s.report?.nodes ?? null));
  const toggle = usePortfolioGraph((s) => s.toggleGroup);
  const rename = usePortfolioGraph((s) => s.renameGroup);
  const ungroup = usePortfolioGraph((s) => s.ungroup);
  const ok = data.members.filter((m) => results?.[m]?.status === "ok").length;
  const bad = data.members.filter((m) => results?.[m] && results[m].status !== "ok").length;
  return (
    <div className={`pg-group${data.collapsed ? " pg-group--collapsed" : ""}`} data-group-id={data.groupId}
         style={{ width: data.width, height: data.collapsed ? undefined : data.height }}>
      <div className="pg-group-head">
        <button type="button" className="pg-group-toggle nodrag" aria-expanded={!data.collapsed}
                aria-label={data.collapsed ? "묶음 펼치기" : "묶음 접기"} onClick={() => toggle(data.groupId)}>
          <ChevronDown size={14} aria-hidden="true" className={data.collapsed ? "pg-palette-chev--closed" : undefined} />
        </button>
        <input className="pg-group-label nodrag" value={data.label} aria-label="묶음 이름"
               onChange={(e) => rename(data.groupId, e.target.value)} />
        <span className="pg-group-sum">
          노드 {data.members.length}개{results ? ` · 완료 ${ok}${bad ? ` · 막힘·실패 ${bad}` : ""}` : ""}
        </span>
        <button type="button" className="pg-group-x nodrag" aria-label="묶음 풀기" title="묶음 풀기 (노드는 남아요)"
                onClick={() => ungroup(data.groupId)}>
          <Ungroup size={14} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

export const GroupFrame = memo(GroupFrameImpl);
