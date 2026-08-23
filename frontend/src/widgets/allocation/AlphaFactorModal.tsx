"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AlphaFactorModal — 02 ALPHA LAB 통합 표현식 팩터 창
//   기존엔 필드 17개 + 함수 9개가 구분 없는 칩 벽으로 깔려 설명은 title 툴팁에만 있었고,
//   클릭하면 무조건 " + 필드"를 덧붙이거나 식 전체를 함수로 감쌌다. TimingFactorModal과
//   동일한 UX(검색 + 패밀리 탭 + 설명·출처 + 삽입 방식 선택)로 통합.
//
// Phase 6: 공통 골격을 CatalogueShell 로 올렸다. 이 파일에는 **알파 고유의 것만** 남는다:
// 삽입 방식(add/sub/replace/wrap) · 함수 vs 필드 분기 · 적용 결과 미리보기.
// applyInsert 는 순수 함수라 그대로 유지(테스트/재사용 가능).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { alphaApi, type AlphaCatalogItem } from "@/entities/alpha/api";
import { CatalogueShell, type CatalogueItem } from "@/shared/ui/CatalogueShell";

/** 도메인 항목 → 셸이 아는 최소 표면. */
function toCatalogueItem(i: AlphaCatalogItem): CatalogueItem {
  return {
    id: i.id,
    label: i.label,
    description: i.desc,
    meta: i.id,
    kindBadge: i.kind === "function" ? "연산자" : undefined,
  };
}

export type AlphaInsertMode = "add" | "sub" | "replace" | "wrap";

const MODE_LABEL: Record<AlphaInsertMode, string> = {
  add: "더하기 ( + )", sub: "빼기 ( − )", replace: "식 교체", wrap: "현재 식 감싸기",
};

/** 삽입 방식 → 새 표현식. 순수 함수라 테스트/재사용 가능. */
export function applyInsert(expr: string, item: AlphaCatalogItem, mode: AlphaInsertMode): string {
  const cur = expr.trim();
  if (item.kind === "function") {
    const inner = cur || "mom_6m";
    return item.insert === "wrap2" ? `${item.id}(${inner}, mom_6m)` : `${item.id}(${inner})`;
  }
  if (!cur || mode === "replace") return item.id;
  if (mode === "sub") return `${cur} - ${item.id}`;
  if (mode === "wrap") return `${cur} - ${item.id}`;   // 필드엔 wrap 없음 — 안전 폴백
  return `${cur} + ${item.id}`;
}

export function AlphaFactorModal({ open, onClose, expr, onApply }: {
  open: boolean;
  onClose: () => void;
  expr: string;
  onApply: (nextExpr: string) => void;
}) {
  const catQ = useQuery({
    queryKey: ["alpha", "fields"],
    queryFn: () => alphaApi.fields(),
    staleTime: Infinity,
    enabled: open,
  });
  const [fam, setFam] = useState<string>("price");
  const [sel, setSel] = useState<AlphaCatalogItem | null>(null);
  const [mode, setMode] = useState<AlphaInsertMode>("add");

  const groups = catQ.data?.groups ?? [];
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const famItems = useMemo(
    () => (groups.find((g) => g.family === fam)?.items ?? []).map(toCatalogueItem),
    [groups, fam]);
  const allItems = useMemo(() => flat.map(toCatalogueItem), [flat]);

  useEffect(() => { if (!open) { setSel(null); setMode("add"); } }, [open]);

  const preview = sel ? applyInsert(expr, sel, mode) : "";

  return (
    <CatalogueShell
      open={open} onClose={onClose}
      title="알파 팩터"
      subtitle="피처·연산자를 골라 표현식에 넣으세요"
      ariaLabel="알파 팩터 추가"
      searchPlaceholder="팩터 검색 — 이름·설명·id"
      families={catQ.data?.families ?? []}
      family={fam} onFamilyChange={setFam}
      items={famItems} allItems={allItems}
      selectedId={sel?.id ?? null}
      onSelect={(ci) => {
        const item = flat.find((i) => i.id === ci.id) ?? null;
        setSel(item);
        // 함수는 감싸기만 가능, 필드로 돌아오면 wrap 을 해제 (기존 동작 그대로)
        if (item?.kind === "function") setMode("wrap");
        else if (mode === "wrap") setMode("add");
      }}
      loading={catQ.isLoading} error={catQ.isError}
      errorText="카탈로그를 불러오지 못했습니다."
      note={catQ.data?.note}
      applyLabel="표현식에 넣기 →"
      comparison={sel ? {
        // 빈 표현식은 "적용된 것이 없다" 이지 "빈 문자열이 적용됐다" 가 아니다.
        active: expr.trim() ? { "표현식": expr } : null,
        draft: { "표현식": preview },
      } : undefined}
      presets={sel ? {
        namespace: "alpha-factor",
        draft: { mode },
        onLoad: (p) => {
          const it = flat.find((x) => x.id === p.itemId);
          if (it) setSel(it);
          // 유효한 모드만 되먹인다. 목록을 손으로 적으면 모드가 늘 때 조용히 빠지므로
          // MODE_LABEL(단일 출처)의 키로 검사한다.
          const m = String(p.payload.mode ?? "");
          if (m in MODE_LABEL) setMode(m as AlphaInsertMode);
        },
      } : undefined}
      onApply={() => { onApply(preview); onClose(); }}
    >
      {sel && (
        <>
          <div className="tfm-sel-t">{sel.label}</div>
          <div className="tfm-sel-d">{sel.desc}</div>
          {sel.kind === "field" && (
            <label className="as-tm-set">
              <span>삽입 방식</span>
              <select className="as-tm-sig" value={mode}
                onChange={(e) => setMode(e.target.value as AlphaInsertMode)}
                aria-label="삽입 방식">
                {(["add", "sub", "replace"] as AlphaInsertMode[]).map((m) => (
                  <option key={m} value={m}>{MODE_LABEL[m]}</option>
                ))}
              </select>
            </label>
          )}
          {sel.kind === "function" && (
            <div className="as-note">
              현재 식 전체를 <b>{sel.id}(…)</b>로 감쌉니다
              {sel.insert === "wrap2" && " (2항 함수 — 두 번째 인자는 넣은 뒤 편집하세요)"}.
            </div>
          )}
          <div className="tfm-prev-l">적용 결과 미리보기</div>
          <code className="tfm-prev">{preview}</code>
          <div className="tfm-row-p">출처 · {sel.provenance}</div>
        </>
      )}
    </CatalogueShell>
  );
}
