"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// StressScenarioModal — 06 STRESS 통합 시나리오 창
//   시나리오가 세 곳에 흩어져 있었다: 좌측 레일의 가상 4 + 역사 4 버튼, 우측
//   KrScenarioPack 카드 안의 국내 7 버튼. 15종을 한 창에서 검색·분류·선택하고
//   강도(severity)까지 같은 자리에서 맞춘다.
//
// Phase 6: 공통 골격을 CatalogueShell 로 올렸다 — AlphaFactorModal 과 사실상 같은
// 구조였다. 이 파일에는 **시나리오 고유의 것만** 남는다: 강도 슬라이더(적용 여부 분기),
// 가용성/사유, 출처 표기. .tfm-* 클래스 계약은 셸이 그대로 유지한다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { allocationApi, type StressScenarioItem } from "@/entities/allocation/api";
import { CatalogueShell, type CatalogueItem } from "@/features/catalogue-shell/CatalogueShell";

/** 도메인 항목 → 셸이 아는 최소 표면. 셸이 StressScenarioItem 을 알 필요가 없다. */
function toCatalogueItem(i: StressScenarioItem): CatalogueItem {
  return {
    id: i.id,
    label: i.label,
    description: i.description,
    meta: i.source,
    available: i.available,
    unavailableReason: i.reason || undefined,
    searchExtra: [i.source],
  };
}

export function StressScenarioModal({ open, onClose, selectedId, severity, onSeverity, onPick }: {
  open: boolean;
  onClose: () => void;
  selectedId: string;
  severity: number;
  onSeverity: (v: number) => void;
  onPick: (s: StressScenarioItem) => void;
}) {
  const catQ = useQuery({
    queryKey: ["allocation", "stress-scenarios"],
    queryFn: () => allocationApi.stressScenarios(),
    staleTime: Infinity,
    enabled: open,
  });
  const [fam, setFam] = useState<string>("hypothetical");
  const [sel, setSel] = useState<StressScenarioItem | null>(null);

  const groups = catQ.data?.groups ?? [];
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const famItems = useMemo(
    () => (groups.find((g) => g.family === fam)?.items ?? []).map(toCatalogueItem),
    [groups, fam]);
  const allItems = useMemo(() => flat.map(toCatalogueItem), [flat]);

  // 창을 열면 현재 선택된 시나리오를 그대로 보여준다(맥락 유지)
  useEffect(() => {
    if (!open) { setSel(null); return; }
    const cur = flat.find((i) => i.id === selectedId);
    if (cur) { setSel(cur); setFam(cur.family); }
  }, [open, selectedId, flat]);

  return (
    <CatalogueShell
      open={open} onClose={onClose}
      title="스트레스 시나리오"
      subtitle="가상 · 역사 리플레이 · 국내팩을 한 창에서"
      ariaLabel="스트레스 시나리오 선택"
      searchPlaceholder="시나리오 검색 — 이름·설명·출처"
      families={catQ.data?.families ?? []}
      family={fam} onFamilyChange={setFam}
      items={famItems} allItems={allItems}
      selectedId={sel?.id ?? null}
      activeId={selectedId}
      onSelect={(ci) => setSel(flat.find((i) => i.id === ci.id) ?? null)}
      loading={catQ.isLoading} error={catQ.isError}
      errorText="시나리오를 불러오지 못했습니다."
      note={catQ.data?.note}
      applyLabel="이 시나리오로 검증 →"
      applyDisabled={!sel?.available}
      onApply={() => { if (sel) { onPick(sel); onClose(); } }}
    >
      {sel && (
        <>
          <div className="tfm-sel-t">{sel.label}</div>
          <div className="tfm-sel-d">{sel.description}</div>
          <div className="tfm-row-p">출처 · {sel.source}</div>

          {sel.severity_applies ? (
            <label className="as-param">
              <span>시나리오 강도 <b className="num">{severity.toFixed(2)}×</b></span>
              <input type="range" min={0.25} max={3} step={0.25} value={severity}
                onChange={(e) => onSeverity(parseFloat(e.target.value))}
                aria-label="시나리오 강도" />
              <em className="as-note-inline">추정 충격을 배율만큼 확대·축소</em>
            </label>
          ) : (
            <div className="as-note">
              실제 시세를 그대로 재생하는 역사 리플레이라 <b>강도 배율이 적용되지 않습니다</b>.
            </div>
          )}

          {!sel.available && (
            <div className="as-err">{sel.reason || "이 시나리오는 현재 데이터로 실행할 수 없습니다."}</div>
          )}
        </>
      )}
    </CatalogueShell>
  );
}
