"use client";
// 대상 경로: frontend/src/components/backtest/FactorPickerModal.tsx
//
// 젠포트식 팩터 선택 창. STEP1(팩터 선택) → STEP2(함수 선택) → "입력" 시
// onInsert 로 { factorName, expr, functionId, params } 를 부모(조건식 에디터)에 전달.

import { useEffect, useMemo, useState } from "react";
import { Search, X, ChevronRight, ChevronDown, ArrowRight, ArrowLeft, Check, ExternalLink } from "lucide-react";
import { type GpFactor } from "@/entities/backtest/factorCatalog";
import { BUTLER_CATEGORIES, butlerToken } from "@/entities/backtest/butlerFactors";
import { FACTOR_FUNCTIONS, FUNCTIONS_BY_ID, INNER_FUNCTIONS, fillTemplate } from "@/entities/backtest/factorFunctions";
import { backtestBridgeApi } from "@/entities/backtest/bridgeApi";
import { type TokenSupportMap } from "@/entities/backtest/bridgeModel";
import { TONES, type Tone } from "@/shared/ui/kit";
// clsx 만 쓴다 — 공용 `cn` 은 tailwind-merge 를 함께 끌어와 이 두 라우트에 +7 kB 를 더한다.
// 여기서는 **충돌하는 유틸리티를 합칠 일이 없다**(모든 클래스 문자열이 이 파일 안에서 조건부로
// 이어붙기만 한다). 그래서 머지 기능에 값을 지불하지 않는다.
import { clsx } from "clsx";

// 지원 맵 모듈 캐시 — 백엔드(/condition-tokens)가 단일 진실 공급원.
// 로드 실패 시 null → 배지 없이 기존 동작 (오프라인 데모 호환).
let _supportCache: TokenSupportMap | null = null;

interface SupportInfo { ok: boolean; group?: string; reason?: string }

export interface FactorPick {
  factorName: string;
  factorToken: string;   // {고가}
  functionId: string;
  params: Record<string, string>;
  expr: string;          // 이동평균({고가}, 20) · 순위(변화율_기간({종가}, 20), 내림차순)
  // 중첩(순위/비율 전용): 랭킹 대상을 파생 지표로 — 예: 순위(변화율_기간(종가,20))
  innerFunctionId?: string;
  innerParams?: Record<string, string>;
  // 두 팩터 변형(비교/큰값/작은값/변화율_팩터): 두 번째 피연산자 + 자체 중첩
  // 예: 변화율_팩터({당기순이익}, 과거값({당기순이익}, 1년))
  factorName2?: string;
  factorToken2?: string;
  inner2FunctionId?: string;
  inner2Params?: Record<string, string>;
}

// 두 번째 피연산자를 팩터로 받을 수 있는 함수 (변화율_팩터는 팩터 필수)
const TWO_FACTOR_IDS = new Set(["cmp", "gt", "lt", "pctf"]);

// ═══════════════════════════════════════════════════════════════════════════════
// Tailwind 전환 (ADR 001 결정 5 — Backtester 공용 컴포넌트 차례)
// 인라인 스타일 76개를 걷어낸다. ADR 이 금지한 CSS-in-JS 가 바로 이것이고, 토큰의 단일
// 진실은 계속 CSS 변수다 — Tailwind 임의값으로 **참조**만 하고 병렬 팔레트를 만들지 않는다.
//
// ★tone 은 CSS 변수로 넘긴다★ Tailwind 는 빌드 타임에 클래스를 뽑으므로 런타임 값을
// 클래스에 끼울 수 없다. 루트에 `--fp-*` 세 개를 **대입**하고(스타일링이 아니라 변수 선언 —
// shadcn 방식) 하위는 `bg-[var(--fp-accent)]` 로 참조한다. 하위 컴포넌트는 tone prop 없이
// 상속만으로 색을 얻으므로 시그니처도 단순해진다.
// ═══════════════════════════════════════════════════════════════════════════════
const RND = "rounded-[var(--bs-border-radius)]";
/** 셀렉트·텍스트 입력 공통 — 같은 스타일 객체가 6회 반복되고 있었다 */
const FIELD = `text-[13px] px-2 py-1.5 border border-[var(--border-strong)] ${RND} bg-[var(--bg-card)] text-[var(--text-primary)]`;
/** 숫자 입력 — 고정폭 + 모노 */
const NUMFIELD = `font-mono text-[13px] w-[90px] px-2.5 py-1.5 border border-[var(--border-strong)] ${RND} bg-[var(--bg-card)] text-[var(--text-primary)]`;
const PLABEL = "text-[11px] text-[var(--text-secondary)]";
const PANEL = `border border-[var(--border)] ${RND}`;
const TWOCOL = "grid grid-cols-[200px_minmax(0,1fr)] gap-[13px] items-stretch";
const PRIMARY = `flex items-center justify-center gap-[5px] text-[14px] text-white bg-[var(--fp-accent)] border-none ${RND} py-[11px] cursor-pointer`;
const ROW = "w-full text-left border-none cursor-pointer text-[13px] px-3 py-[5px] rounded-md";
const BADGE = "text-[9px] text-[var(--text-muted)] border border-[var(--border)] rounded px-1";

const baseToken = (f: GpFactor) => (/^\{[^{}]+\}$/.test(f.expr) ? f.expr : `{${f.name}}`);
// 팩터 → 백엔드 토큰(지원 판정·평가). Butler 표시명은 토큰과 다를 수 있으므로 토큰으로 판정.
const tokenOf = (f: GpFactor) => butlerToken(f);
const BUTLER_FLAT: { catLabel: string; f: GpFactor }[] = BUTLER_CATEGORIES.flatMap(
  (c) => c.groups.flatMap((g) => g.factors.map((f) => ({ catLabel: c.label, f }))),
);

export default function FactorPickerModal({ open, tone = "neutral", initial, allowNesting = false, onClose, onInsert }: {
  open: boolean; tone?: Tone; initial?: Partial<FactorPick>;
  /** 중첩(내부 함수)을 모든 단일시계열 함수에 허용 — 수식 빌더 전용. 기본은 순위/비율만(스크리너 호환). */
  allowNesting?: boolean;
  onClose: () => void; onInsert: (pick: FactorPick) => void;
}) {
  const [step, setStep] = useState<"factor" | "function">("factor");
  const [query, setQuery] = useState("");
  const [openCat, setOpenCat] = useState<string>(BUTLER_CATEGORIES[0]?.id ?? "");
  const [factor, setFactor] = useState<GpFactor | null>(null);
  const [support, setSupport] = useState<TokenSupportMap | null>(_supportCache);
  const [fnId, setFnId] = useState<string>(initial?.functionId ?? "base");
  const [params, setParams] = useState<Record<string, string>>(initial?.params ?? {});
  const [innerFnId, setInnerFnId] = useState<string>(initial?.innerFunctionId ?? "base");
  const [innerParams, setInnerParams] = useState<Record<string, string>>(initial?.innerParams ?? {});
  // 두 번째 피연산자 (비교/큰값/작은값=상수|팩터 선택, 변화율_팩터=팩터 필수)
  const [operand2Mode, setOperand2Mode] = useState<"value" | "factor">(initial?.factorToken2 ? "factor" : "value");
  const [factor2Name, setFactor2Name] = useState<string>(initial?.factorName2 ?? "");
  const [inner2FnId, setInner2FnId] = useState<string>(initial?.inner2FunctionId ?? "base");
  const [inner2Params, setInner2Params] = useState<Record<string, string>>(initial?.inner2Params ?? {});

  useEffect(() => {
    if (!open || support) return;
    backtestBridgeApi.conditionTokens()
      .then((s) => { _supportCache = s; setSupport(s); })
      .catch(() => {});  // 실패 시 배지 없이 기존 동작
  }, [open, support]);

  // Escape 로 닫기 — 기존에는 backdrop 클릭만 지원했다(CatalogueShell 과 동일한 계약).
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const supportInfo = (name: string): SupportInfo => {
    if (!support) return { ok: true };
    const g = support.supported[name];
    if (g) return { ok: true, group: g };
    return { ok: false, reason: support.unsupported[name] ?? support.default_reason };
  };

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? BUTLER_FLAT.filter((x) => x.f.name.toLowerCase().includes(q)) : [];
  }, [query]);
  const fn = FUNCTIONS_BY_ID[fnId];
  const selInfo = factor ? supportInfo(tokenOf(factor)) : null;

  const selectByName = (name: string) => {
    const hit = BUTLER_FLAT.find((x) => x.f.name === name || tokenOf(x.f) === name);
    if (hit) setFactor(hit.f);
  };
  const isCross = fnId === "rank" || fnId === "ratio";
  // 내부 함수(중첩) 허용 — 수식 빌더(allowNesting)에선 단일 시계열 함수 전부
  // (예: 이동평균(과거값({종가},1),20)). 그 외(스크리너)는 기존처럼 순위/비율만.
  // base(원값)·두 팩터 함수(비교/큰값/작은값/변화율_팩터)는 제외.
  const allowInner = allowNesting ? (fnId !== "base" && !TWO_FACTOR_IDS.has(fnId)) : isCross;
  const innerFn = FUNCTIONS_BY_ID[innerFnId];
  const tk = factor ? baseToken(factor) : "{팩터}";
  // 두 팩터 모드: 변화율_팩터는 항상, 비교/큰값/작은값은 '팩터' 선택 시
  const isTwoFactor = TWO_FACTOR_IDS.has(fnId) && (fnId === "pctf" || operand2Mode === "factor");
  const inner2Fn = FUNCTIONS_BY_ID[inner2FnId];
  const tk2 = factor2Name ? `{${factor2Name}}` : "{팩터2}";
  const expr2 = inner2FnId !== "base" ? fillTemplate(inner2Fn.preview, tk2, inner2Params) : tk2;
  // 중첩: 함수의 {f} 자리에 내부 지표식을 넣는다 — 이동평균(과거값({종가},1),20) · 순위(변화율_기간({종가},20),내림차순)
  const innerExpr = allowInner && innerFnId !== "base" ? fillTemplate(innerFn.preview, tk, innerParams) : tk;
  const expr = isTwoFactor ? `${fn.name}(${tk}, ${expr2})` : fillTemplate(fn.preview, innerExpr, params);
  const accent = TONES[tone];
  // 두 번째 팩터 후보: 지원 토큰만 (카테고리 optgroup)
  const factor2Options = useMemo(() =>
    BUTLER_CATEGORIES.map((c) => ({
      label: c.label,
      names: [...new Set(c.groups.flatMap((g) => g.factors)
        .filter((f) => supportInfo(tokenOf(f)).ok).map((f) => tokenOf(f)))],
    })).filter((g) => g.names.length > 0),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [support]);

  if (!open) return null;

  const setParam = (kind: string, idx: number, v: string) =>
    setParams((p) => ({ ...p, [paramKey(kind, idx)]: v }));
  const setInnerParam = (kind: string, idx: number, v: string) =>
    setInnerParams((p) => ({ ...p, [paramKey(kind, idx)]: v }));

  const pickInnerFn = (id: string) => {
    setInnerFnId(id);
    const f = FUNCTIONS_BY_ID[id];
    const init: Record<string, string> = {};
    (f?.params ?? []).forEach((p, i) => {
      if (p.kind !== "direction") init[paramKey(p.kind, i)] = p.default;
    });
    setInnerParams(init);
  };

  const pickInner2Fn = (id: string) => {
    setInner2FnId(id);
    const f = FUNCTIONS_BY_ID[id];
    const init: Record<string, string> = {};
    (f?.params ?? []).forEach((p, i) => {
      if (p.kind !== "direction") init[paramKey(p.kind, i)] = p.default;
    });
    setInner2Params(init);
  };

  const submit = () => {
    if (!factor || (selInfo && !selInfo.ok)) return;  // 미지원 팩터는 입력 차단
    if (isTwoFactor && !factor2Name) return;          // 두 팩터 함수는 두 번째 팩터 필수
    const withInner = allowInner && innerFnId !== "base";
    const withInner2 = isTwoFactor && inner2FnId !== "base";
    onInsert({
      factorName: factor.name, factorToken: tk, functionId: fnId, params, expr,
      innerFunctionId: withInner ? innerFnId : undefined,
      innerParams: withInner ? innerParams : undefined,
      factorName2: isTwoFactor ? factor2Name : undefined,
      factorToken2: isTwoFactor ? `{${factor2Name}}` : undefined,
      inner2FunctionId: withInner2 ? inner2FnId : undefined,
      inner2Params: withInner2 ? inner2Params : undefined,
    });
  };

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/45 p-[18px]"
      // ★유일하게 남는 style — 색 대입이 아니라 CSS 변수 선언이다★
      style={{
        "--fp-accent": accent.accent,
        "--fp-bg": accent.bg,
        "--fp-text": accent.text,
      } as React.CSSProperties}
    >
      {/* ★대화상자 계약★ — CatalogueShell 이 세 창에 준 것과 같은 수준을 여기에도 맞춘다.
          이 창은 role 도 aria-modal 도 Escape 도 없었다(backdrop 클릭만 닫힘). 그러면
          스크린리더가 모달임을 알 수 없고, AAS 안에 놓일 경우 WizardTracker 의 모달 예외
          (`[role="dialog"][aria-modal="true"]`)도 적용되지 않아 화살표 키에 창이 날아간다. */}
      <div onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-label="팩터 선택"
        className="w-full max-w-[600px] max-h-[82vh] overflow-auto bg-[var(--bg-card)] border border-[var(--border)] rounded-[var(--bs-border-radius-lg)] px-[18px] pt-[18px] pb-4 shadow-[var(--bs-box-shadow)]">

        {/* breadcrumb */}
        <div className="flex items-center justify-between mb-3.5">
          <div className="flex items-center gap-[7px]">
            <Crumb active={step === "factor"} onClick={() => setStep("factor")}>STEP1 팩터 선택</Crumb>
            <ChevronRight size={14} className="text-[var(--text-muted)]" />
            <Crumb active={step === "function"} disabled={!factor} onClick={() => factor && setStep("function")}>STEP2 함수 선택</Crumb>
          </div>
          <button type="button" onClick={onClose} aria-label="닫기" className="bg-none border-none cursor-pointer text-[var(--text-muted)] flex"><X size={16} /></button>
        </div>

        {step === "factor" ? (
          <>
            <div className={clsx("flex items-center gap-2 border border-[var(--border-strong)] px-[11px] py-2 mb-3.5", RND)}>
              <Search size={15} className="text-[var(--text-muted)]" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="조건을 단어로 입력하세요"
                autoFocus aria-label="조건을 단어로 입력하세요"
                className="flex-1 border-none outline-none bg-transparent text-[13px] text-[var(--text-primary)]" />
            </div>

            <div className={TWOCOL}>
              {/* left: category + factor list (or search results) */}
              <div className={clsx(PANEL, "p-[7px] max-h-[320px] overflow-auto flex flex-col gap-px")}>
                {query ? (
                  results.length ? results.map(({ catLabel, f }, i) => (
                    <FactorRow key={catLabel + f.name + i} f={f} active={factor?.name === f.name && factor?.expr === f.expr} sub={catLabel} info={supportInfo(tokenOf(f))} onClick={() => setFactor(f)} />
                  )) : <div className="text-xs text-[var(--text-muted)] px-[9px] py-2">검색 결과가 없습니다</div>
                ) : (
                  BUTLER_CATEGORIES.map((c) => {
                    const flat = c.groups.flatMap((g) => g.factors);
                    const okN = support ? flat.filter((f) => supportInfo(tokenOf(f)).ok).length : flat.length;
                    return (
                      <div key={c.id}>
                        <button type="button" onClick={() => setOpenCat(openCat === c.id ? "" : c.id)}
                          className={clsx("w-full flex items-center gap-1.5 text-[13px] bg-none border-none cursor-pointer px-[9px] py-[7px] text-left",
                            openCat === c.id ? "text-[var(--fp-text)]" : "text-[var(--text-secondary)]")}>
                          {openCat === c.id && <span className="w-[5px] h-[5px] rounded-full bg-[var(--fp-accent)]" />}
                          <span className="flex-1">{c.label}</span>
                          <span className="text-[11px] text-[var(--text-muted)]">{support ? `${okN}/${flat.length}` : flat.length}</span>
                          {openCat === c.id ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                        </button>
                        {openCat === c.id && (
                          <div className="pl-1.5 flex flex-col gap-px mb-1">
                            {c.groups.map((g) => (
                              <div key={g.label}>
                                <div className="text-[10.5px] font-semibold tracking-[0.02em] text-[var(--text-muted)] pt-[7px] px-[9px] pb-[3px]">{g.label}</div>
                                {g.factors.map((f, fi) => (
                                  <FactorRow key={g.label + f.name + fi} f={f} active={factor?.name === f.name && factor?.expr === f.expr} info={supportInfo(tokenOf(f))} onClick={() => setFactor(f)} />
                                ))}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>

              {/* right: selected factor detail */}
              <div className={clsx(PANEL, "p-3.5 flex flex-col")}>
                {factor ? (
                  <>
                    <div className="text-xs text-[var(--text-secondary)] mb-[7px]">선택된 팩터</div>
                    <div className={clsx("text-[17px] font-medium mb-[9px]",
                      selInfo && !selInfo.ok ? "text-[var(--text-muted)]" : "text-[var(--fp-text)]")}>{factor.name}</div>
                    <div className="font-mono text-xs text-[var(--text-secondary)]">{factor.expr}</div>
                    {selInfo && !selInfo.ok && (
                      <div className={clsx("mt-[11px] text-xs leading-relaxed text-[var(--danger)] bg-[var(--danger-light)] px-[11px] py-[9px]", RND)}>
                        미지원 — {selInfo.reason}
                      </div>
                    )}
                    {selInfo && !selInfo.ok && (support?.substitutes?.[factor.name]?.length ?? 0) > 0 && (
                      <div className="mt-[9px]">
                        <div className="text-[11px] text-[var(--text-secondary)] mb-[5px]">
                          대체 제안 — 같은 의도의 자체 팩터 (클릭해 선택)
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {support!.substitutes![factor.name].map((n) => (
                            <button key={n} type="button" onClick={() => selectByName(n)}
                              className={clsx("text-xs text-[var(--fp-text)] bg-[var(--fp-bg)] border border-[var(--fp-accent)] px-[9px] py-1 cursor-pointer", RND)}>
                              {n}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {selInfo?.ok && support && ["fundamental", "market", "macro", "flow", "score"].includes(selInfo.group ?? "") && (
                      <div className={clsx("mt-[11px] text-xs leading-relaxed text-[var(--text-secondary)] bg-[var(--bg-section)] px-[11px] py-[9px]", RND)}>
                        {selInfo.group === "fundamental" ? support.fundamental_note
                          : selInfo.group === "market" ? support.market_note
                          : selInfo.group === "macro" ? support.macro_note
                          : selInfo.group === "score" ? support.score_note
                          : support.flow_note}
                      </div>
                    )}
                    <div className="mt-auto pt-4 text-right">
                      <span className="text-xs text-[var(--fp-text)] inline-flex items-center gap-[3px]">이 팩터 더 알아보기 <ExternalLink size={12} /></span>
                    </div>
                  </>
                ) : (
                  <div className="m-auto text-[13px] text-[var(--text-muted)] text-center">
                    왼쪽에서 팩터를 선택하세요
                    {support && <div className="text-[11px] mt-2">회색 팩터는 미지원 — 평가 시 무시되므로 선택할 수 없습니다</div>}
                  </div>
                )}
              </div>
            </div>

            <button type="button" disabled={!factor || (selInfo ? !selInfo.ok : false)} onClick={() => setStep("function")}
              className={clsx("mt-4 w-full flex items-center justify-center gap-[5px] text-[14px] text-white border-none py-[11px]", RND,
                factor && (selInfo?.ok ?? true) ? "bg-[var(--fp-accent)] cursor-pointer" : "bg-[var(--border-strong)] cursor-not-allowed")}>
              다음 단계 <ArrowRight size={15} />
            </button>
          </>
        ) : (
          <>
            <div className={TWOCOL}>
              {/* left: function list */}
              <div className={clsx(PANEL, "p-[7px] max-h-[320px] overflow-auto flex flex-col gap-px")}>
                <GroupLabel dot>자주 쓰는 함수</GroupLabel>
                {FACTOR_FUNCTIONS.filter((f) => f.group === "common").map((f) => (
                  <FnRow key={f.id} name={f.name} active={f.id === fnId} onClick={() => { setFnId(f.id); setParams({}); }} />
                ))}
                <GroupLabel>전체</GroupLabel>
                {FACTOR_FUNCTIONS.filter((f) => f.group === "all").map((f) => (
                  <FnRow key={f.id} name={f.name} active={f.id === fnId} onClick={() => { setFnId(f.id); setParams({}); }} />
                ))}
              </div>

              {/* right: function detail + preview */}
              <div className={clsx(PANEL, "p-3.5 flex flex-col")}>
                <div className="text-[17px] font-medium text-[var(--text-primary)] mb-[9px]">{fn.name}</div>
                <div className="text-[13px] text-[var(--text-secondary)] leading-relaxed mb-3.5">{fn.desc}</div>

                {!isTwoFactor && fn.params.length > 0 && (
                  <div className="flex flex-wrap gap-2.5 mb-3.5">
                    {fn.params.map((p, i) => (
                      <div key={i} className="flex flex-col gap-1">
                        <span className={PLABEL}>{p.label}</span>
                        {p.kind === "direction" ? (
                          <select value={params[paramKey(p.kind, i)] ?? p.default} onChange={(e) => setParam(p.kind, i, e.target.value)}
                            className={FIELD}>
                            <option value="DESC">내림차순</option>
                            <option value="ASC">오름차순</option>
                          </select>
                        ) : (
                          <input type="number" value={params[paramKey(p.kind, i)] ?? p.default} onChange={(e) => setParam(p.kind, i, e.target.value)}
                            className={NUMFIELD} />
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* 두 번째 피연산자 — 비교/큰값/작은값: 상수|팩터 선택, 변화율_팩터: 팩터 필수 */}
                {TWO_FACTOR_IDS.has(fnId) && (
                  <div className="mb-3.5">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={PLABEL}>두 번째 피연산자</span>
                      {fnId !== "pctf" && (
                        <div className={clsx("flex gap-0 border border-[var(--border-strong)] overflow-hidden", RND)}>
                          {(["value", "factor"] as const).map((m) => (
                            <button key={m} type="button" onClick={() => setOperand2Mode(m)}
                              className={clsx("text-[11px] px-[9px] py-[3px] border-none cursor-pointer",
                                operand2Mode === m ? "bg-[var(--fp-accent)] text-white" : "bg-[var(--bg-card)] text-[var(--text-secondary)]")}>
                              {m === "value" ? "상수" : "팩터"}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                    {isTwoFactor && (
                      <div className="flex flex-wrap gap-2.5 items-end">
                        <select value={factor2Name} onChange={(e) => setFactor2Name(e.target.value)}
                          className={clsx(FIELD, "max-w-[220px]")}>
                          <option value="">팩터 선택…</option>
                          {factor2Options.map((g) => (
                            <optgroup key={g.label} label={g.label}>
                              {g.names.map((n) => <option key={n} value={n}>{n}</option>)}
                            </optgroup>
                          ))}
                        </select>
                        <select value={inner2FnId} onChange={(e) => pickInner2Fn(e.target.value)}
                          className={FIELD}>
                          <option value="base">원값 (팩터 그대로)</option>
                          {INNER_FUNCTIONS.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                        </select>
                        {inner2FnId !== "base" && inner2Fn.params.filter((p) => p.kind !== "direction").map((p, i) => (
                          <div key={i} className="flex flex-col gap-1">
                            <span className={PLABEL}>{p.label}</span>
                            <input type="number" value={inner2Params[paramKey(p.kind, i)] ?? p.default}
                              onChange={(e) => setInner2Params((q) => ({ ...q, [paramKey(p.kind, i)]: e.target.value }))}
                              className={NUMFIELD} />
                          </div>
                        ))}
                      </div>
                    )}
                    {fnId === "pctf" && (
                      <div className="text-[11px] text-[var(--text-muted)] mt-[5px]">
                        ((F1 − F2) / |F2|) × 100 — 예: 변화율_팩터({"{당기순이익}"}, 과거값({"{당기순이익}"}, 1년)) = 전년 대비 성장률
                      </div>
                    )}
                  </div>
                )}

                {/* 내부 지표(중첩) — 함수에 넣기 전 팩터에 먼저 적용 (예: 이동평균(과거값({종가},1),20)) */}
                {allowInner && (
                  <div className="mb-3.5">
                    <div className="text-[11px] text-[var(--text-secondary)] mb-1">
                      {isCross ? "내부 지표 (랭킹 대상 · 선택)" : "내부 지표 (먼저 적용할 함수 · 선택)"}
                    </div>
                    <div className="flex flex-wrap gap-2.5 items-end">
                      <select value={innerFnId} onChange={(e) => pickInnerFn(e.target.value)}
                        className={FIELD}>
                        <option value="base">원값 (팩터 그대로)</option>
                        {INNER_FUNCTIONS.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                      </select>
                      {innerFnId !== "base" && innerFn.params.filter((p) => p.kind !== "direction").map((p, i) => (
                        <div key={i} className="flex flex-col gap-1">
                          <span className={PLABEL}>{p.label}</span>
                          <input type="number" value={innerParams[paramKey(p.kind, i)] ?? p.default} onChange={(e) => setInnerParam(p.kind, i, e.target.value)}
                            className={NUMFIELD} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="text-xs text-[var(--text-secondary)] mb-1.5">조건식 미리보기</div>
                <div className={clsx("font-mono text-[15px] text-[var(--text-primary)] bg-[var(--bg-section)] px-[13px] py-[11px] break-all", RND)}>{expr}</div>
              </div>
            </div>

            <div className="mt-4 flex gap-2.5">
              <button type="button" onClick={() => setStep("factor")}
                className={clsx("flex-none flex items-center gap-1 text-[14px] text-[var(--text-secondary)] bg-none border border-[var(--border-strong)] px-[22px] py-[11px] cursor-pointer", RND)}>
                <ArrowLeft size={15} /> 이전 단계
              </button>
              <button type="button" onClick={submit}
                className={clsx(PRIMARY, "flex-1")}>
                <Check size={15} /> 입력
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const paramKey = (kind: string, idx: number) => (kind === "period" ? "n" : kind === "value" ? (idx >= 1 ? "v" : "v") : "dir");

// 아래 4개는 대화상자 서브트리 안에서만 쓰이므로 `--fp-*` 를 **상속**받는다.
// 그래서 tone prop 이 필요 없다 — 색은 CSS 가 전달한다.

function Crumb({ active, disabled, onClick, children }: { active: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      className={clsx("bg-none border-none p-0",
        disabled ? "cursor-default" : "cursor-pointer",
        active ? "text-[16px] font-medium text-[var(--text-primary)]" : "text-[14px] font-normal",
        !active && (disabled ? "text-[var(--text-muted)]" : "text-[var(--text-secondary)]"))}>
      {children}
    </button>
  );
}

function FactorRow({ f, active, sub, info, onClick }: {
  f: GpFactor; active: boolean; sub?: string; info?: SupportInfo; onClick: () => void;
}) {
  const unsupported = info ? !info.ok : false;
  return (
    <button type="button" onClick={onClick} title={unsupported ? `미지원 — ${info?.reason}` : undefined}
      className={clsx(ROW, "flex items-baseline gap-1.5",
        unsupported && "opacity-45",
        active ? "bg-[var(--fp-bg)] text-[var(--fp-text)]"
          : unsupported ? "bg-transparent text-[var(--text-muted)]"
          : "bg-transparent text-[var(--text-secondary)]")}>
      <span className={clsx("flex-1", unsupported && "line-through")}>{f.name}</span>
      {info?.ok && info.group && info.group !== "base" && info.group !== "ohlcv" && (
        <span className={BADGE}>
          {info.group === "fundamental" ? "재무" : info.group === "market" ? "시장"
            : info.group === "macro" ? "매크로" : info.group === "score" ? "점수 근사" : "수급"}
        </span>
      )}
      {unsupported && <span className={BADGE}>미지원</span>}
      {sub && <span className="text-[10px] text-[var(--text-muted)]">{sub}</span>}
    </button>
  );
}

function FnRow({ name, active, onClick }: { name: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className={clsx(ROW, active ? "bg-[var(--fp-bg)] text-[var(--fp-text)]"
        : "bg-transparent text-[var(--text-secondary)]")}>
      {name}
    </button>
  );
}

function GroupLabel({ dot, children }: { dot?: boolean; children: React.ReactNode }) {
  return (
    <div className={clsx("flex items-center gap-1.5 text-[13px] px-[9px] py-[7px]",
      dot ? "text-[var(--fp-text)]" : "text-[var(--text-secondary)] border-t border-[var(--border)] mt-[3px]")}>
      {dot && <span className="w-[5px] h-[5px] rounded-full bg-[var(--fp-accent)]" />}
      {children}
    </div>
  );
}
