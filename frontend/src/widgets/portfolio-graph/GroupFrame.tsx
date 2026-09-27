"use client";
/**
 * 묶음 상자 · 전략 상자 (BL1 → BM C2 · KNIME 메타노드 · ComfyUI 서브그래프 · Dataiku 구역)
 * ==========================================================================
 * 계산에는 끼지 않는 **화면 정보**다 — 서버로 가는 그래프에는 없고 파일의 `groups` 에만 남는다. 상자를 끌면 안의
 * 노드가 함께 움직이고, 접으면 안의 노드를 숨긴다. 접어도 계산은 그대로다.
 *
 * BM C2 — **전략 상자**(`kind: "strategy"`)는 한 전략의 흐름이다: 띠 색 · 결과 요약(완료/막힘/실패 · 계산 시간 합) · 전략이 낸
 * 비중의 헤드라인. 두 번 누르면(또는 ‘들어가기’) 그 전략만 밝히고 나머지는 흐린다. 상자는 ‘내 블록’으로 저장할 수 있다.
 *
 * BN N1 — ★전략 지도도 캔버스와 같은 노드와 선이다★(사용자 결정). 펼친 전략은 평소의 묶음 상자(띠 색 점선 + 머리 줄),
 * **접은 전략은 노드 카드 한 장** — 노드와 같은 모양·같은 포트 점으로, 경계를 넘는 선은 그 포트에서 이어진다(실제 링크는 그대로).
 * 카드의 큰 숫자는 이 전략의 **포트폴리오 몫** — 이은 포트폴리오 노드 결과(`view.strategies`)의 서버 값이고, 모르면 "—" 와 이유.
 */
import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { BookmarkPlus, ChevronDown, Download, GitBranch, LogIn, Play, Ungroup } from "lucide-react";
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
  /** 전략의 몫(%) — 이은 포트폴리오 노드 결과(`view.strategies`)의 서버 값. 계산 전·모르면 null(BN N1). */
  share?: number | null;
  /** 전략의 출력이 포트폴리오 노드에 이어졌나 — 몫을 모를 때 그 이유를 가른다. */
  linked?: boolean;
  /** "이 전략만 계산" — 캔버스가 채운다(부분 계산). */
  onRunStrategy?: (groupId: string) => void;
  /** 전략째 갈래 — 캔버스가 채운다. */
  onBranchStrategy?: (groupId: string) => void;
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
/** 접은 전략 카드의 포트 자리 — 노드 카드(GraphNode)와 같은 간격. */
const SNODE_PORT_TOP = 46;

/** 몫을 모를 때의 이유 — 계산 전 · 포트폴리오에 잇지 않음 · 이었는데 서버 값이 없음(지어내지 않는다). */
function shareWhy(computed: boolean, linked: boolean | undefined): string {
  if (!computed) return "계산하면 보여요";
  if (!linked) return "포트폴리오에 잇지 않았어요";
  return "몫을 모름 — 포트폴리오 노드를 확인하세요";
}
const known = (v: number | null | undefined): v is number => typeof v === "number" && Number.isFinite(v);

function GroupFrameImpl({ data }: NodeProps<GroupFrameData>) {
  const results = usePortfolioGraph((s) => (s.reportStale ? null : s.report?.nodes ?? null));
  const toggle = usePortfolioGraph((s) => s.toggleGroup);
  const rename = usePortfolioGraph((s) => s.renameGroup);
  const ungroup = usePortfolioGraph((s) => s.ungroup);
  const dive = usePortfolioGraph((s) => s.setFocusGroup);
  const saveBlock = usePortfolioGraph((s) => s.saveBlock);
  const running = usePortfolioGraph((s) => s.running);
  const strategy = data.kind === "strategy";
  const ok = data.members.filter((m) => results?.[m]?.status === "ok").length;
  const blocked = data.members.filter((m) => results?.[m]?.status === "blocked").length;
  const failed = data.members.filter((m) => results?.[m]?.status === "failed").length;
  const times = data.members.map((m) => results?.[m]?.elapsed_ms).filter((x): x is number => typeof x === "number");
  const total = times.reduce((a, b) => a + b, 0);
  const out = data.output ? results?.[data.output] : undefined;
  const head = out?.status === "ok" ? out.explain?.headline : null;
  const noun = strategy ? "전략" : "묶음";
  if (strategy && data.collapsed) {
    return <StrategyNode data={data} ok={ok} blocked={blocked} failed={failed} total={times.length ? total : null} computed={!!results} />;
  }
  const minH = PROXY_TOP + Math.max(data.proxyIn.length, data.proxyOut.length) * PROXY_GAP + 10;
  return (
    <div className={`pg-group${strategy ? ` pg-group--strategy pg-band-${data.color}` : ""}${data.collapsed ? " pg-group--collapsed" : ""}`}
         data-group-id={data.groupId} data-kind={data.kind}
         style={{ width: data.collapsed ? 280 : data.width, height: data.collapsed ? undefined : data.height,
                  minHeight: data.collapsed ? minH : undefined }}>
      <div className="pg-group-head">
        <button type="button" className="pg-group-toggle nodrag" aria-expanded={!data.collapsed}
                aria-label={data.collapsed ? `${noun} 펼치기` : `${noun} 접기`}
                title={strategy ? "접으면 노드 한 장이 돼요 — 계산은 그대로예요" : undefined} onClick={() => toggle(data.groupId)}>
          <ChevronDown size={14} aria-hidden="true" className={data.collapsed ? "pg-palette-chev--closed" : undefined} />
        </button>
        <input className="pg-group-label nodrag" value={data.label} aria-label={`${noun} 이름`}
               onChange={(e) => rename(data.groupId, e.target.value)} />
        {strategy && (
          <span className="pg-group-share" data-share={known(data.share) ? data.share : ""}
                title={known(data.share) ? "포트폴리오에서 이 전략이 차지하는 몫(서버 계산)" : shareWhy(!!results, data.linked)}>
            몫 <b>{known(data.share) ? `${data.share.toFixed(1)}%` : "—"}</b>
          </span>
        )}
        <span className="pg-group-sum">
          노드 {data.members.length}개{results
            ? ` · 완료 ${ok}${blocked ? ` · 막힘 ${blocked}` : ""}${failed ? ` · 실패 ${failed}` : ""}` : ""}
          {results && times.length > 0 && <span className="pg-group-time"> · 계산 {fmtElapsed(total)}</span>}
        </span>
        <span className="pg-group-tools">
          {strategy && (
            <button type="button" className="pg-group-run nodrag" disabled={running} onClick={() => data.onRunStrategy?.(data.groupId)}
                    title="이 전략의 노드만 계산해요 — 나머지는 이전 계산으로 남아요">
              <Play size={12} aria-hidden="true" /> 이 전략만 계산
            </button>
          )}
          <button type="button" className="pg-group-x pg-group-dive nodrag" aria-label={`${noun} 안으로 들어가기`}
                  title="이 상자만 밝혀 봐요 (두 번 눌러도 돼요)" onClick={() => dive(data.groupId)}>
            <LogIn size={14} aria-hidden="true" />
          </button>
          {strategy && (
            <button type="button" className="pg-group-x pg-group-branch nodrag" aria-label="전략째 갈래 만들기"
                    title="이 전략의 노드를 모두 복제해 설정만 바꿔 나란히 봐요" onClick={() => data.onBranchStrategy?.(data.groupId)}>
              <GitBranch size={14} aria-hidden="true" />
            </button>
          )}
          <button type="button" className="pg-group-x pg-group-save nodrag" aria-label="내 블록으로 저장"
                  title="이 상자를 내 블록에 넣어요 (이 브라우저)" onClick={() => saveBlock(data.groupId)}>
            <BookmarkPlus size={14} aria-hidden="true" />
          </button>
          <button type="button" className="pg-group-x pg-group-file nodrag" aria-label="블록 파일로 받기"
                  title="이 상자를 .pgblock.json 파일로 받아요"
                  onClick={() => { const b = saveBlock(data.groupId); if (b) downloadBlock(b); }}>
            <Download size={14} aria-hidden="true" />
          </button>
          <button type="button" className="pg-group-x pg-group-unwrap nodrag" aria-label={`${noun} 풀기`} title={`${noun} 풀기 (노드는 남아요)`}
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

/**
 * 접은 전략 = 노드 카드 한 장(BN N1). 노드 카드와 같은 층: 머리 줄(띠 색 표 · "전략 · 노드 n개" · 상태 점) → 이름 → 큰 숫자 하나(몫) →
 * 상태 한 줄 → 이 전략만 계산. 포트는 노드처럼 색 점이고 이름은 마우스를 올리면 보인다. 멀리서는 이름과 몫만.
 */
function StrategyNode({ data, ok, blocked, failed, total, computed }: {
  data: GroupFrameData; ok: number; blocked: number; failed: number; total: number | null; computed: boolean;
}) {
  const toggle = usePortfolioGraph((s) => s.toggleGroup);
  const rename = usePortfolioGraph((s) => s.renameGroup);
  const running = usePortfolioGraph((s) => s.running);
  const state = !computed ? "idle" : failed ? "failed" : blocked ? "blocked" : "ok";
  const share = known(data.share) ? data.share : null;
  const ports = Math.max(data.proxyIn.length, data.proxyOut.length);
  return (
    <div className={`pg-group pg-group--strategy pg-group--collapsed pg-snode pg-band-${data.color}`}
         data-group-id={data.groupId} data-kind="strategy" style={{ minHeight: SNODE_PORT_TOP + ports * PROXY_GAP + 8 }}>
      <button type="button" className="pg-group-toggle pg-snode-open nodrag" aria-expanded={false} aria-label="전략 펼치기"
              title="펼쳐서 안의 노드를 봐요" onClick={() => toggle(data.groupId)}>
        <ChevronDown size={15} aria-hidden="true" className="pg-palette-chev--closed" />
      </button>
      <div className="pg-node-k">
        <i className="pg-snode-mark" aria-hidden="true" />
        <span className="pg-node-plain">전략 · 노드 {data.members.length}개</span>
        <span className={`pg-node-dot pg-node-dot--${state}`} aria-hidden="true" />
      </div>
      <div className="pg-node-far" aria-hidden="true">
        <span className="pg-node-far-name">{data.label}</span>
        <span className={`pg-node-far-v pg-node-far-v--${share === null ? "idle" : "ok"}`}>
          {share === null ? "몫 —" : <>{share.toFixed(1)}<small>%</small></>}
        </span>
      </div>
      <input className="pg-group-label pg-snode-name nodrag" value={data.label} aria-label="전략 이름"
             onChange={(e) => rename(data.groupId, e.target.value)} />
      <p className="pg-snode-share" data-share={share ?? ""}>
        {share === null
          ? <><b>—</b><small>{shareWhy(computed, data.linked)}</small></>
          : <><b>{share.toFixed(1)}<i>%</i></b><small>포트폴리오 몫</small></>}
      </p>
      {computed && (
        <p className="pg-snode-status">
          <i className="pg-pip pg-pip--ok" />완료 {ok}
          {blocked > 0 && <> · <i className="pg-pip pg-pip--blocked" />막힘 {blocked}</>}
          {failed > 0 && <> · <i className="pg-pip pg-pip--failed" />실패 {failed}</>}
          {total !== null && <span className="pg-group-time"> · 계산 {fmtElapsed(total)}</span>}
        </p>
      )}
      {data.output === null && <p className="pg-group-warn">비중을 내는 노드가 없어 포트폴리오에 합칠 수 없어요.</p>}
      <button type="button" className="pg-group-run pg-snode-run nodrag" disabled={running} onClick={() => data.onRunStrategy?.(data.groupId)}
              title="이 전략의 노드만 계산해요 — 나머지는 이전 계산으로 남아요">
        <Play size={12} aria-hidden="true" /> 이 전략만 계산
      </button>
      {data.proxyIn.map((p, i) => (
        <div key={p.id} className="pg-proxy pg-proxy--in pg-port" style={{ top: SNODE_PORT_TOP + i * PROXY_GAP }} title={p.label}>
          <Handle type="target" position={Position.Left} id={p.id} className="pg-handle" isConnectable={false}
                  style={{ background: p.color, borderColor: "var(--pg-paper)" }} />
          <span className="pg-port-name">{p.label}</span>
        </div>
      ))}
      {data.proxyOut.map((p, i) => (
        <div key={p.id} className="pg-proxy pg-proxy--out pg-port" style={{ top: SNODE_PORT_TOP + i * PROXY_GAP }} title={p.label}>
          <span className="pg-port-name">{p.label}</span>
          <Handle type="source" position={Position.Right} id={p.id} className="pg-handle" isConnectable={false}
                  style={{ background: p.color, borderColor: "var(--pg-paper)" }} />
        </div>
      ))}
    </div>
  );
}
