"use client";
// Strategy Health Panel (Full Expansion P5) — 알파·슬리브 건강도.
//   등록부·검증 IC/ICIR에서 healthy/watch/de_risk/paused/retired 판정. 데이터 미연동
//   신호는 unmeasured(정직). de-risk/paused는 실행계획 반영 대상으로 강조.
import React from "react";
import { useQuery } from "@tanstack/react-query";
import { attributionApi, type HealthItem } from "@/entities/attribution/api";
import { ArchiveDrawer } from "@/shared/ui/ArchiveDrawer";

const STATUS_KO: Record<HealthItem["status"], string> = {
  healthy: "정상", watch: "관찰", de_risk: "비중축소", paused: "중단", retired: "은퇴",
};

export function StrategyHealthPanel() {
  const q = useQuery({ queryKey: ["allocation", "strategy-health"], queryFn: () => attributionApi.strategyHealth().catch(() => null) });
  const h = q.data;

  // 행 하나 — 본문과 서랍이 같은 것을 렌더한다(두 벌로 복사하지 않는다).
  const row = (it: HealthItem) => (
    <li key={it.alpha_id} className={`as-health-item ${it.status}`}>
      <span className={`as-health-dot ${it.status}`} />
      <span className="as-health-name">{it.name}</span>
      <span className="as-health-status num">{STATUS_KO[it.status]}</span>
      <span className="as-health-sig num">
        {(() => {
          const ic = it.signals.find((s) => s.key === "ic_icir");
          if (ic?.status === "unmeasured") return "IC 미검증";
          const v = ic?.value as { ic?: number; icir?: number } | undefined;
          return v ? `IC ${v.ic ?? "—"} · ICIR ${v.icir ?? "—"}` : "—";
        })()}
      </span>
    </li>
  );

  // 주의가 필요한 상태만 본문에. 판정 자체는 서버가 하고 여기서는 나누기만 한다.
  const ATTENTION: HealthItem["status"][] = ["de_risk", "paused", "watch"];
  const items = h?.items ?? [];
  const attention = items.filter((it) => ATTENTION.includes(it.status));
  const resting = items.filter((it) => !ATTENTION.includes(it.status));

  return (
    <section className="as-card">
      <div className="as-card-title">STRATEGY HEALTH <span className="as-note-inline">알파·슬리브 건강도</span></div>
      {!h || h.n === 0 ? (
        <div className="as-empty">등록된 알파 없음 — 02 ALPHA LAB에서 알파를 검증·등록하면 건강도가 표시됩니다.</div>
      ) : (
        <>
          <div className="as-health-counts">
            {(["healthy", "watch", "de_risk", "paused", "retired"] as const).map((s) => (
              h.counts[s] > 0 && <span key={s} className={`as-health-pill ${s}`}>{STATUS_KO[s]} {h.counts[s]}</span>
            ))}
          </div>
          {h.derisk_alphas.length > 0 && (
            <div className="as-health-derisk">
              ⚠ 비중축소/중단 대상 {h.derisk_alphas.length}건 — 실행계획에서 제외/축소 권고:
              {" "}{h.derisk_alphas.map((d) => d.name).join(", ")}
            </div>
          )}
          {/* ★15줄이 레일에 전부 펼쳐져 있었다 (A7)★ 주의가 필요한 것(비중축소·중단·
              관찰)을 먼저 보여 주고 나머지는 서랍으로. "정상"인 알파는 지금 볼 이유가
              없고, 그걸 스크롤하다 de-risk 대상을 놓치는 것이 실제 손해다. */}
          <ul className="as-health-list">{attention.map(row)}</ul>
          {resting.length > 0 && (
            <ArchiveDrawer
              className="as-health-arch"
              label={`정상 ${resting.length}개 보기`}
              title="STRATEGY HEALTH — 전체"
              hint={`${h.items.length}개 중 주의 ${attention.length} · 정상 ${resting.length}`}>
              <ul className="as-health-list">{h.items.map(row)}</ul>
            </ArchiveDrawer>
          )}
          <div className="as-note">{h.note}</div>
        </>
      )}
    </section>
  );
}
