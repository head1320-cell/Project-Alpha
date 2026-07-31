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
import { allocationApi, MODEL_TYPE_SHORT } from "@/entities/allocation/api";
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
    scenario, scenarios, scenarioPackId, runPackHash, isResultStale, result, activeRuleSet,
  } = useAllocation();

  // 통합 시나리오 카탈로그 — 스트레스 화면·선택 창과 **같은 쿼리 키**라 캐시를 공유한다
  // (추가 요청 0). 여기서 필요한 것은 선택된 팩의 신원과 model_type 뿐이다.
  const scenCatQ = useQuery({
    queryKey: ["allocation", "stress-scenarios"],
    queryFn: () => allocationApi.stressScenarios(),
    staleTime: Infinity,
  });

  // ★박힌 버전이 아직 실재하는지 확인한다★
  // 확인하지 않으면 삭제된 버전 번호를 그대로 보여주게 되고, 사용자는 그 런이 재현됐다고 믿는다.
  const rvQ = useQuery({
    queryKey: ["allocation", "timing-rule-versions", activeRuleSet?.id],
    queryFn: () => allocationApi.timingRuleVersions(activeRuleSet!.id),
    enabled: !!activeRuleSet?.id,
    staleTime: 30_000,
  });
  // 확인이 끝나기 전에는 단정하지 않는다 — 로딩 중에 "미상"이라 적으면 잘못된 경보다.
  const versionResolved = activeRuleSet?.version != null && rvQ.isSuccess
    ? rvQ.data.versions.some((v) => v.version === activeRuleSet.version)
    : null;

  const dashQ = useQuery({ queryKey: ["macro", "dashboard"], queryFn: () => analysisApi.macroDashboard().catch(() => null) });
  const byId = new Map<string, MacroIndicator>();
  (dashQ.data?.themes ?? []).forEach((t) => t.indicators.forEach((i) => byId.set(i.id, i)));

  // 스냅샷의 regime 은 서버가 준 자유 문자열이다 — 색 테이블에 없는 값이 올 수 있으므로
  // 캐스팅으로 밀어 넣지 않고 조회 실패를 정상 경로로 다룬다(색만 없고 라벨은 그대로 표시).
  const rc = (rg.regime && (REGIME_COLORS as Record<string, { fg: string; bg: string; border: string } | undefined>)[rg.regime]) || null;
  const confPct = rg.confidence != null ? Math.round(rg.confidence * 100) : null;
  const pinned = rg.source === "snapshot";

  // ⑦ 시나리오 — **팩 신원**(Phase 9). 라벨만 적던 것을 `pack_id@hash` 까지 올린다.
  //    라벨은 계수가 바뀌어도 그대로라 재현 좌표가 되지 못한다 — 해시는 충격 정의를 따라간다.
  //    통합 카탈로그에서 찾지 못하면(레거시 id 등) 라벨로 물러서되 신원은 적지 않는다.
  const activePack = (scenCatQ.data?.groups ?? [])
    .flatMap((g) => g.items).find((i) => i.pack_id === scenarioPackId) ?? null;
  // ★두 해시가 모두 있을 때만 비교한다★ 한쪽이 없으면 "다르다" 가 아니라 "모른다" 이고,
  //   모르는 것을 경고로 표시하면 정상 상태가 계속 경고처럼 보인다.
  const packChanged = !!runPackHash && !!activePack?.content_hash
    && runPackHash !== activePack.content_hash;
  const scenLabel = activePack?.label
    ?? scenarios.find((s) => s.id === scenarioPackId)?.label
    ?? scenarios.find((s) => s.id === scenario)?.label ?? null;
  // ⑦ 룰셋 — 저장된 룰셋이 붙어 있으면 **신원(id v버전)**을, 없으면 미저장 설정 요약을 적는다.
  //    둘은 다른 것이다: 전자는 서버에 불변으로 남아 재현되고, 후자는 이 브라우저의 임시 상태다.
  //    같은 칸에 같은 모양으로 적으면 사용자는 저장되지 않은 설정을 재현 가능한 것으로 오해한다.
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
      {activeRuleSet ? (
        <span className="as-ctx-rules num"
          title={activeRuleSet.version == null
            ? `타이밍 룰셋 ${activeRuleSet.id} — 버전이 기록되지 않았습니다. 이 런이 어떤 룰로 계산됐는지 단정할 수 없습니다`
            : versionResolved === false
              ? `타이밍 룰셋 ${activeRuleSet.id} v${activeRuleSet.version} — 이 버전이 서버에 없습니다(삭제되었거나 저장에 실패). 현재 버전으로 대신 보여주지 않습니다`
              : `타이밍 룰셋 ${activeRuleSet.id} v${activeRuleSet.version} — 이 버전의 내용은 서버에 불변으로 보관됩니다`}>
          <em>RULES</em> {activeRuleSet.id.replace(/^tr_/, "").slice(0, 10)}
          {/* ★버전을 못 찾으면 현재 버전을 대신 보여주지 않는다★
              그러면 사용자는 재현됐다고 믿게 된다 — 모르면 모른다고 적는다. */}
          {activeRuleSet.version == null
            ? <span className="as-ctx-rules-na"> 버전 미기록</span>
            : versionResolved === false
              ? <span className="as-ctx-rules-na"> v{activeRuleSet.version} 확인 불가</span>
              : ` v${activeRuleSet.version}`}
        </span>
      ) : (
        <span className="as-ctx-rules num" title="저장되지 않은 타이밍 설정 요약 — 재현 좌표가 아닙니다">
          {timingSummary}
        </span>
      )}
      {scenLabel && (
        <span className="as-ctx-scen"
          title={activePack
            ? `시나리오 팩 ${activePack.identity}\n${activePack.model_type_label}\n분류: ${activePack.family_label}`
            : "선택된 스트레스 시나리오 — 통합 카탈로그에서 팩 신원을 찾지 못했습니다"}>
          {scenLabel}
          {/* ★역사인가 가정인가는 결과가 보이는 곳마다 적는다★ (스펙 §5) */}
          {activePack && (
            <em className={`as-model-type mt-${activePack.model_type}`}>
              {MODEL_TYPE_SHORT[activePack.model_type]}
            </em>
          )}
          {/* 신원을 못 찾으면 해시를 지어내지 않는다 — 라벨만 남는다. */}
          {activePack && <em className="as-ctx-scen-id num"> {activePack.content_hash}</em>}
          {/* ★런이 쓴 해시와 지금 해시가 다르면 그 사실을 적는다★ (Phase 10b)
              조용히 현재 팩을 보여주면 사용자는 그 런이 재현됐다고 믿는다 — 7c 가 룰셋
              버전에 대해 세운 규칙과 같다. 판단 근거는 두 해시뿐이므로 지어낼 것이 없다. */}
          {packChanged && (
            <em className="as-ctx-scen-drift"
              title={`이 런은 ${runPackHash} 로 계산됐지만 현재 팩은 ${activePack?.content_hash} 입니다 — 충격 정의가 바뀌었습니다`}>
              팩 변경됨
            </em>
          )}
        </span>
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
