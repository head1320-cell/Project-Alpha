"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// FactorPickerModal — §8.1 의 네 번째 창. CatalogueShell 위로 이전 (Phase 11c).
//
// 무엇이 바뀌었나: **단계가 없어졌다**
// ─────────────────────────────────────────────────────────────────────────────
// 이 창만 2단계였다(STEP1 팩터 → STEP2 함수, 브레드크럼·다음/이전 단계). 셸은 단계 모델이
// 없고 우측 패널을 `selectedId` 가 있을 때만 그린다 — 즉 "좌측에서 고르면 우측이 열린다" 가
// 이미 단계 없는 같은 흐름이다. 그래서 브레드크럼을 셸 위에 다시 얹지 않고 걷어냈다.
// 대신 옛 STEP1 의 선택 상세(미지원 사유·대체 제안·그룹 노트)와 STEP2 의 함수 설정이 우측
// 패널에 **함께** 놓인다 — 고른 팩터를 보면서 함수를 정할 수 있어 왕복이 줄어든다.
//
// ★잃지 않으려고 셸을 먼저 넓혔다★
// 카테고리별 지원 개수(`countLabel`) · 그룹 소제목(`groupLabel`) · 창 색조(`styleVars`) 는
// 셸에 없던 능력이다. 창을 셸에 맞추려고 기능을 줄이면 "창 통일" 이 아니라 기능 축소다.
//
// 미지원 표기도 셸의 규칙을 따른다 — 사유를 **툴팁이 아니라 행에** 적는다. 이전 구현은
// `title=` 로 숨겼고, 그건 나머지 세 창이 의도적으로 하지 않는 일이었다.
//
// ★출력 계약(`FactorPick`)은 한 글자도 바뀌지 않는다★
// 소비자가 둘이다(백테스터 수식 빌더 · 스크리너). 특히 `innerFunctionId`·`factorToken2`·
// `inner2Params` 는 화면에 거의 드러나지 않으면서 수식에는 그대로 나타난다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { type GpFactor } from "@/entities/backtest/factorCatalog";
import { BUTLER_CATEGORIES, butlerToken } from "@/entities/backtest/butlerFactors";
import { FACTOR_FUNCTIONS, FUNCTIONS_BY_ID, INNER_FUNCTIONS, fillTemplate } from "@/entities/backtest/factorFunctions";
import { backtestBridgeApi } from "@/entities/backtest/bridgeApi";
import { type TokenSupportMap } from "@/entities/backtest/bridgeModel";
import { TONES, type Tone } from "@/shared/ui/kit";
import { CatalogueShell, type CatalogueItem } from "@/shared/ui/CatalogueShell";
// clsx 만 쓴다 — 공용 `cn` 은 tailwind-merge 를 함께 끌어와 이 두 라우트에 +7 kB 를 더한다.
// 여기서는 충돌하는 유틸리티를 합칠 일이 없다(조건부로 이어붙이기만 한다).
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

const RND = "rounded-[var(--bs-border-radius)]";
/** 셀렉트·텍스트 입력 공통 */
const FIELD = `text-[13px] px-2 py-1.5 border border-[var(--border-strong)] ${RND} bg-[var(--bg-card)] text-[var(--text-primary)]`;
/** 숫자 입력 — 고정폭 + 모노 */
const NUMFIELD = `font-mono text-[13px] w-[90px] px-2.5 py-1.5 border border-[var(--border-strong)] ${RND} bg-[var(--bg-card)] text-[var(--text-primary)]`;
const PLABEL = "text-[11px] text-[var(--text-secondary)]";
const FNROW = "w-full text-left border-none cursor-pointer text-[13px] px-3 py-[5px] rounded-md";

const baseToken = (f: GpFactor) => (/^\{[^{}]+\}$/.test(f.expr) ? f.expr : `{${f.name}}`);
// 팩터 → 백엔드 토큰(지원 판정·평가). Butler 표시명은 토큰과 다를 수 있으므로 토큰으로 판정.
const tokenOf = (f: GpFactor) => butlerToken(f);

/**
 * 항목 신원은 **경로**로 만든다 — 팩터 이름은 유일하지 않다(실측: `종합점수` 가 두 카테고리에
 * 있다). 이름을 id 로 쓰면 셸의 key 가 충돌하고 선택이 엉뚱한 행으로 간다.
 */
const idOf = (cat: string, group: string, name: string) => `${cat}/${group}/${name}`;

interface FlatFactor { catId: string; catLabel: string; group: string; f: GpFactor; id: string }

const BUTLER_FLAT: FlatFactor[] = BUTLER_CATEGORIES.flatMap((c) =>
  c.groups.flatMap((g) => g.factors.map((f) => ({
    catId: c.id, catLabel: c.label, group: g.label, f, id: idOf(c.id, g.label, f.name),
  }))),
);
const BY_ID = new Map(BUTLER_FLAT.map((x) => [x.id, x]));

const GROUP_BADGE: Record<string, string> = {
  fundamental: "재무", market: "시장", macro: "매크로", score: "점수 근사", flow: "수급",
};

export default function FactorPickerModal({ open, tone = "neutral", initial, allowNesting = false, onClose, onInsert }: {
  open: boolean; tone?: Tone; initial?: Partial<FactorPick>;
  /** 중첩(내부 함수)을 모든 단일시계열 함수에 허용 — 수식 빌더 전용. 기본은 순위/비율만(스크리너 호환). */
  allowNesting?: boolean;
  onClose: () => void; onInsert: (pick: FactorPick) => void;
}) {
  const [family, setFamily] = useState<string>(BUTLER_CATEGORIES[0]?.id ?? "");
  const [selId, setSelId] = useState<string | null>(null);
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

  const supportInfo = useMemo(() => (name: string): SupportInfo => {
    if (!support) return { ok: true };
    const g = support.supported[name];
    if (g) return { ok: true, group: g };
    return { ok: false, reason: support.unsupported[name] ?? support.default_reason };
  }, [support]);

  const toItem = useMemo(() => (x: FlatFactor): CatalogueItem => {
    const info = supportInfo(tokenOf(x.f));
    return {
      id: x.id,
      label: x.f.name,
      description: x.f.expr,
      // 검색 결과는 카테고리를 가로지르므로 어디 소속인지 행에 적어 준다.
      meta: x.catLabel,
      kindBadge: info.ok && info.group ? GROUP_BADGE[info.group] : undefined,
      groupLabel: x.group,
      available: info.ok,
      unavailableReason: info.reason,
      searchExtra: [tokenOf(x.f), x.catLabel, x.group],
    };
  }, [supportInfo]);

  const allItems = useMemo(() => BUTLER_FLAT.map(toItem), [toItem]);
  const items = useMemo(
    () => BUTLER_FLAT.filter((x) => x.catId === family).map(toItem),
    [family, toItem],
  );

  // 카테고리별 지원 개수 — 지원맵이 없으면 전체 개수만. 추정치로 채우지 않는다.
  const families = useMemo(() => BUTLER_CATEGORIES.map((c) => {
    const flat = c.groups.flatMap((g) => g.factors);
    const ok = support ? flat.filter((f) => supportInfo(tokenOf(f)).ok).length : null;
    return {
      id: c.id, label: c.label,
      countLabel: ok === null ? String(flat.length) : `${ok}/${flat.length}`,
    };
  }), [support, supportInfo]);

  const sel = selId ? BY_ID.get(selId) : undefined;
  const factor = sel?.f ?? null;
  const selInfo = factor ? supportInfo(tokenOf(factor)) : null;

  const fn = FUNCTIONS_BY_ID[fnId];
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
  // 중첩: 함수의 {f} 자리에 내부 지표식을 넣는다
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
  [supportInfo]);

  const setParam = (kind: string, idx: number, v: string) =>
    setParams((p) => ({ ...p, [paramKey(kind, idx)]: v }));
  const setInnerParam = (kind: string, idx: number, v: string) =>
    setInnerParams((p) => ({ ...p, [paramKey(kind, idx)]: v }));

  const initParams = (id: string): Record<string, string> => {
    const f = FUNCTIONS_BY_ID[id];
    const init: Record<string, string> = {};
    (f?.params ?? []).forEach((p, i) => {
      if (p.kind !== "direction") init[paramKey(p.kind, i)] = p.default;
    });
    return init;
  };
  const pickInnerFn = (id: string) => { setInnerFnId(id); setInnerParams(initParams(id)); };
  const pickInner2Fn = (id: string) => { setInner2FnId(id); setInner2Params(initParams(id)); };

  // 미지원 팩터와 두 번째 팩터 누락은 **적용 버튼 상태로** 막는다 — 선택 자체는 막지 않는다.
  // 고를 수조차 없으면 왜 못 쓰는지 볼 기회가 없다.
  const applyDisabled = !factor || (selInfo ? !selInfo.ok : false) || (isTwoFactor && !factor2Name);

  const submit = () => {
    if (!factor || applyDisabled) return;
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
    <CatalogueShell
      open={open}
      onClose={onClose}
      title="팩터 선택"
      subtitle="팩터를 고르고 함수를 씌워 조건식 한 항을 만듭니다"
      ariaLabel="팩터 선택"
      searchPlaceholder="조건을 단어로 입력하세요"
      families={families}
      family={family}
      onFamilyChange={setFamily}
      items={items}
      allItems={allItems}
      selectedId={selId}
      onSelect={(i) => setSelId(i.id)}
      applyLabel="입력"
      onApply={submit}
      applyDisabled={applyDisabled}
      note="지원 여부는 백엔드 /condition-tokens 가 단일 진실 공급원입니다 — 미지원 팩터는 평가에서 무시되므로 적용할 수 없습니다."
      // ★색조는 스타일이 아니라 CSS 변수 대입이다★ `--t-accent` 를 덮으면 셸의 기존
      // `.tfm-*` 규칙이 그대로 다시 물든다 — 새 CSS 없이 매수/매도 문맥 색을 지킨다.
      styleVars={{
        "--t-accent": accent.accent,
        "--fp-accent": accent.accent,
        "--fp-bg": accent.bg,
        "--fp-text": accent.text,
      } as React.CSSProperties}
    >
      {/* ── 고른 팩터 상세 (옛 STEP1 우측) ── */}
      {factor && (
        <div className="mb-3.5">
          <div className="text-xs text-[var(--text-secondary)] mb-[5px]">선택된 팩터</div>
          <div className={clsx("text-[17px] font-medium",
            selInfo && !selInfo.ok ? "text-[var(--text-muted)]" : "text-[var(--fp-text)]")}>
            {factor.name}
          </div>
          <div className="font-mono text-xs text-[var(--text-secondary)]">{factor.expr}</div>

          {selInfo && !selInfo.ok && (
            <div className={clsx("mt-[9px] text-xs leading-relaxed text-[var(--danger)] bg-[var(--danger-light)] px-[11px] py-[9px]", RND)}>
              미지원 — {selInfo.reason}
            </div>
          )}
          {selInfo && !selInfo.ok && (support?.substitutes?.[factor.name]?.length ?? 0) > 0 && (
            <div className="mt-[9px]">
              <div className="text-[11px] text-[var(--text-secondary)] mb-[5px]">
                대체 제안 — 같은 의도의 자체 팩터 (클릭해 선택)
              </div>
              <div className="flex flex-wrap gap-1.5">
                {support!.substitutes![factor.name].map((n) => {
                  // 카탈로그에 없는 대체 제안은 **누를 수 없게** 둔다. 눌러도 아무 일이
                  // 없는 버튼은 사용자가 자기 조작을 의심하게 만든다.
                  const hit = BUTLER_FLAT.find((x) => x.f.name === n || tokenOf(x.f) === n);
                  return (
                    <button key={n} type="button" disabled={!hit}
                      onClick={() => hit && setSelId(hit.id)}
                      className={clsx("text-xs text-[var(--fp-text)] bg-[var(--fp-bg)] border border-[var(--fp-accent)] px-[9px] py-1", RND,
                        hit ? "cursor-pointer" : "opacity-50 cursor-not-allowed")}>
                      {n}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {selInfo?.ok && support && ["fundamental", "market", "macro", "flow", "score"].includes(selInfo.group ?? "") && (
            <div className={clsx("mt-[9px] text-xs leading-relaxed text-[var(--text-secondary)] bg-[var(--bg-section)] px-[11px] py-[9px]", RND)}>
              {selInfo.group === "fundamental" ? support.fundamental_note
                : selInfo.group === "market" ? support.market_note
                : selInfo.group === "macro" ? support.macro_note
                : selInfo.group === "score" ? support.score_note
                : support.flow_note}
            </div>
          )}
        </div>
      )}

      {/* ── 함수 (옛 STEP2) ── */}
      <div className="text-xs text-[var(--text-secondary)] mb-1.5">함수</div>
      <div className={clsx("max-h-[168px] overflow-auto flex flex-col gap-px mb-2.5 border border-[var(--border)]", RND)}>
        <GroupLabel dot>자주 쓰는 함수</GroupLabel>
        {FACTOR_FUNCTIONS.filter((f) => f.group === "common").map((f) => (
          <FnRow key={f.id} name={f.name} active={f.id === fnId}
            onClick={() => { setFnId(f.id); setParams({}); }} />
        ))}
        <GroupLabel>전체</GroupLabel>
        {FACTOR_FUNCTIONS.filter((f) => f.group === "all").map((f) => (
          <FnRow key={f.id} name={f.name} active={f.id === fnId}
            onClick={() => { setFnId(f.id); setParams({}); }} />
        ))}
      </div>

      <div className="text-[13px] text-[var(--text-secondary)] leading-relaxed mb-2.5">{fn.desc}</div>

      {!isTwoFactor && fn.params.length > 0 && (
        <div className="flex flex-wrap gap-2.5 mb-3.5">
          {fn.params.map((p, i) => (
            <div key={i} className="flex flex-col gap-1">
              <span className={PLABEL}>{p.label}</span>
              {p.kind === "direction" ? (
                <select value={params[paramKey(p.kind, i)] ?? p.default} aria-label={p.label}
                  onChange={(e) => setParam(p.kind, i, e.target.value)} className={FIELD}>
                  <option value="DESC">내림차순</option>
                  <option value="ASC">오름차순</option>
                </select>
              ) : (
                <input type="number" value={params[paramKey(p.kind, i)] ?? p.default} aria-label={p.label}
                  onChange={(e) => setParam(p.kind, i, e.target.value)} className={NUMFIELD} />
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
                aria-label="두 번째 팩터" className={clsx(FIELD, "fp-factor2 max-w-[220px]")}>
                <option value="">팩터 선택…</option>
                {factor2Options.map((g) => (
                  <optgroup key={g.label} label={g.label}>
                    {g.names.map((n) => <option key={n} value={n}>{n}</option>)}
                  </optgroup>
                ))}
              </select>
              <select value={inner2FnId} onChange={(e) => pickInner2Fn(e.target.value)}
                aria-label="두 번째 팩터의 내부 지표" className={clsx(FIELD, "fp-inner2-fn")}>
                <option value="base">원값 (팩터 그대로)</option>
                {INNER_FUNCTIONS.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
              {inner2FnId !== "base" && inner2Fn.params.filter((p) => p.kind !== "direction").map((p, i) => (
                <div key={i} className="flex flex-col gap-1">
                  <span className={PLABEL}>{p.label}</span>
                  <input type="number" aria-label={p.label}
                    value={inner2Params[paramKey(p.kind, i)] ?? p.default}
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

      {/* 내부 지표(중첩) — 함수에 넣기 전 팩터에 먼저 적용 */}
      {allowInner && (
        <div className="mb-3.5">
          <div className="text-[11px] text-[var(--text-secondary)] mb-1">
            {isCross ? "내부 지표 (랭킹 대상 · 선택)" : "내부 지표 (먼저 적용할 함수 · 선택)"}
          </div>
          <div className="flex flex-wrap gap-2.5 items-end">
            {/* ★`fp-inner-fn` 은 E2E 계약이다★ 중첩은 화면에서 가장 눈에 안 띄면서 수식에는
                그대로 나타나는 출력이라, 이 지점을 지켜보지 않으면 조용히 사라진다. */}
            <select value={innerFnId} onChange={(e) => pickInnerFn(e.target.value)}
              aria-label="내부 지표" className={clsx(FIELD, "fp-inner-fn")}>
              <option value="base">원값 (팩터 그대로)</option>
              {INNER_FUNCTIONS.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
            {innerFnId !== "base" && innerFn.params.filter((p) => p.kind !== "direction").map((p, i) => (
              <div key={i} className="flex flex-col gap-1">
                <span className={PLABEL}>{p.label}</span>
                <input type="number" aria-label={p.label}
                  value={innerParams[paramKey(p.kind, i)] ?? p.default}
                  onChange={(e) => setInnerParam(p.kind, i, e.target.value)} className={NUMFIELD} />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="text-xs text-[var(--text-secondary)] mb-1.5">조건식 미리보기</div>
      {/* `fp-preview` 는 E2E 계약이다 — 토큰 문자열({시가총액})은 목록 행·선택 상세·미리보기
          세 곳에 동시에 나타나므로, 범위를 좁히지 않으면 단정이 어느 것을 본 것인지 알 수 없다. */}
      <div className={clsx("fp-preview font-mono text-[15px] text-[var(--text-primary)] bg-[var(--bg-section)] px-[13px] py-[11px] break-all mb-3.5", RND)}>
        {expr}
      </div>
    </CatalogueShell>
  );
}

const paramKey = (kind: string, idx: number) => (kind === "period" ? "n" : kind === "value" ? (idx >= 1 ? "v" : "v") : "dir");

// 아래 둘은 대화상자 서브트리 안에서만 쓰이므로 `--fp-*` 를 **상속**받는다.
// 그래서 tone prop 이 필요 없다 — 색은 CSS 가 전달한다.

function FnRow({ name, active, onClick }: { name: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      className={clsx(FNROW, active ? "bg-[var(--fp-bg)] text-[var(--fp-text)]"
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
