"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// ResearchIndex — 00 OVERVIEW 를 "연구 색인" 으로 (UI/UX 현대화 P4)
// ─────────────────────────────────────────────────────────────────────────────
// 순서가 곧 설계다. 대시보드는 수치를 먼저 보여주지만 리서치 색인은 **신원을 먼저** 보여준다:
//   ① 무엇을 연구 중인가 (스터디·런 신원)
//   ② 어떤 맥락에서 보고 있는가 (유니버스·스냅샷·룰셋·팩·낡음)
//   ③ 지금 할 일 하나
//   ④ 최근 런
//   ⑤ 최근 스터디 — **브라우저에만 있다고 표시**
//
// ★없는 것을 0 으로 적지 않는다★
// 런이 없으면 "0건" 이 아니라 "아직 기록된 런이 없습니다" 라고 쓴다. 0 은 측정 결과이고
// 없음은 측정 이전이다. 리서치 도구에서 이 둘을 같은 글자로 적으면 신뢰도를 과장한다.
//
// ★딥링크를 지어내지 않는다★ (v2.1 §4.2)
// 서버는 run_id 로 단건 조회를 제공하지만(`GET /api/v1/research-runs/{id}`),
// **그 런을 여는 URL 은 존재하지 않는다**. 저널 페이지에는 쿼리 파라미터가 없다.
// 그래서 행마다 링크를 달아 "여기를 누르면 이 런이 열린다" 고 말하지 않는다 —
// 목록으로 가는 링크 하나만 둔다. 없는 기능을 있는 것처럼 보이게 하는 것이
// 이 프로젝트가 가장 경계하는 종류의 거짓말이다. (D6 승인 시 ?run= 으로 바뀐다.)
// ═══════════════════════════════════════════════════════════════════════════════

import React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { researchApi } from "@/entities/research/api";
import { listStudies, type AllocationStudy } from "@/entities/allocation/storage";
import { allocationApi } from "@/entities/allocation/api";
import { AsyncState, type AsyncStatus } from "@/shared/ui/States";
import { EvidenceBadge } from "@/shared/ui/evidence";
import { useAllocation } from "./AllocationProvider";
import { useResearchRegime } from "./useResearchRegime";
import { nextAction } from "./nextAction";

const ts = (sec: number) => new Date(sec * 1000).toISOString().slice(0, 16).replace("T", " ");

export function ResearchIndex() {
  const router = useRouter();
  const rg = useResearchRegime();
  const {
    activeStudy, activeRunId, attachedSnapshotId, holdings, timingCfg, activeRuleSet,
    scenarioPackId, isResultStale, result, stressQ, stageComplete, studiesVersion,
  } = useAllocation();

  const runsQ = useQuery({
    queryKey: ["research-runs", "index"],
    queryFn: () => researchApi.list(undefined, 8),
    staleTime: 30_000,
  });

  // 스터디는 이 브라우저에만 있다 — 서버에 없다는 사실을 화면에 적는다.
  const [studies, setStudies] = React.useState<AllocationStudy[]>([]);
  React.useEffect(() => { setStudies(listStudies()); }, [studiesVersion]);

  const scenCatQ = useQuery({
    queryKey: ["allocation", "stress-scenarios"],
    queryFn: () => allocationApi.stressScenarios(),
    staleTime: Infinity,
  });
  const activePack = (scenCatQ.data?.groups ?? [])
    .flatMap((g) => g.items).find((i) => i.pack_id === scenarioPackId) ?? null;

  const na = nextAction({
    hasStudy: !!activeStudy,
    holdingsCount: holdings.length,
    hasSnapshot: !!attachedSnapshotId,
    hasRuleSet: !!activeRuleSet,
    hasResult: !!result,
    isResultStale,
    hasStressValidation: !!stressQ.data?.available,
    hasJournalEntry: stageComplete["/allocation/journal"],
  });

  const runs = runsQ.data?.runs ?? [];
  const runsStatus: AsyncStatus =
    runsQ.isLoading ? { kind: "loading", label: "런 목록을 불러오는 중" }
    : runsQ.isError ? { kind: "unavailable", reason: "런 저장소를 조회하지 못했습니다(DB 미가용일 수 있습니다). 런이 없다는 뜻은 아닙니다." }
    : runs.length === 0 ? { kind: "empty", label: "아직 기록된 런이 없습니다", reason: "최적화 후 '이 결정을 런으로 기록' 을 누르면 재현 단위가 서버에 남습니다." }
    : { kind: "ready" };

  return (
    <section className="as-ri">
      {/* ① 신원 ─────────────────────────────────────────────────────────── */}
      <div className="as-ri-id">
        <div className="as-ri-id-main">
          <span className="as-ri-k">STUDY</span>
          {activeStudy
            ? <b className="as-ri-v">{activeStudy.name}</b>
            : <span className="as-ri-none">활성 스터디 없음 — 저널에 기록하면 이름이 붙습니다</span>}
        </div>
        <div className="as-ri-id-main">
          <span className="as-ri-k">RUN</span>
          {activeRunId
            ? <b className="as-ri-v num">{activeRunId}</b>
            : <span className="as-ri-none">활성 런 없음 — 결정을 기록하면 재현 좌표가 생깁니다</span>}
        </div>
      </div>

      {/* ② 맥락 ─────────────────────────────────────────────────────────── */}
      <div className="as-ri-ctx">
        <span className="as-ri-c"><em>유니버스</em><b className="num">{timingCfg.market.toUpperCase()} · {holdings.length}종목</b></span>
        <span className="as-ri-c"><em>국면 기준</em>
          <b className="num">{rg.source === "snapshot" ? "PINNED" : "LIVE"}{rg.asOf ? ` @${rg.asOf.slice(0, 10)}` : ""}</b></span>
        <span className="as-ri-c"><em>룰셋</em>
          <b className="num">{activeRuleSet
            ? `${activeRuleSet.id.replace(/^tr_/, "").slice(0, 10)}${activeRuleSet.version != null ? ` v${activeRuleSet.version}` : ""}`
            : "미저장"}</b></span>
        <span className="as-ri-c"><em>시나리오 팩</em>
          <b className="num">{activePack ? activePack.identity : "미선택"}</b></span>
        {isResultStale && result && (
          <EvidenceBadge kind="caution" reason="입력이 바뀐 뒤 재계산되지 않았습니다 — 아래 수치는 이전 입력의 결과입니다.">
            미반영 변경
          </EvidenceBadge>
        )}
      </div>

      {/* ③ 지금 할 일 하나 — P3.5 의 정책을 그대로 쓴다(두 곳이 다르게 말하면 안 된다) */}
      <div className="as-ri-next">
        <button className="as-ri-next-b" data-next={na.key} onClick={() => router.push(na.href)}>
          {na.label} →
        </button>
        <span className="as-ri-next-why">{na.why}</span>
      </div>

      {/* ④ 최근 런 ──────────────────────────────────────────────────────── */}
      <div className="as-ri-sec">
        <div className="as-ri-sec-h">
          <span>최근 런</span>
          {/* 행마다 딥링크를 달지 않는 이유는 파일 상단 주석에 있다. */}
          <Link href="/allocation/journal" className="as-ri-more">저널에서 전체 목록 보기 →</Link>
        </div>
        <AsyncState status={runsStatus}>
          <ul className="as-ri-runs">
            {runs.map((r) => (
              <li key={r.run_id} className={`as-ri-run${r.run_id === activeRunId ? " on" : ""}`}>
                <span className="as-ri-run-id num">{r.run_id}</span>
                <span className="as-ri-run-nm">{r.name || r.kind}</span>
                <span className="as-ri-run-t num">{ts(r.created_at)}</span>
                {r.snapshot?.coverage?.source === "mock" && (
                  <em className="as-ri-run-mock">합성</em>
                )}
              </li>
            ))}
          </ul>
        </AsyncState>
      </div>

      {/* ⑤ 최근 스터디 — 브라우저 로컬임을 반드시 적는다 ───────────────────── */}
      <div className="as-ri-sec">
        <div className="as-ri-sec-h">
          <span>최근 스터디</span>
          <EvidenceBadge kind="caution" reason="이 목록은 서버가 아니라 이 브라우저에만 있습니다. 다른 기기·시크릿 창에서는 보이지 않고, 저장소를 비우면 사라집니다.">
            브라우저 로컬
          </EvidenceBadge>
        </div>
        {studies.length === 0
          ? <div className="as-empty">아직 저장된 스터디가 없습니다 — 09 JOURNAL 에서 첫 기록을 남기세요.</div>
          : (
            <ul className="as-ri-studies">
              {studies.slice(0, 5).map((s) => (
                <li key={s.id} className="as-ri-study">
                  <span className="as-ri-study-nm">{s.name}</span>
                  <span className="num">{s.savedAt.slice(0, 16).replace("T", " ")}</span>
                  <span className="num">{Object.keys(s.holdings).length}종목</span>
                </li>
              ))}
            </ul>
          )}
      </div>
    </section>
  );
}
