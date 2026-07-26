"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AlphaFactorModal — 02 ALPHA LAB 통합 표현식 팩터 창
//   기존엔 필드 17개 + 함수 9개가 구분 없는 칩 벽으로 깔려 설명은 title 툴팁에만 있었고,
//   클릭하면 무조건 " + 필드"를 덧붙이거나 식 전체를 함수로 감쌌다. TimingFactorModal과
//   동일한 UX(검색 + 패밀리 탭 + 설명·출처 + 삽입 방식 선택)로 통합.
//   .tfm-* 스타일을 그대로 공유 — 스테이지 간 팩터 창의 시각·조작 일관성.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { alphaApi, type AlphaCatalogItem } from "@/entities/alpha/api";

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
  const [q, setQ] = useState("");
  const [fam, setFam] = useState<string>("price");
  const [sel, setSel] = useState<AlphaCatalogItem | null>(null);
  const [mode, setMode] = useState<AlphaInsertMode>("add");

  const groups = catQ.data?.groups ?? [];
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return groups.find((g) => g.family === fam)?.items ?? [];
    return flat.filter((i) =>
      i.label.toLowerCase().includes(s) || i.desc.toLowerCase().includes(s) ||
      i.id.toLowerCase().includes(s));
  }, [q, fam, groups, flat]);

  useEffect(() => { if (!open) { setQ(""); setSel(null); setMode("add"); } }, [open]);

  const preview = sel ? applyInsert(expr, sel, mode) : "";

  if (!open) return null;
  return (
    <div className="tfm-backdrop" onClick={onClose}>
      <div className="tfm" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="알파 팩터 추가">
        <div className="tfm-head">
          <div className="tfm-title">알파 팩터 <span className="as-note-inline">피처·연산자를 골라 표현식에 넣으세요</span></div>
          <button className="as-x" onClick={onClose} aria-label="닫기">×</button>
        </div>

        <div className="tfm-body">
          <div className="tfm-left">
            <input className="tfm-search" placeholder="팩터 검색 — 이름·설명·id"
              value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
            {!q && (
              <div className="tfm-fams">
                {(catQ.data?.families ?? []).map((f) => (
                  <button key={f.id} className={fam === f.id ? "on" : ""} onClick={() => setFam(f.id)}>{f.label}</button>
                ))}
              </div>
            )}
            <div className="tfm-list">
              {catQ.isLoading && <div className="as-empty">카탈로그 불러오는 중…</div>}
              {catQ.isError && <div className="as-err">카탈로그를 불러오지 못했습니다.</div>}
              {!catQ.isLoading && results.length === 0 && <div className="as-empty">검색 결과가 없습니다</div>}
              {results.map((i) => (
                <button key={i.id} className={`tfm-row${sel?.id === i.id ? " on" : ""}`}
                  onClick={() => { setSel(i); if (i.kind === "function") setMode("wrap"); else if (mode === "wrap") setMode("add"); }}>
                  <span className="tfm-row-t">
                    {i.label}
                    {i.kind === "function" && <em className="tfm-kind">연산자</em>}
                  </span>
                  <span className="tfm-row-d">{i.desc}</span>
                  <span className="tfm-row-p">{i.id}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="tfm-right">
            {!sel ? (
              <div className="as-empty">왼쪽에서 팩터를 선택하세요.</div>
            ) : (
              <>
                <div className="tfm-sel-t">{sel.label}</div>
                <div className="tfm-sel-d">{sel.desc}</div>
                {sel.kind === "field" && (
                  <label className="as-tm-set">
                    <span>삽입 방식</span>
                    <select className="as-tm-sig" value={mode}
                      onChange={(e) => setMode(e.target.value as AlphaInsertMode)}>
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
                <button className="as-fb-apply" onClick={() => { onApply(preview); onClose(); }}>
                  표현식에 넣기 →
                </button>
              </>
            )}
          </div>
        </div>

        {catQ.data?.note && <div className="tfm-note">{catQ.data.note}</div>}
      </div>
    </div>
  );
}
