"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// CatalogueShell — 카탈로그 선택 창의 단일 셸 (Phase 6, 스펙 §8.1)
//
// ★왜 shared/ui 인가 (Phase 11c)★
// 원래 `features/catalogue-shell` 에 있었다. 네 번째 창인 팩터 픽커가 `features/factor-picker`
// 라서, 셸을 features 에 두면 **같은 계층 슬라이스끼리의 import** 가 되어 FSD 가드레일이
// 막는다(실측: `import/no-restricted-paths` 에러 1건). 규칙이 안내하는 대로 shared 로 내렸다 —
// 셸은 이미 도메인 타입을 하나도 모르므로 원래 이 자리가 맞았고, '네 창이 한 셸을 쓴다' 는
// §8.1 의 주장이 구조로도 참이 된다.
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
// Phase 6b 현황: `frequencyWarningSlot` 은 TimingFactorModal 이 채웠다.
// `previewSlot` 은 **여전히 비어 있다** — 팩터의 과거 시계열을 내려주는 엔진/엔드포인트가
// 아직 없다(`evaluate()` 는 현재값 스칼라 하나뿐). 자리만 그럴듯하게 채우는 것은 정직성
// 규칙 위반이라 6b-2 로 넘겼다(drift D6b-1).
//
// 툴팁을 쓰지 않는 이유: 기존 두 창은 title= 을 **0회** 쓴다. 미가용 사유를 툴팁에 숨기지
// 않고 목록 행에 그대로 적는 것이 의도된 정직성 설계다(StressScenarioModal 주석 참조).
// §8.1 이 Tooltip 을 나열하지만 여기서 도입하면 그 설계를 되돌리는 셈이라 넣지 않았다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ToggleGroup, ToggleGroupItem } from "@/shared/ui/shadcn/toggle-group";
import { cn } from "@/shared/lib/cn";
import { useFocusTrap } from "@/shared/lib/useFocusTrap";
import {
  deletePreset, listPresets, savePreset,
  type CataloguePreset, type PresetNamespace,
} from "@/shared/lib/cataloguePresets";

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
  /**
   * `kindBadge` 에 함께 붙일 클래스. **등급을 눈으로 구별해야 할 때만** 쓴다 —
   * `.tfm-kind` 하나로는 "선택됨" 배지와 같은 모양이라 등급 차이가 화면에서 사라진다.
   */
  kindBadgeClass?: string;
  /** false 면 선택은 되지만 적용은 막는다. 사유는 목록에 그대로 적는다. */
  available?: boolean;
  /** 미가용 사유 — 툴팁이 아니라 화면에 */
  unavailableReason?: string;
  /** 검색 대상에 추가할 문자열들 */
  searchExtra?: string[];
  /**
   * 목록 안 소제목 (Phase 11c). 카탈로그가 **2단 위계**일 때 쓴다 —
   * 팩터 창은 카테고리 13개 아래 그룹 42개를 갖고, 그룹 이름이 사라지면 "시가총액"이
   * 어느 묶음의 것인지 화면에서 알 수 없다. 연속한 항목의 값이 바뀔 때만 한 줄 그린다.
   * ★검색 중에는 그리지 않는다★ 검색 결과는 패밀리를 가로지르므로 소제목이 뒤섞여
   * 오히려 위계를 왜곡한다(패밀리 필터를 검색 중에 숨기는 것과 같은 이유).
   */
  groupLabel?: string;
}

export interface CatalogueFamily {
  id: string;
  label: string;
  /**
   * 토글에 함께 적는 표시용 개수 — 예: `"13/20"` (지원/전체) 또는 `"20"`.
   * ★셸은 도메인을 모른다★ 그래서 계산하지 않고 **완성된 문자열**을 받는다.
   * 주지 않으면 개수 자체가 없다 — 0 이나 추정치로 채우지 않는다.
   *
   * 이름이 `count` 가 아닌 이유: `StressScenarioModal` 이 이미 자기 패밀리 객체에
   * `count: number` 를 달고 있다(셸은 그걸 읽지 않는다). 같은 이름을 쓰면 그 창이
   * 컴파일되지 않으므로, 표시용 문자열임을 이름으로 구분한다.
   */
  countLabel?: string;
}

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

  /** ── Phase 6d: 저장된 프리셋 (스펙 §8.1 요구 11) ──
   *  창이 네임스페이스와 현재 draft 를 주면 셸이 저장/불러오기 UI 를 그린다.
   *  주지 않으면 프리셋 줄 자체가 없다 — 쓸 수 없는 버튼을 보여 주지 않는다. */
  presets?: {
    namespace: PresetNamespace;
    /** 지금 설정 — 저장 버튼이 이걸 담는다. */
    draft: Record<string, unknown>;
    /** 불러오기 — 창이 자기 draft 상태에 되먹인다. itemId 로 대상 항목도 함께 복원한다. */
    onLoad: (preset: CataloguePreset) => void;
  };

  /** ── Phase 6d: 초안 vs 적용본 비교 (스펙 §8.1 요구 12) ──
   *  라벨 → 값 맵. 셸은 도메인을 모르므로 **표시용 값**을 그대로 받아 다른 항목만 나열한다.
   *  `active` 가 없으면 "아직 적용된 것이 없다" 는 뜻이며, 그 경우 비교가 아니라 그 사실을 적는다. */
  comparison?: {
    active: Record<string, string> | null;
    draft: Record<string, string>;
  };

  /**
   * ── Phase 11c: 창 단위 색조 ──
   * 대화상자 루트에 얹는 **CSS 변수 선언**이다(스타일링이 아니라 변수 대입 — shadcn 방식).
   * 팩터 창은 매수/매도 문맥에 따라 색이 달라야 했고, 그 능력을 셸로 옮기면서 잃지 않으려면
   * 여기가 필요하다. `--t-accent` 를 얹으면 기존 `.tfm-*` 규칙이 그대로 다시 물든다 —
   * 새 CSS 를 만들지 않고 토큰만 지역적으로 덮는다(`:root` 는 건드리지 않는다).
   */
  styleVars?: React.CSSProperties;
}

/** 초안과 적용본에서 **달라진 항목만** 뽑는다. 같은 값을 나열하면 무엇이 바뀌었는지 묻힌다. */
function diffFields(active: Record<string, string>, draft: Record<string, string>) {
  const keys = Array.from(new Set([...Object.keys(active), ...Object.keys(draft)]));
  return keys
    .map((k) => ({ key: k, from: active[k] ?? "—", to: draft[k] ?? "—" }))
    .filter((d) => d.from !== d.to);
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
    previewSlot, frequencyWarningSlot, presets, comparison, styleVars,
  } = props;

  const [q, setQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  // ★A14: 창은 `document.body` 로 포털한다 — 이것이 없으면 창이 창이 아니다★
  // 예전에는 소비자가 놓인 자리에 **인라인으로** 렌더됐다. A11 §62 가
  // `.as-ws2 .as-center > .as-card` 에 `animation: a11-rise … both` 를 걸면서 그 카드의
  // computed transform 이 `matrix(1,0,0,1,0,0)`(= `none` 이 아니다)로 **영구히** 남았고,
  // transform 이 있는 조상은 `position: fixed` 의 컨테이닝 블록이 된다. 그래서
  // `.tfm-backdrop { position: fixed; inset: 0 }` 이 뷰포트가 아니라 **카드 상자**에
  // 갇혔다 — 실측 298×241px, 적용 버튼은 y=2321 로 화면 밖. z-index 9998 도 그 카드의
  // stacking context 안이라 형제 카드가 위를 덮었다.
  // 증상: `.tfm` 은 상자가 비어 있지 않아 `toBeVisible()` 을 통과하는데 **클릭이 안 된다**
  // (Playwright: "…intercepts pointer events"). 9개 `.as-ws2` 스테이지 전부가 그랬다.
  // 포털은 원인이 무엇이든 구조적으로 이 계열을 닫는다. 선례: `.shad-overlay`(z-1000),
  // Radix Dialog. `.tfm-*` 클래스명은 그대로라 E2E 계약은 유지된다.
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);   // SSR 에는 document 가 없다

  // 프리셋 목록은 localStorage 라 렌더 중에 읽지 않는다(SSR 불일치). 창이 열릴 때 한 번.
  const [presetRows, setPresetRows] = useState<CataloguePreset[]>([]);
  const [presetName, setPresetName] = useState("");
  const ns = presets?.namespace;
  const refreshPresets = React.useCallback(() => {
    setPresetRows(ns ? listPresets(ns) : []);
  }, [ns]);
  useEffect(() => { if (open) refreshPresets(); }, [open, refreshPresets]);

  // 스펙 §8.1 — 열려 있는 동안 Tab 이 창 밖으로 걸어 나가지 못하게 한다(닫으면 원위치 복귀).
  useFocusTrap(dialogRef, open);

  useEffect(() => { if (!open) { setQ(""); setPresetName(""); } }, [open]);

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

  if (!open || !mounted) return null;

  return createPortal(
    // .tfm-* 클래스는 그대로 유지한다 — Playwright 계약이고, 이 단계는 중복 제거가 목적이다.
    <div className="tfm-backdrop" onClick={onClose} style={styleVars}>
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
                  <ToggleGroupItem key={f.id} value={f.id}>
                    {f.label}
                    {/* ★개수를 숨기지 않는다★ 0/7 처럼 전부 미가용인 묶음도 그대로 적는다 —
                        비어 보이는 패밀리를 눌러 보고서야 알게 되는 것이 더 나쁘다. */}
                    {f.countLabel && <span className="tfm-fam-n num">{f.countLabel}</span>}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            )}

            <div className="tfm-list" role="listbox" aria-label="카탈로그">
              {loading && <div className="as-empty">불러오는 중…</div>}
              {error && <div className="as-err">{errorText || "불러오지 못했습니다."}</div>}
              {!loading && results.length === 0 && <div className="as-empty">검색 결과가 없습니다</div>}
              {results.map((i, idx) => {
                const off = i.available === false;
                // 소제목은 **검색 중이 아닐 때만**, 그리고 값이 바뀌는 첫 항목에만.
                const head = !q && i.groupLabel && i.groupLabel !== results[idx - 1]?.groupLabel
                  ? i.groupLabel : null;
                return (
                  <React.Fragment key={i.id}>
                  {head && <div className="tfm-group" role="presentation">{head}</div>}
                  <button role="option" aria-selected={selectedId === i.id}
                    className={cn("tfm-row", selectedId === i.id && "on", off && "off")}
                    onClick={() => onSelect(i)}>
                    <span className="tfm-row-t">
                      {i.label}
                      {activeId === i.id && <em className="tfm-kind">선택됨</em>}
                      {i.kindBadge && (
                        <em className={cn("tfm-kind", i.kindBadgeClass)}>{i.kindBadge}</em>
                      )}
                      {off && <em className="tfm-off">미가용</em>}
                    </span>
                    <span className="tfm-row-d">{i.description}</span>
                    {/* 미가용 사유를 툴팁이 아니라 목록에 — 왜 못 쓰는지 바로 보이게 */}
                    <span className="tfm-row-p">
                      {off ? (i.unavailableReason || "데이터 미보유") : (i.meta ?? "")}
                    </span>
                  </button>
                  </React.Fragment>
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

                {/* ── 초안 vs 적용본 (§8.1 요구 12) ── */}
                {comparison && (
                  <div className="tfm-cmp">
                    <div className="tfm-cmp-h">초안 vs 적용본</div>
                    {comparison.active === null ? (
                      // ★비교 대상이 없다는 것과 "차이가 없다"는 다른 사실이다★
                      <div className="tfm-cmp-none">
                        아직 적용된 설정이 없습니다 — 비교할 대상이 없습니다(차이가 없는 것이 아닙니다).
                      </div>
                    ) : (() => {
                      const rows = diffFields(comparison.active, comparison.draft);
                      return rows.length === 0 ? (
                        <div className="tfm-cmp-same">적용본과 같습니다 — 적용해도 바뀌는 것이 없습니다.</div>
                      ) : (
                        <ul className="tfm-cmp-list">
                          {rows.map((d) => (
                            <li key={d.key} className="tfm-cmp-row">
                              <span className="tfm-cmp-k">{d.key}</span>
                              <span className="tfm-cmp-from num">{d.from}</span>
                              <span className="tfm-cmp-arrow">→</span>
                              <span className="tfm-cmp-to num">{d.to}</span>
                            </li>
                          ))}
                        </ul>
                      );
                    })()}
                  </div>
                )}

                {/* ── 저장된 프리셋 (§8.1 요구 11) ── */}
                {presets && (
                  <div className="tfm-preset">
                    <div className="tfm-preset-h">프리셋</div>
                    <div className="tfm-preset-save">
                      <input className="tfm-preset-name" value={presetName}
                        placeholder="이 설정에 이름을 붙여 저장"
                        aria-label="프리셋 이름"
                        onChange={(e) => setPresetName(e.target.value)} />
                      <button className="tfm-preset-add" disabled={!selectedId}
                        onClick={() => {
                          savePreset(presets.namespace, presetName, selectedId!, presets.draft);
                          setPresetName("");
                          refreshPresets();
                        }}>저장</button>
                    </div>
                    {presetRows.length === 0 ? (
                      <div className="tfm-preset-empty">저장된 프리셋이 없습니다.</div>
                    ) : (
                      <ul className="tfm-preset-list">
                        {presetRows.map((p) => (
                          <li key={p.id} className="tfm-preset-row">
                            <button className="tfm-preset-load"
                              onClick={() => presets.onLoad(p)}>
                              {p.name}
                              <span className="tfm-preset-item num">{p.itemId}</span>
                            </button>
                            <button className="tfm-preset-del" aria-label={`${p.name} 삭제`}
                              onClick={() => { deletePreset(presets.namespace, p.id); refreshPresets(); }}>
                              ×
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {/* ★프리셋은 재현 좌표가 아니다★ 룰셋 버전과 혼동하면 안 된다. */}
                    <div className="tfm-preset-note">
                      프리셋은 이 브라우저에만 저장됩니다 — 런에 기록되지 않으므로 재현 좌표가
                      아닙니다.
                    </div>
                  </div>
                )}

                <button className="as-fb-apply" disabled={applyDisabled} onClick={onApply}>
                  {applyLabel}
                </button>
              </>
            )}
          </div>
        </div>

        {note && <div className="tfm-note">{note}</div>}
      </div>
    </div>,
    document.body,
  );
}
