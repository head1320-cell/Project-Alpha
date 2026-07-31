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
// Phase 6b-2: previewSlot 도 채웠다 — 룩어헤드 안전 롤링 평가가 백엔드에 생겼기 때문이다
// (`GET /timing-factors/{id}/history`, 각 점을 `as_of(m)` 안에서 평가). 임계·방향·티커를
// 바꾸면 미리보기도 그 설정으로 다시 채점된다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  allocationApi, frequencyLabel, frequencyVerdict, frequencyWarningText,
  type CanaryInput, type CanarySignalType, type TimingFactorMeta,
} from "@/entities/allocation";
import { CatalogueShell, type CatalogueItem } from "@/shared/ui/CatalogueShell";
import { TimingFactorPreview } from "./TimingFactorPreview";

/** 미리보기 구간 — 24개월이면 전환을 몇 번 보기에 충분하고 호출도 24회로 끝난다. */
const PREVIEW_MONTHS = 24;

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

/** 카나리 하나를 비교용 라벨→값 맵으로. 셸은 도메인을 모르므로 표시 문자열까지 여기서 만든다. */
function canaryFields(c: CanaryInput): Record<string, string> {
  const out: Record<string, string> = {
    "티커": c.id || "—",
    "임계": String(c.threshold),
    "방향": c.direction === "above" ? "이상" : "이하",
    "리밸런싱": c.rebalance_or_holding_period || "month_end",
  };
  Object.entries(c.params ?? {}).forEach(([k, v]) => { out[`파라미터 ${k}`] = String(v); });
  return out;
}

export function TimingFactorModal({ open, onClose, onAdd, active = [] }: {
  open: boolean;
  onClose: () => void;
  onAdd: (c: CanaryInput) => void;
  /** 이미 담겨 있는 카나리들 — 초안 vs 적용본 비교(§8.1 요구 12)의 '적용본' 쪽. */
  active?: CanaryInput[];
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

  // 같은 팩터가 이미 담겨 있으면 그것이 '적용본'. 없으면 null — "차이 없음"과 다른 사실이다.
  const activeCanary = useMemo(
    () => (sel ? active.find((c) => c.signal === sel.id) ?? null : null),
    [active, sel]);
  const upd = (patch: Partial<CanaryInput>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const updParam = (k: string, v: number) =>
    setDraft((d) => (d ? { ...d, params: { ...(d.params || {}), [k]: v }, lookback: v } : d));

  // 미리보기 — 값을 못 만드는 팩터(as_of 계열)는 애초에 요청하지 않는다.
  // 임계·방향·티커가 바뀌면 queryKey 가 바뀌어 그 설정으로 다시 채점된다.
  const canPreview = !!sel && !sel.requires_as_of && !!draft;
  const prevQ = useQuery({
    queryKey: ["allocation", "timing-factor-history", sel?.id, draft?.id,
      draft?.threshold, draft?.direction],
    queryFn: () => allocationApi.timingFactorHistory(sel!.id, {
      ticker: draft!.id, market: "kr", months: PREVIEW_MONTHS,
      threshold: draft!.threshold, direction: draft!.direction,
    }),
    enabled: open && canPreview,
    staleTime: 5 * 60_000,
  });

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
      comparison={draft ? {
        active: activeCanary ? canaryFields(activeCanary) : null,
        draft: canaryFields(draft),
      } : undefined}
      presets={draft ? {
        namespace: "timing-factor",
        draft: draft as unknown as Record<string, unknown>,
        onLoad: (p) => {
          // 프리셋이 가리키는 팩터를 먼저 고른 뒤 설정을 되먹인다 — 다른 팩터에 남의 설정을
          // 얹으면 파라미터 이름이 맞지 않는다.
          const f = flat.find((x) => x.id === p.itemId);
          if (f) { setSel(f); setDraft(p.payload as unknown as CanaryInput); }
        },
      } : undefined}
      applyLabel="이 팩터 추가 →"
      onApply={() => { if (draft && !sel?.requires_as_of) { onAdd(draft); onClose(); } }}
      applyDisabled={!draft || !!sel?.requires_as_of}
      previewSlot={canPreview ? (
        <TimingFactorPreview history={prevQ.data} loading={prevQ.isLoading}
          error={prevQ.isError} unit={sel?.unit} />
      ) : undefined}
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
