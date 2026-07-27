"use client";
// 0M MACRO PHASE — 매크로 국면 스냅샷을 리서치 컨텍스트로 고정.
//
// Macro 탭의 "Allocation Studio에서 열기" 가 스냅샷을 서버에 만들고 ?snapshot=<id> 로
// 넘어온다. 여기서는 **적용 전에 매핑을 미리 보여 주고** Apply/Dismiss 를 받는다.
// 스냅샷은 이미 영속화되어 있으므로 Dismiss 해도 잃는 것이 없다 — 생성과 적용은 별개 행위다.
//
// ★브라우저에 본문을 복사하지 않는다★ — Provider 는 ID 만 들고, 본문은 서버가 진실이고
// react-query 가 캐시한다. 그래야 새로고침 후에도 같은 ID 로 다시 읽어 재현이 성립한다.
import React, { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAllocation } from "@/widgets/allocation/AllocationProvider";
import { regimeSnapshotApi } from "@/entities/regime-snapshot/api";
import {
  dominantPhase, STATUS_LABEL, USAGE_LABEL, USAGE_REASON,
} from "@/entities/regime-snapshot/model";
import { LoadingState } from "@/shared/ui/States";

// useSearchParams() 는 정적 프리렌더를 CSR 로 바일아웃시키므로 Suspense 경계가 필요하다
// (Next 14: missing-suspense-with-csr-bailout). tsc 는 못 잡고 next build 가 잡는다.
export default function MacroPhaseStagePage() {
  return (
    <Suspense fallback={<LoadingState label="스냅샷 컨텍스트를 준비하는 중" />}>
      <MacroPhaseStage />
    </Suspense>
  );
}

function MacroPhaseStage() {
  const params = useSearchParams();
  const incoming = params.get("snapshot");
  const { attachedSnapshotId, attachSnapshot, detachSnapshot } = useAllocation();

  // 미리보기 대상: URL 로 막 넘어온 것 우선, 없으면 이미 붙어 있는 것.
  const targetId = incoming || attachedSnapshotId;
  const isPreview = !!incoming && incoming !== attachedSnapshotId;

  const snapQ = useQuery({
    queryKey: ["regime-snapshot", targetId],
    queryFn: () => (targetId ? regimeSnapshotApi.get(targetId) : Promise.resolve(null)),
    enabled: !!targetId,
  });
  const snap = snapQ.data ?? null;
  const phase = snap ? dominantPhase(snap.phase_probabilities) : null;

  return (
    <div className="as-ws2 as-ws-exp">
      <main className="as-center">
        <section className="as-card as-macro-snap">
          <div className="as-card-title">
            MACRO PHASE SNAPSHOT
            <span className="as-note-inline">국면 판정을 ID 로 고정 — 이후 단계가 이 스냅샷을 참조합니다</span>
          </div>

          {!targetId && (
            <div className="as-empty">
              연결된 스냅샷이 없습니다. Macro 탭에서 <b>Allocation Studio에서 열기</b>를 누르면
              현재 국면이 스냅샷으로 고정되어 여기로 넘어옵니다.
            </div>
          )}

          {targetId && snapQ.isLoading && <LoadingState label="스냅샷을 불러오는 중" />}

          {targetId && !snapQ.isLoading && !snap && (
            <div className="as-empty as-macro-missing">
              스냅샷 <code className="num">{targetId}</code> 을(를) 찾을 수 없습니다.
              삭제되었거나 다른 환경에서 만들어진 ID 일 수 있습니다.
            </div>
          )}

          {snap && (
            <>
              {/* ── 매핑 미리보기: 이 국면이 무엇을 의미하는지 ── */}
              <div className="as-macro-map">
                <div className="as-macro-row">
                  <span className="as-macro-k">국면</span>
                  <b className="as-macro-v">{phase ? `${phase.name}` : "—"}</b>
                  <span className="as-macro-sub num">
                    {phase ? `${(phase.p * 100).toFixed(0)}%` : ""}
                    {snap.confidence != null ? ` · 신뢰도 ${(snap.confidence * 100).toFixed(0)}%` : ""}
                  </span>
                </div>
                <div className="as-macro-row">
                  <span className="as-macro-k">성장 / 물가 축</span>
                  <b className="as-macro-v num">
                    {snap.growth_axis.toFixed(2)} / {snap.inflation_axis.toFixed(2)}
                  </b>
                  <span className="as-macro-sub">Z-Score</span>
                </div>
                <div className="as-macro-row">
                  <span className="as-macro-k">스트레스</span>
                  <b className="as-macro-v num">{snap.stress_score.toFixed(0)}</b>
                  <span className="as-macro-sub">0–100</span>
                </div>
                <div className="as-macro-row">
                  <span className="as-macro-k">기준시점 (as-of)</span>
                  <b className="as-macro-v num">{snap.as_of || "—"}</b>
                  <span className="as-macro-sub">이 시점에 알 수 있던 데이터만 사용</span>
                </div>
              </div>

              {snap.explanation && <p className="as-macro-expl">{snap.explanation}</p>}

              {/* ── 데이터 정직성 배지: 한계를 숨기지 않는다 ── */}
              <div className="as-macro-badges">
                <span className={`as-macro-badge as-usage-${snap.research_usage}`}
                  title={USAGE_REASON[snap.research_usage]}>
                  {USAGE_LABEL[snap.research_usage]}
                </span>
                <span className="as-macro-badge as-status" title="스냅샷 구성 데이터의 출처/신선도">
                  {STATUS_LABEL[snap.data_status]}
                </span>
                <span className="as-macro-badge as-obs num" title="스냅샷이 참조하는 관측치 수">
                  관측치 {snap.observations?.length ?? 0}
                </span>
              </div>

              {snap.research_usage === "forward_only" && (
                <div className="as-note as-macro-warn">
                  {USAGE_REASON.forward_only}
                </div>
              )}

              {/* ── 재현 식별자 ── */}
              <div className="as-macro-repro num">
                <span>ID <code>{snap.snapshot_id}</code></span>
                <span>model {snap.model_version}</span>
                <span>engine {snap.engine_version}</span>
                <span>code {snap.code_version}</span>
              </div>

              {/* ── 적용/해제 ── */}
              <div className="as-macro-actions">
                {isPreview ? (
                  <>
                    <button className="as-fb-apply as-macro-apply"
                      onClick={() => attachSnapshot(snap.snapshot_id)}>
                      리서치 컨텍스트로 적용
                    </button>
                    <span className="as-note-inline">
                      적용 전입니다 — 스냅샷은 이미 저장되어 있으므로 무시해도 사라지지 않습니다.
                    </span>
                  </>
                ) : (
                  <>
                    <span className="as-macro-attached">✓ 리서치 컨텍스트에 연결됨</span>
                    <button className="as-macro-detach" onClick={detachSnapshot}>연결 해제</button>
                  </>
                )}
              </div>
            </>
          )}
        </section>
      </main>

      <aside className="as-center">
        <section className="as-card">
          <div className="as-card-title">WHY A SNAPSHOT</div>
          <div className="as-note">
            국면을 라이브로 다시 조회하면 <b>항상 오늘의 국면</b>이 보입니다. 그러면 과거에 내린
            결정을 오늘의 분류로 채점하게 됩니다. 스냅샷은 판정 시점·모델 버전·관측치 신원을
            함께 굳혀 <b>그때의 판단</b>을 보존합니다.
          </div>
        </section>
        <section className="as-card">
          <div className="as-card-title">OVERLAY, NOT OVERRIDE</div>
          <div className="as-note">
            매크로 국면은 타이밍 규칙을 덮어쓰지 않습니다. 04 TIMING 에서 규칙만 / 매크로만 /
            둘 다를 비교할 수 있게 하는 것이 다음 단계 작업입니다.
          </div>
        </section>
      </aside>
    </div>
  );
}
