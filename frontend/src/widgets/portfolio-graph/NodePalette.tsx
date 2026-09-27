"use client";
/**
 * 노드 팔레트 — ★서버 카탈로그만 본다★ (BI3 → BJ2 → BK W6)
 * 퀀트 워크플로우 단계별(데이터 → 신호 → 생각 정하기 → 비중 정하기 → 확인하기 → 실행·기록)로
 * 쉬운 이름과 한 줄 설명을 보여 준다. 노드가 서른 개 가까이 되어 단계마다 **접고 펼 수 있고**(개수 표시),
 * 검색은 쉬운 이름·설명·종류 이름에 더해 **예전 화면 이름**(STRESS·Stress·06 …)으로도 찾는다 —
 * `LEGACY_SCREENS`(BL4 — 마법사는 지웠고 옛 주소는 캔버스로 온다). 맨 아래 "빠른 시작" 은 템플릿.
 * 클릭하면 캔버스 가운데에, 끌면 놓은 자리에 놓인다.
 */
import { useEffect, useState } from "react";
import { ChevronDown, Download, Search, Trash2, Upload } from "lucide-react";
import { parseBlock, TEMPLATES, type NodeCatalogEntry, type WorkflowStage } from "@/entities/portfolio-graph";
import { downloadBlock } from "./GroupFrame";
import { usePortfolioGraph } from "./store";
import { legacyScreensOf } from "@/entities/portfolio-graph/legacyScreens";
import { STAGE_VAR } from "./GraphNode";

export const PALETTE_MIME = "application/x-pg-node";

export function NodePalette({ catalog, stages, initialQuery = "", onAdd, onTemplate, onGoal }: {
  catalog: NodeCatalogEntry[];
  stages: WorkflowStage[];
  /** 처음 검색어 — 옛 주소로 온 사람에게 그 화면의 일을 하는 노드를 먼저 보인다(BL4). */
  initialQuery?: string;
  onAdd: (kind: string) => void;
  onTemplate: (key: string) => void;
  /** 목표로 시작(BM C4) — 빠른 시작 맨 위. */
  onGoal?: () => void;
}) {
  /** 노드 종류 → 그 일을 하던 예전 화면(검색·툴팁용). */
  const legacyOf = (kind: string) => legacyScreensOf(kind);
  const [q, setQ] = useState(initialQuery);
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const needle = q.trim().toLowerCase();
  const match = (c: NodeCatalogEntry) => !needle || [c.plain_label, c.plain_description, c.type, c.label,
    ...legacyOf(c.type).flatMap((a) => [a.title, ...a.aliases])]
    .some((s) => s?.toLowerCase().includes(needle));
  const known = new Set(stages.map((s) => s.key));
  const groups = [...stages, ...[...new Set(catalog.map((c) => c.stage))]
    .filter((k) => !known.has(k)).map((k) => ({ key: k, label: k || "기타" }))];

  return (
    <aside className="pg-palette" aria-label="노드 추가">
      <label className="pg-search">
        <Search size={14} aria-hidden="true" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="무엇을 추가할까요?" aria-label="노드 찾기" />
      </label>
      {groups.map((st) => {
        const all = catalog.filter((c) => c.stage === st.key);
        const items = all.filter(match);
        if (needle && !items.length) return null;
        const open = !!needle || !closed[st.key];                 // 찾는 중에는 늘 펼친다
        const body = `pg-palette-body-${st.key}`;
        return (
          <section key={st.key} className="pg-palette-group" data-stage={st.key}>
            <h4 className="pg-palette-cat">
              <button type="button" className="pg-palette-toggle" aria-expanded={open} aria-controls={body}
                      onClick={() => setClosed((c) => ({ ...c, [st.key]: open }))}>
                <i style={{ background: STAGE_VAR[st.key] ?? "var(--pg-mute)" }} />
                <span className="pg-palette-cat-name">{st.label}</span>
                <span className="pg-palette-count">{needle ? `${items.length}/${all.length}` : all.length}</span>
                <ChevronDown size={14} aria-hidden="true" className={`pg-palette-chev${open ? "" : " pg-palette-chev--closed"}`} />
              </button>
            </h4>
            <div id={body} hidden={!open}>
              {all.length === 0 && <p className="pg-palette-soon">{st.label} 노드는 곧 추가돼요.</p>}
              {items.map((c) => (
                <button key={c.type} type="button" className="pg-palette-item" data-kind={c.type} draggable
                        title={`${c.label} (${c.type})${legacyOf(c.type).length ? ` · 예전 화면 ${legacyOf(c.type).map((a) => a.aliases[1] ?? a.title).join(", ")}` : ""}`}
                        onDragStart={(e) => { e.dataTransfer.setData(PALETTE_MIME, c.type); e.dataTransfer.effectAllowed = "move"; }}
                        onClick={() => onAdd(c.type)}>
                  <b>{c.plain_label}</b>
                  <span>{c.plain_description}</span>
                </button>
              ))}
            </div>
          </section>
        );
      })}
      {needle && !catalog.some(match) && <p className="pg-palette-soon">‘{q}’에 맞는 노드가 없어요.</p>}
      <MyBlocks />
      <section className="pg-quickstart" aria-label="빠른 시작">
        <h4 className="pg-quickstart-h">빠른 시작</h4>
        {onGoal && (
          <button type="button" className="pg-goal-entry" onClick={onGoal}>
            <b>목표로 시작하기</b>
            <span>무엇을 하려는지 · 종목 · 기간을 고르면 흐름을 만들어 바로 계산해요.</span>
          </button>
        )}
        {TEMPLATES.map((t) => (
          <button key={t.key} type="button" className="pg-template" data-template={t.key} onClick={() => onTemplate(t.key)}>
            <b>{t.name}</b>
            <span>{t.description}</span>
          </button>
        ))}
      </section>
    </aside>
  );
}

/**
 * 내 블록 (BM C2 · ComfyUI 블루프린트) — 상자를 저장해 두고 다시 넣는다. ★이 브라우저에만★ 있다(편의 — 신뢰 저장은 파일).
 * 저장소를 못 쓰면 "없음" 이 아니라 "저장할 수 없음" 이라 말하고, 파일 불러오기는 그대로 된다.
 */
function MyBlocks() {
  const blocks = usePortfolioGraph((s) => s.blocks);
  const available = usePortfolioGraph((s) => s.blocksAvailable);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => { usePortfolioGraph.getState().loadBlocks(); }, []);
  const insert = (i: number) => {
    const st = usePortfolioGraph.getState();
    st.setNote(st.insertBlock(st.blocks[i]));
  };
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    const r = parseBlock(await f.text());
    if (!r.block) { setProblem(`「${f.name}」을 넣지 않았어요 — ${r.problem} 캔버스는 그대로예요.`); return; }
    setProblem(null);
    const st = usePortfolioGraph.getState();
    st.setNote(st.insertBlock(r.block));
  };
  return (
    <section className="pg-blocks" aria-label="내 블록">
      <h4 className="pg-blocks-h">내 블록 <span className="pg-blocks-where">이 브라우저에만</span></h4>
      {!available && <p className="pg-blocks-note">이 브라우저에 블록을 저장할 수 없어요 — 상자의 ‘파일로 받기’를 쓰고, 파일로 불러와요.</p>}
      {available && blocks.length === 0 && <p className="pg-blocks-note">아직 없어요. 상자 머리의 책갈피 버튼으로 전략이나 묶음을 넣어 두세요.</p>}
      {blocks.map((b, i) => (
        <div key={`${b.label}-${i}`} className="pg-block" data-block={b.label}>
          <button type="button" className="pg-block-add" onClick={() => insert(i)}
                  title={b.kind === "strategy" ? "새 전략 띠로 넣고 포트폴리오에 이어요" : "묶음으로 넣어요"}>
            <b>{b.label}</b>
            <span>{b.kind === "strategy" ? "전략" : "묶음"} · 노드 {b.nodes.length}개</span>
          </button>
          <button type="button" className="pg-block-x" aria-label={`${b.label} 파일로 받기`} onClick={() => downloadBlock(b)}>
            <Download size={13} aria-hidden="true" />
          </button>
          <button type="button" className="pg-block-x" aria-label={`${b.label} 지우기`}
                  onClick={() => usePortfolioGraph.getState().removeBlock(i)}>
            <Trash2 size={13} aria-hidden="true" />
          </button>
        </div>
      ))}
      <label className="pg-block-import">
        <Upload size={13} aria-hidden="true" /> 블록 파일 불러오기
        <input type="file" accept=".json,application/json" className="pg-block-input"
               onChange={(e) => { void onFile(e.target.files?.[0]); e.target.value = ""; }} />
      </label>
      {problem && <p className="pg-blocks-note pg-blocks-note--err" role="alert">{problem}</p>}
    </section>
  );
}
