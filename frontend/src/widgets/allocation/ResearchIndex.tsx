"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// ResearchIndex — 00 OVERVIEW 를 "연구 색인" 으로 (UI/UX 현대화 P4)
// ─────────────────────────────────────────────────────────────────────────────
// 순서가 곧 설계다. 대시보드는 수치를 먼저 보여주지만 리서치 색인은 **신원을 먼저** 보여준다:
//   ① 무엇을 연구 중인가 (스터디·런 신원)
//   ② 지금 할 일 하나
//   ③ 최근 런
//   ④ 최근 스터디 — **브라우저에만 있다고 표시**
//
// ★맥락(유니버스·스냅샷·룰셋·팩·낡음)은 여기서 다시 그리지 않는다★
// 처음에는 그렸다. 그런데 ContextStrip 이 layout 에서 **모든 AAS 스테이지에** 이미
// 렌더된다(app/allocation/layout.tsx::StageChrome) — 바로 이 블록 한 칸 위다.
// 같은 사실을 두 번 적으면 둘이 어긋나는 순간 어느 쪽이 맞는지 알 수 없고, 측정해 보니
// 그 중복이 First Load JS 를 12 kB 늘리고 있었다(233 → 245, ADR 001 한도 4 kB 초과).
// 지웠더니 기준선으로 돌아왔다.
//
// ★없는 것을 0 으로 적지 않는다★
// 런이 없으면 "0건" 이 아니라 "아직 기록된 런이 없습니다" 라고 쓴다. 0 은 측정 결과이고
// 없음은 측정 이전이다. 리서치 도구에서 이 둘을 같은 글자로 적으면 신뢰도를 과장한다.
//
// ★딥링크 — 이제 진짜로 있다★ (D6, v2.1 §4.2)
// 한동안 런 행은 클릭 불가였다. 서버는 `GET /api/v1/research-runs/{id}` 로 단건을 줬지만
// **그 런을 여는 URL 이 없었기** 때문이다(저널에 쿼리 파라미터가 없었다). 없는 기능을
// 있는 것처럼 보이게 하지 않으려고 링크를 달지 않았다.
// D6 에서 `/allocation/journal?run=<id>` 가 생겼고, 행은 그 주소로 링크된다 —
// 새로고침·공유에도 같은 런을 가리킨다. 목록에 없는 런이면 저널이 그 사실을 적는다.
// ═══════════════════════════════════════════════════════════════════════════════

import React from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useAllocation } from "./AllocationProvider";
import { nextAction } from "./nextAction";

// 목록부는 조회 계층을 들고 온다 — 첫 로드에서 떼어낸다(측정: 233 → 242 kB 였다).
const ResearchIndexLists = dynamic(() => import("./ResearchIndexLists"), { ssr: false });

export function ResearchIndex() {
  const router = useRouter();
  const {
    activeStudy, activeRunId, attachedSnapshotId, holdings, activeRuleSet,
    isResultStale, result, stressQ, stageComplete, studiesVersion,
  } = useAllocation();

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

  return (
    <section className="as-ri">
      {/* ① 신원 — 첫 화면에 즉시 있어야 하므로 정적으로 둔다. */}
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

      {/* ② 지금 할 일 하나 — P3.5 정책을 그대로 쓴다. */}
      <div className="as-ri-next">
        <button className="as-ri-next-b" data-next={na.key} onClick={() => router.push(na.href)}>
          {na.label} →
        </button>
        <span className="as-ri-next-why">{na.why}</span>
      </div>

      <ResearchIndexLists activeRunId={activeRunId} studiesVersion={studiesVersion} />
    </section>
  );
}
