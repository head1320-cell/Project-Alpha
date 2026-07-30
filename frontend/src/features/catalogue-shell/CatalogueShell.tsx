"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// CatalogueShell — 카탈로그 선택 창의 단일 셸 (Phase 6, 스펙 §8.1)
//
// 무엇을 없애는가
// ─────────────────────────────────────────────────────────────────────────────
// StressScenarioModal(126줄)과 AlphaFactorModal(140줄)은 **구조가 사실상 동일**했다:
//   backdrop → dialog → head(제목+닫기) → body(좌: 검색+패밀리+목록 / 우: 상세+설정+적용) → note
// 다른 것은 우측 패널의 설정 위젯과 가용성 표기뿐이다. 그 공통 골격을 여기로 올린다.
//
// ★이 단계의 게이트는 "기능 손실 0" 이다★
// 스타일 개선이 목적이 아니라 중복 제거다. 각 창이 하던 일을 하나도 잃지 않아야 하고,
// stage-windows.spec.ts 의 기존 단언이 그 바닥선이다.
//
// 우측 패널은 **선택적 슬롯**이다 (Drift D6-2)
// ─────────────────────────────────────────────────────────────────────────────
// 스펙 §8.1 은 우측에 "과거 미리보기(값/임계/**시기 상황**/상태전환 횟수)"와
// "샘플링↔리밸런싱 빈도 충돌 경고"도 요구한다. 그 둘은 SignalState·evaluation_frequency,
// 즉 TimingRuleSetV2(Phase 7) 개념이다. 시나리오·알파 카탈로그에서는 "시기 상황"이라는
// 말 자체가 성립하지 않는다. 그래서 슬롯만 정의하고 **Phase 6 은 비워 둔다** —
// 6b(TimingFactorModal)가 채운다. 가짜 상태로 채우지 않는다.
//
// 툴팁을 쓰지 않는 이유: 기존 두 창은 title= 을 **0회** 쓴다. 미가용 사유를 툴팁에 숨기지
// 않고 목록 행에 그대로 적는 것이 의도된 정직성 설계다(StressScenarioModal 주석 참조).
// §8.1 이 Tooltip 을 나열하지만 여기서 도입하면 그 설계를 되돌리는 셈이라 넣지 않았다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useRef, useState } from "react";
import { ToggleGroup, ToggleGroupItem } from "@/shared/ui/shadcn/toggle-group";
import { cn } from "@/shared/lib/cn";

/** 좌측 목록 한 줄. 도메인 타입을 셸이 알지 않도록 최소 표면만 받는다. */
export interface CatalogueItem {
  id: string;
  /** 행 제목 */
  label: string;
  /** 행 설명 */
  description: string;
  /** 행 우측 메타 — 출처·id 등 */
  meta?: string;
  /** 종류 배지 (연산자 / 역사 리플레이 …) */
  kindBadge?: string;
  /** false 면 선택은 되지만 적용은 막는다. 사유는 목록에 그대로 적는다. */
  available?: boolean;
  /** 미가용 사유 — 툴팁이 아니라 화면에 */
  unavailableReason?: string;
  /** 검색 대상에 추가할 문자열들 */
  searchExtra?: string[];
}

export interface CatalogueFamily { id: string; label: string }

export interface CatalogueShellProps {
  open: boolean;
  onClose: () => void;
  /** 창 제목 + 부제 */
  title: string;
  subtitle?: string;
  /** 다이얼로그 aria-label */
  ariaLabel: string;
  /** 검색 입력 placeholder */
  searchPlaceholder: string;

  families: CatalogueFamily[];
  /** 현재 패밀리 (검색어가 없을 때 목록을 좁힌다) */
  family: string;
  onFamilyChange: (id: string) => void;

  /** 이 패밀리의 항목들 — 검색 중이면 호출자가 전체를 넘긴다 */
  items: CatalogueItem[];
  /** 전체 항목 (검색용) */
  allItems: CatalogueItem[];

  selectedId: string | null;
  onSelect: (item: CatalogueItem) => void;
  /** 이미 적용되어 있는 항목 — "선택됨" 배지 */
  activeId?: string;

  loading?: boolean;
  error?: boolean;
  errorText?: string;
  /** 하단 정직성 노트 */
  note?: string;

  /** 우측 패널: 선택 항목에 대한 설정 위젯 */
  children?: React.ReactNode;
  /** 우측 패널 하단 적용 버튼 */
  applyLabel: string;
  onApply: () => void;
  applyDisabled?: boolean;

  /** ── 선택적 슬롯 (Phase 6 은 비워 둔다 · 6b 가 채운다) ── */
  previewSlot?: React.ReactNode;
  frequencyWarningSlot?: React.ReactNode;
}

/** 검색 매칭 — 라벨·설명·id·추가 문자열. 한글/영문 모두 소문자 비교. */
function matches(i: CatalogueItem, needle: string): boolean {
  const hay = [i.label, i.description, i.id, ...(i.searchExtra ?? [])]
    .join(" ").toLowerCase();
  return hay.includes(needle);
}

export function CatalogueShell(props: CatalogueShellProps) {
  const {
    open, onClose, title, subtitle, ariaLabel, searchPlaceholder,
    families, family, onFamilyChange, items, allItems,
    selectedId, onSelect, activeId, loading, error, errorText, note,
    children, applyLabel, onApply, applyDisabled,
    previewSlot, frequencyWarningSlot,
  } = props;

  const [q, setQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (!open) setQ(""); }, [open]);

  // Escape 로 닫기 — 기존 창들은 backdrop 클릭만 지원했다(스펙 §8.1: Escape close).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return items;
    return allItems.filter((i) => matches(i, s));
  }, [q, items, allItems]);

  if (!open) return null;

  return (
    // .tfm-* 클래스는 그대로 유지한다 — Playwright 계약이고, 이 단계는 중복 제거가 목적이다.
    <div className="tfm-backdrop" onClick={onClose}>
      <div className="tfm" ref={dialogRef} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-label={ariaLabel}>
        <div className="tfm-head">
          <div className="tfm-title">
            {title}{subtitle && <span className="as-note-inline">{subtitle}</span>}
          </div>
          <button className="as-x" onClick={onClose} aria-label="닫기">×</button>
        </div>

        <div className="tfm-body">
          <div className="tfm-left">
            <input ref={searchRef} className="tfm-search" placeholder={searchPlaceholder}
              value={q} onChange={(e) => setQ(e.target.value)} autoFocus
              aria-label={searchPlaceholder} />

            {/* 검색 중에는 패밀리 필터를 숨긴다(기존 동작 유지) */}
            {!q && families.length > 0 && (
              <ToggleGroup type="single" value={family} className="tfm-fams"
                aria-label="패밀리 필터"
                onValueChange={(v) => { if (v) onFamilyChange(v); }}>
                {families.map((f) => (
                  <ToggleGroupItem key={f.id} value={f.id}>{f.label}</ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}

            <div className="tfm-list" role="listbox" aria-label="카탈로그">
              {loading && <div className="as-empty">불러오는 중…</div>}
              {error && <div className="as-err">{errorText || "불러오지 못했습니다."}</div>}
              {!loading && results.length === 0 && <div className="as-empty">검색 결과가 없습니다</div>}
              {results.map((i) => {
                const off = i.available === false;
                return (
                  <button key={i.id} role="option" aria-selected={selectedId === i.id}
                    className={cn("tfm-row", selectedId === i.id && "on", off && "off")}
                    onClick={() => onSelect(i)}>
                    <span className="tfm-row-t">
                      {i.label}
                      {activeId === i.id && <em className="tfm-kind">선택됨</em>}
                      {i.kindBadge && <em className="tfm-kind">{i.kindBadge}</em>}
                      {off && <em className="tfm-off">미가용</em>}
                    </span>
                    <span className="tfm-row-d">{i.description}</span>
                    {/* 미가용 사유를 툴팁이 아니라 목록에 — 왜 못 쓰는지 바로 보이게 */}
                    <span className="tfm-row-p">
                      {off ? (i.unavailableReason || "데이터 미보유") : (i.meta ?? "")}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="tfm-right">
            {!selectedId ? (
              <div className="as-empty">왼쪽에서 항목을 선택하세요.</div>
            ) : (
              <>
                {children}
                {/* 선택적 슬롯 — Phase 6 은 넘기지 않는다(6b 소관) */}
                {previewSlot}
                {frequencyWarningSlot}
                <button className="as-fb-apply" disabled={applyDisabled} onClick={onApply}>
                  {applyLabel}
                </button>
              </>
            )}
          </div>
        </div>

        {note && <div className="tfm-note">{note}</div>}
      </div>
    </div>
  );
}
