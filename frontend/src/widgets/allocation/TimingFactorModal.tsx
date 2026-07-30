"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// TimingFactorModal — AAS TIMING 통합 팩터 창
//   기존 카나리(13612W·절대모멘텀·이동평균·지표)와 신규 팩터(평균절대모멘텀·가속·이격도·
//   돌파·오버나이트·Defense First·장단기금리차)를 한 창에서 관리. 저장 단위는 TimingRule
//   공통 스키마(백엔드 dataclass와 1:1).
//
// Phase 6b: 네 번째이자 마지막 모달을 CatalogueShell 로 올렸다 — 나머지 셋은 Phase 6 에서
// 이전했고, 이 창은 밑에 깔린 모델(TimingRuleSetV2)이 Phase 7 에서 안정된 뒤로 미뤄 뒀다.
// 이 파일에는 **타이밍 고유의 것만** 남는다: 대상 티커/시리즈, 파라미터, 통과 방향, 임계,
// defense_first 부호 경고, 그리고 **리밸런싱 주기 충돌 경고**(스펙 §8.1 요구 13).
// .tfm-* 클래스 계약은 셸이 그대로 유지한다.
//
// previewSlot(과거 미리보기 — §8.1 요구 4)은 **의도적으로 비워 둔다**: 팩터의 과거 시계열을
// 내려주는 엔진/엔드포인트가 아직 없다(`evaluate()` 는 현재값 스칼라 하나). 자리만 채워
// 그럴듯한 상태를 보여주는 것은 정직성 규칙 위반이라 6b-2 로 넘겼다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  allocationApi, frequencyLabel, frequencyVerdict, frequencyWarningText,
  type CanaryInput, type CanarySignalType, type TimingFactorMeta,
} from "@/entities/allocation";
import { CatalogueShell, type CatalogueItem } from "@/features/catalogue-shell/CatalogueShell";

const PARAM_LABEL: Record<string, string> = {
  months: "개월", days: "일", max_months: "최대 개월", ma_days: "이평 일수", k: "k 계수",
  series_id: "매크로 시리즈 id",
};

/** TimingRule 기본값과 같은 리밸런싱 주기 — 백엔드 dataclass 기본값이 month_end. */
const DEFAULT_REBALANCE = "month_end";

/** 팩터 메타 → 기본 카나리(=TimingRule 스펙의 시그널 부분) */
export function canaryFromFactor(f: TimingFactorMeta): CanaryInput {
  const p = { ...(f.params || {}) };
  const primary = Object.keys(p).find((k) => typeof p[k] === "number");
  return {
    kind: f.id === "indicator" ? "indicator" : "asset",
    id: f.id === "indicator" ? "VIXCLS" : "SPY",
    signal: f.id as CanarySignalType,
    lookback: primary ? Number(p[primary]) || 12 : 12,
    threshold: f.default_threshold,
    direction: f.default_direction,
    params: p,
    rebalance_or_holding_period: DEFAULT_REBALANCE,
  };
}

/** 도메인 항목 → 셸이 아는 최소 표면. 셸이 TimingFactorMeta 를 알 필요가 없다. */
function toCatalogueItem(f: TimingFactorMeta): CatalogueItem {
  return {
    id: f.id,
    label: f.label,
    description: f.desc,
    meta: f.provenance,
    kindBadge: f.existing ? undefined : "NEW",
    searchExtra: [f.provenance],
    // ★as_of 가 필요한 팩터는 이 창에서 추가할 수 없다★ 카나리 평가 경로에 시점을 넘길
    // 방법이 없어, 추가를 허용하면 값이 영원히 없는(=늘 위험-오프) 규칙이 조용히 생긴다.
    // 목록에서 숨기지 않고 **사유를 적어 보여준다** — 카탈로그에 있는 것을 안 보이게 하면
    // 사용자는 왜 없는지 알 수 없다.
    available: f.requires_as_of ? false : undefined,
    unavailableReason: f.requires_as_of
      ? "시점(as_of) 기준으로 평가하는 팩터라 카나리 규칙으로 추가할 수 없습니다 — 백테스트 경로에서 사용합니다."
      : undefined,
  };
}

export function TimingFactorModal({ open, onClose, onAdd }: {
  open: boolean;
  onClose: () => void;
  onAdd: (c: CanaryInput) => void;
}) {
  const catQ = useQuery({
    queryKey: ["allocation", "timing-factors"],
    queryFn: () => allocationApi.timingFactors(),
    staleTime: Infinity,
    enabled: open,
  });
  const [fam, setFam] = useState<string>("momentum");
  const [sel, setSel] = useState<TimingFactorMeta | null>(null);
  const [draft, setDraft] = useState<CanaryInput | null>(null);

  const groups = catQ.data?.groups ?? [];
  const flat = useMemo(() => groups.flatMap((g) => g.factors), [groups]);
  const famItems = useMemo(
    () => (groups.find((g) => g.family === fam)?.factors ?? []).map(toCatalogueItem),
    [groups, fam]);
  const allItems = useMemo(() => flat.map(toCatalogueItem), [flat]);

  useEffect(() => { if (!open) { setSel(null); setDraft(null); } }, [open]);

  const pick = (f: TimingFactorMeta) => { setSel(f); setDraft(canaryFromFactor(f)); };
  const upd = (patch: Partial<CanaryInput>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const updParam = (k: string, v: number) =>
    setDraft((d) => (d ? { ...d, params: { ...(d.params || {}), [k]: v }, lookback: v } : d));

  const rebalance = draft?.rebalance_or_holding_period || DEFAULT_REBALANCE;
  const verdict = frequencyVerdict(
    sel?.evaluation_frequency, rebalance, catQ.data?.frequency_ranks);
  const warning = frequencyWarningText(verdict);

  return (
    <CatalogueShell
      open={open} onClose={onClose}
      title="타이밍 팩터"
      subtitle="시그널을 골라 파라미터를 맞추세요"
      ariaLabel="타이밍 팩터 추가"
      searchPlaceholder="팩터 검색 — 이름·설명·출처"
      families={catQ.data?.families ?? []}
      family={fam} onFamilyChange={setFam}
      items={famItems} allItems={allItems}
      selectedId={sel?.id ?? null}
      onSelect={(ci) => { const f = flat.find((x) => x.id === ci.id); if (f) pick(f); }}
      loading={catQ.isLoading} error={catQ.isError}
      errorText="카탈로그를 불러오지 못했습니다."
      note={catQ.data?.note}
      applyLabel="이 팩터 추가 →"
      onApply={() => { if (draft && !sel?.requires_as_of) { onAdd(draft); onClose(); } }}
      applyDisabled={!draft || !!sel?.requires_as_of}
      frequencyWarningSlot={sel && draft ? (
        <div className="tfm-freq">
          <label className="as-tm-set">
            <span>리밸런싱 주기
              <em className="as-note-inline">
                팩터 갱신 주기 · {frequencyLabel(sel.evaluation_frequency ?? "")}
              </em>
            </span>
            <select className="tfm-freq-sel" value={rebalance}
              aria-label="리밸런싱 주기"
              onChange={(e) => upd({ rebalance_or_holding_period: e.target.value })}>
              {(catQ.data?.rebalance_options ?? []).map((o) => (
                <option key={o.id} value={o.id}>{o.label}</option>
              ))}
            </select>
          </label>
          {warning ? (
            <div className="tfm-freq-warn" role="status">{warning}</div>
          ) : (
            <div className="tfm-freq-ok">
              주기가 맞습니다 — 팩터 갱신마다 리밸런싱에 반영됩니다.
            </div>
          )}
        </div>
      ) : undefined}
    >
      {sel && draft && (
        <>
          <div className="tfm-sel-t">{sel.label}</div>
          <div className="tfm-sel-d">{sel.desc}</div>
          <label className="as-tm-set">
            <span>{sel.id === "indicator" ? "매크로 시리즈 id" : "대상 티커"}</span>
            <input className="as-tm-id" value={draft.id}
              onChange={(e) => upd({ id: e.target.value.toUpperCase() })} />
          </label>
          {Object.entries(sel.params || {})
            .filter(([, dflt]) => typeof dflt === "number")
            .map(([k, dflt]) => (
              <label key={k} className="as-tm-set">
                <span>{PARAM_LABEL[k] ?? k}</span>
                <input className="as-tm-num num" type="number" step={k === "k" ? 0.1 : 1}
                  value={draft.params?.[k] ?? dflt}
                  onChange={(e) => updParam(k, parseFloat(e.target.value) || 0)} />
              </label>
            ))}
          <label className="as-tm-set">
            <span>통과 방향</span>
            <select className="as-tm-sig" value={draft.direction}
              onChange={(e) => upd({ direction: e.target.value as "above" | "below" })}>
              <option value="above">임계 초과 시 통과</option>
              <option value="below">임계 미만 시 통과</option>
            </select>
          </label>
          <label className="as-tm-set">
            <span>임계값 <em className="as-note-inline">단위: {sel.unit}</em></span>
            <input className="as-tm-num num" type="number" step={0.1} value={draft.threshold}
              onChange={(e) => upd({ threshold: parseFloat(e.target.value) || 0 })} />
          </label>
          {sel.id === "defense_first" && (
            <div className="as-note" style={{ color: "var(--color-caution, #d97706)" }}>
              역발상 팩터 — 값이 <b>음수일 때 위험-온</b>입니다(방어자산이 약하면 위험선호).
            </div>
          )}
        </>
      )}
    </CatalogueShell>
  );
}
