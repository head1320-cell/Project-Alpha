"use client";
// 리서치 컨텍스트 스트립 — "지금 어떤 연구 안에 있고, 어떤 매크로 맥락 아래에서 보고 있는가".
//
// 스펙 §4 의 9개 요소를 **한 줄**에 담는다(대시보드가 아니다):
//   ① 활성 런/스터디 신원  ② 포트폴리오  ③ 시장·유니버스  ④ 기준시점(as-of)
//   ⑤ 데이터 상태          ⑥ 매크로 국면+신뢰도  ⑦ 룰셋·시나리오
//   ⑧ 마지막 계산 대비 미반영 변경  ⑨ 재현 식별자
//
// 국면 값은 useResearchRegime() 한 곳에서 온다 — **붙은 스냅샷이 이기고 라이브는 라벨된 폴백**.
// 어느 쪽을 보고 있는지 화면에 반드시 드러낸다(PINNED / LIVE). 고정된 줄 알았는데 오늘 값을
// 보고 있는 상황이 이 프로젝트에서 가장 위험한 침묵이다.
//
// 기존 .as-ctx* 클래스 계약은 유지하고(E2E 가 직접 선택) 새 수정자 클래스만 추가한다.
import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { REGIME_COLORS, zScoreColor } from "@/entities/macro/api";
import { analysisApi } from "@/entities/macro/analysisApi";
import { type MacroIndicator } from "@/entities/macro/analysisModel";
import { STATUS_LABEL, USAGE_LABEL, USAGE_REASON } from "@/entities/regime-snapshot/model";
import { useAllocation } from "./AllocationProvider";
import { useResearchRegime } from "./useResearchRegime";

const CANARY: { id: string; label: string }[] = [
  { id: "VIXCLS", label: "VIX" },
  { id: "DGS10", label: "US10Y" },
  { id: "BAMLH0A0HYM2", label: "HY SPD" },
  { id: "T10Y2Y", label: "10Y-2Y" },
];

function Spark({ values }: { values: number[] }) {
  const vals = values.filter((v) => Number.isFinite(v));
  if (vals.length < 3) return null;
  const w = 46; const h = 14;
  const min = Math.min(...vals); const max = Math.max(...vals);
  const range = max - min || 1;
  const pts = vals.map((v, i) =>
    `${((i / (vals.length - 1)) * w).toFixed(1)},${(h - 2 - ((v - min) / range) * (h - 4)).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="as-ctx-spark">
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth={1.1} opacity={0.55} />
    </svg>
  );
}

export function ContextStrip() {
  const rg = useResearchRegime();
  const {
    activeStudy, activeRunId, attachedSnapshotId, holdings, timingCfg,
    scenario, scenarios, isResultStale, result,
  } = useAllocation();

  const dashQ = useQuery({ queryKey: ["macro", "dashboard"], queryFn: () => analysisApi.macroDashboard().catch(() => null) });
  const byId = new Map<string, MacroIndicator>();
  (dashQ.data?.themes ?? []).forEach((t) => t.indicators.forEach((i) => byId.set(i.id, i)));

  // 스냅샷의 regime 은 서버가 준 자유 문자열이다 — 색 테이블에 없는 값이 올 수 있으므로
  // 캐스팅으로 밀어 넣지 않고 조회 실패를 정상 경로로 다룬다(색만 없고 라벨은 그대로 표시).
  const rc = (rg.regime && (REGIME_COLORS as Record<string, { fg: string; bg: string; border: string } | undefined>)[rg.regime]) || null;
  const confPct = rg.confidence != null ? Math.round(rg.confidence * 100) : null;
  const pinned = rg.source === "snapshot";

  // ⑦ 시나리오 — 선택된 항목의 label. "팩(pack)" 신원은 Phase 9(ScenarioPackV2) 소관이다.
  const scenLabel = scenarios.find((s) => s.id === scenario)?.label ?? null;
  // ⑦ 룰셋 — 저장된 rule set 신원을 프론트가 아직 들고 있지 않다(timingCfg 는 미저장 설정).
  //    그래서 "설정 요약"으로 정직하게 표기한다. 버전 있는 룰셋은 Phase 7(TimingRuleSetV2).
  const timingSummary = `카나리 ${timingCfg.canaries.length}${
    timingCfg.minBreadth ? `·k${timingCfg.minBreadth}` : ""}${
    timingCfg.overlay.type !== "none" ? `·${timingCfg.overlay.type}` : ""}`;
  // ⑤ 데이터 상태 — 스냅샷 상태가 있으면 그것, 없으면 결과의 mock 여부
  const resultMock = !!result && (result.coverage as { source?: string }).source === "mock";

  return (
    <div className="as-ctx">
      {/* ⑥ 매크로 국면 + 신뢰도 · ④ 기준시점 — PINNED/LIVE 를 반드시 밝힌다 */}
      <Link href={pinned ? "/allocation/macro" : "/macro"}
        className={`as-ctx-regime${pinned ? " pinned" : ""}`}
        title={pinned
          ? `고정된 스냅샷 기준 — as-of ${rg.asOf ?? "—"}\n${rg.researchUsage ? USAGE_REASON[rg.researchUsage] : ""}`
          : "라이브 국면(지금) — Macro Cockpit 열기"}
        style={rc ? { background: rc.bg, color: rc.fg, borderColor: rc.border } : undefined}>
        <em className="as-ctx-src">{pinned ? "PINNED" : "LIVE"}</em>
        {rg.regime
          ? <>{rg.regime}{confPct != null && <b className="num"> CONF {confPct}%</b>}</>
          : rg.isLoading ? "REGIME …" : "REGIME —"}
      </Link>

      {rg.asOf && <span className="as-ctx-asof num" title="이 국면 판정의 기준시점">@{rg.asOf.slice(0, 10)}</span>}

      {rg.recommendedMode && (
        <span className="as-ctx-mode num" data-mode={rg.recommendedMode}>{rg.recommendedMode}</span>
      )}
      {rg.stressScore != null && (
        <span className="as-ctx-stress num" title="Stress Index (0~100)">
          STRESS {Math.round(rg.stressScore)}
        </span>
      )}

      {/* ⑤ 데이터 상태 + 연구 사용등급 */}
      {rg.dataStatus && (
        <span className="as-ctx-status" title="스냅샷 구성 데이터의 출처/신선도">
          {STATUS_LABEL[rg.dataStatus]}
        </span>
      )}
      {rg.researchUsage && (
        <span className={`as-ctx-usage as-usage-${rg.researchUsage}`} title={USAGE_REASON[rg.researchUsage]}>
          {USAGE_LABEL[rg.researchUsage]}
        </span>
      )}
      {!rg.dataStatus && resultMock && (
        <span className="as-ctx-status as-ctx-mock" title="현재 결과는 합성(mock) 데이터 기준">합성(mock)</span>
      )}

      {/* ① 활성 런 / 스터디 신원 */}
      {activeStudy && (
        <span className="as-ctx-study" title={`저장된 스터디 — ${activeStudy.id}`}>
          <em>STUDY</em> {activeStudy.name}
        </span>
      )}
      {activeRunId && (
        <Link href="/allocation/journal" className="as-ctx-run num" title={`활성 ResearchRun — ${activeRunId}`}>
          <em>RUN</em> {activeRunId.replace(/^rr_/, "").slice(0, 12)}
        </Link>
      )}

      {/* ② 포트폴리오 · ③ 시장·유니버스 (sleeve 모델은 아직 없다 — market + 보유 수로 대용) */}
      <span className="as-ctx-univ num" title="시장 · 보유 종목 수 (sleeve 개념은 아직 모델링되지 않음)">
        {timingCfg.market.toUpperCase()} · {holdings.length}종목
      </span>

      {/* ⑦ 룰셋 · 시나리오 */}
      <span className="as-ctx-rules num" title="타이밍 설정 요약 (버전 있는 룰셋은 이후 단계)">
        {timingSummary}
      </span>
      {scenLabel && (
        <span className="as-ctx-scen" title="선택된 스트레스 시나리오">{scenLabel}</span>
      )}

      {/* ⑧ 마지막 계산 대비 미반영 변경 — isResultStale 을 그대로 노출(재계산하지 않는다) */}
      {isResultStale && (
        <span className="as-ctx-stale" title="입력이 바뀌었지만 아직 재계산되지 않았습니다">
          미반영 변경
        </span>
      )}

      {/* ⑨ 재현 식별자 */}
      {attachedSnapshotId && (
        <Link href="/allocation/macro" className="as-ctx-snap num"
          title={`데이터 스냅샷 ${attachedSnapshotId}\nmodel ${rg.modelVersion ?? "—"} · engine ${rg.engineVersion ?? "—"} · code ${rg.codeVersion ?? "—"}`}>
          <em>SNAP</em> {attachedSnapshotId.replace(/^rgs_/, "").slice(0, 12)}
        </Link>
      )}

      <span className="as-ctx-fill" />
      {CANARY.map(({ id, label }) => {
        const ind = byId.get(id);
        const color = ind ? zScoreColor(ind.z_score) : "var(--t-muted)";
        return (
          <span key={id} className="as-ctx-canary" style={{ color }}
            title={ind ? `${ind.name} · z ${ind.z_score?.toFixed(2) ?? "—"}` : `${label} — 데이터 없음`}>
            <em>{label}</em>
            <b className="num">{ind?.latest != null
              ? ind.latest.toFixed(Math.abs(ind.latest) >= 100 ? 0 : 2) : "—"}</b>
            {ind?.spark && <Spark values={ind.spark.slice(-24)} />}
          </span>
        );
      })}
    </div>
  );
}
