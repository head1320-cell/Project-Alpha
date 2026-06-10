"use client";
// 대상 경로: frontend/src/components/backtest/FactorPickerModal.tsx
//
// 젠포트식 팩터 선택 창. STEP1(팩터 선택) → STEP2(함수 선택) → "입력" 시
// onInsert 로 { factorName, expr, functionId, params } 를 부모(조건식 에디터)에 전달.

import { useMemo, useState } from "react";
import { Search, X, ChevronRight, ChevronDown, ArrowRight, ArrowLeft, Check, ExternalLink } from "lucide-react";
import { FACTOR_CATEGORIES, searchFactors, type GpFactor } from "../../lib/backtest/factorCatalog";
import { FACTOR_FUNCTIONS, FUNCTIONS_BY_ID, INNER_FUNCTIONS, fillTemplate } from "../../lib/backtest/factorFunctions";
import { TONES, type Tone } from "./kit";

export interface FactorPick {
  factorName: string;
  factorToken: string;   // {고가}
  functionId: string;
  params: Record<string, string>;
  expr: string;          // 이동평균({고가}, 20) · 순위(변화율_기간({종가}, 20), 내림차순)
  // 중첩(순위/비율 전용): 랭킹 대상을 파생 지표로 — 예: 순위(변화율_기간(종가,20))
  innerFunctionId?: string;
  innerParams?: Record<string, string>;
}

const R = "var(--bs-border-radius)";
const RL = "var(--bs-border-radius-lg)";

const baseToken = (f: GpFactor) => (/^\{[^{}]+\}$/.test(f.expr) ? f.expr : `{${f.name}}`);

export default function FactorPickerModal({ open, tone = "neutral", initial, onClose, onInsert }: {
  open: boolean; tone?: Tone; initial?: Partial<FactorPick>;
  onClose: () => void; onInsert: (pick: FactorPick) => void;
}) {
  const [step, setStep] = useState<"factor" | "function">("factor");
  const [query, setQuery] = useState("");
  const [openCat, setOpenCat] = useState<string>(FACTOR_CATEGORIES[0]?.id ?? "");
  const [factor, setFactor] = useState<GpFactor | null>(null);
  const [fnId, setFnId] = useState<string>(initial?.functionId ?? "base");
  const [params, setParams] = useState<Record<string, string>>(initial?.params ?? {});
  const [innerFnId, setInnerFnId] = useState<string>(initial?.innerFunctionId ?? "base");
  const [innerParams, setInnerParams] = useState<Record<string, string>>(initial?.innerParams ?? {});

  const results = useMemo(() => searchFactors(query), [query]);
  const fn = FUNCTIONS_BY_ID[fnId];
  const isCross = fnId === "rank" || fnId === "ratio";
  const innerFn = FUNCTIONS_BY_ID[innerFnId];
  const tk = factor ? baseToken(factor) : "{팩터}";
  // 중첩: 순위/비율의 {f} 자리에 내부 지표식을 넣는다 — 순위(변화율_기간({종가}, 20), 내림차순)
  const innerExpr = isCross && innerFnId !== "base" ? fillTemplate(innerFn.preview, tk, innerParams) : tk;
  const expr = fillTemplate(fn.preview, innerExpr, params);
  const accent = TONES[tone];

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

  const submit = () => {
    if (!factor) return;
    const withInner = isCross && innerFnId !== "base";
    onInsert({
      factorName: factor.name, factorToken: tk, functionId: fnId, params, expr,
      innerFunctionId: withInner ? innerFnId : undefined,
      innerParams: withInner ? innerParams : undefined,
    });
  };

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 18 }}
    >
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: "100%", maxWidth: 600, maxHeight: "82vh", overflow: "auto", background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: RL, padding: "18px 18px 16px", boxShadow: "var(--bs-box-shadow)" }}>

        {/* breadcrumb */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <Crumb active={step === "factor"} onClick={() => setStep("factor")}>STEP1 팩터 선택</Crumb>
            <ChevronRight size={14} style={{ color: "var(--text-muted)" }} />
            <Crumb active={step === "function"} disabled={!factor} onClick={() => factor && setStep("function")}>STEP2 함수 선택</Crumb>
          </div>
          <button type="button" onClick={onClose} aria-label="닫기" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", display: "flex" }}><X size={16} /></button>
        </div>

        {step === "factor" ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid var(--border-strong)", borderRadius: R, padding: "8px 11px", marginBottom: 14 }}>
              <Search size={15} style={{ color: "var(--text-muted)" }} />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="조건을 단어로 입력하세요"
                style={{ flex: 1, border: "none", outline: "none", background: "transparent", fontSize: 13, color: "var(--text-primary)" }} />
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "200px minmax(0,1fr)", gap: 13, alignItems: "stretch" }}>
              {/* left: category + factor list (or search results) */}
              <div style={{ border: "1px solid var(--border)", borderRadius: R, padding: 7, maxHeight: 320, overflow: "auto", display: "flex", flexDirection: "column", gap: 1 }}>
                {query ? (
                  results.length ? results.map(({ category, factor: f }) => (
                    <FactorRow key={category.id + f.name} f={f} active={factor?.name === f.name} tone={tone} sub={category.label} onClick={() => setFactor(f)} />
                  )) : <div style={{ fontSize: 12, color: "var(--text-muted)", padding: "8px 9px" }}>검색 결과가 없습니다</div>
                ) : (
                  FACTOR_CATEGORIES.map((c) => (
                    <div key={c.id}>
                      <button type="button" onClick={() => setOpenCat(openCat === c.id ? "" : c.id)}
                        style={{ width: "100%", display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: openCat === c.id ? accent.text : "var(--text-secondary)", background: "none", border: "none", cursor: "pointer", padding: "7px 9px", textAlign: "left" }}>
                        {openCat === c.id && <span style={{ width: 5, height: 5, borderRadius: "50%", background: accent.accent }} />}
                        <span style={{ flex: 1 }}>{c.label}</span>
                        <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{c.factors.length}</span>
                        {openCat === c.id ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      </button>
                      {openCat === c.id && (
                        <div style={{ paddingLeft: 6, display: "flex", flexDirection: "column", gap: 1, marginBottom: 4 }}>
                          {c.factors.map((f) => (
                            <FactorRow key={f.name} f={f} active={factor?.name === f.name} tone={tone} onClick={() => setFactor(f)} />
                          ))}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              {/* right: selected factor detail */}
              <div style={{ border: "1px solid var(--border)", borderRadius: R, padding: 14, display: "flex", flexDirection: "column" }}>
                {factor ? (
                  <>
                    <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 7 }}>선택된 팩터</div>
                    <div style={{ fontSize: 17, fontWeight: 500, color: accent.text, marginBottom: 9 }}>{factor.name}</div>
                    <div style={{ fontFamily: "var(--bs-font-mono)", fontSize: 12, color: "var(--text-secondary)" }}>{factor.expr}</div>
                    <div style={{ marginTop: "auto", paddingTop: 16, textAlign: "right" }}>
                      <span style={{ fontSize: 12, color: accent.text, display: "inline-flex", alignItems: "center", gap: 3 }}>이 팩터 더 알아보기 <ExternalLink size={12} /></span>
                    </div>
                  </>
                ) : (
                  <div style={{ margin: "auto", fontSize: 13, color: "var(--text-muted)", textAlign: "center" }}>왼쪽에서 팩터를 선택하세요</div>
                )}
              </div>
            </div>

            <button type="button" disabled={!factor} onClick={() => setStep("function")}
              style={{ marginTop: 16, width: "100%", display: "flex", alignItems: "center", justifyContent: "center", gap: 5, fontSize: 14, color: "#fff", background: factor ? accent.accent : "var(--border-strong)", border: "none", borderRadius: R, padding: "11px 0", cursor: factor ? "pointer" : "not-allowed" }}>
              다음 단계 <ArrowRight size={15} />
            </button>
          </>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "200px minmax(0,1fr)", gap: 13, alignItems: "stretch" }}>
              {/* left: function list */}
              <div style={{ border: "1px solid var(--border)", borderRadius: R, padding: 7, maxHeight: 320, overflow: "auto", display: "flex", flexDirection: "column", gap: 1 }}>
                <GroupLabel tone={tone} dot>자주 쓰는 함수</GroupLabel>
                {FACTOR_FUNCTIONS.filter((f) => f.group === "common").map((f) => (
                  <FnRow key={f.id} name={f.name} active={f.id === fnId} tone={tone} onClick={() => { setFnId(f.id); setParams({}); }} />
                ))}
                <GroupLabel tone={tone}>전체</GroupLabel>
                {FACTOR_FUNCTIONS.filter((f) => f.group === "all").map((f) => (
                  <FnRow key={f.id} name={f.name} active={f.id === fnId} tone={tone} onClick={() => { setFnId(f.id); setParams({}); }} />
                ))}
              </div>

              {/* right: function detail + preview */}
              <div style={{ border: "1px solid var(--border)", borderRadius: R, padding: 14, display: "flex", flexDirection: "column" }}>
                <div style={{ fontSize: 17, fontWeight: 500, color: "var(--text-primary)", marginBottom: 9 }}>{fn.name}</div>
                <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, marginBottom: 14 }}>{fn.desc}</div>

                {fn.params.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
                    {fn.params.map((p, i) => (
                      <div key={i} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>{p.label}</span>
                        {p.kind === "direction" ? (
                          <select value={params[paramKey(p.kind, i)] ?? p.default} onChange={(e) => setParam(p.kind, i, e.target.value)}
                            style={{ fontSize: 13, padding: "6px 8px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }}>
                            <option value="DESC">내림차순</option>
                            <option value="ASC">오름차순</option>
                          </select>
                        ) : (
                          <input type="number" value={params[paramKey(p.kind, i)] ?? p.default} onChange={(e) => setParam(p.kind, i, e.target.value)}
                            style={{ fontFamily: "var(--bs-font-mono)", fontSize: 13, width: 90, padding: "6px 10px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* 내부 지표(중첩) — 순위/비율의 랭킹 대상을 파생 지표로 (예: 20일 수익률 순위) */}
                {isCross && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ fontSize: 11, color: "var(--text-secondary)", marginBottom: 4 }}>내부 지표 (랭킹 대상 · 선택)</div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "flex-end" }}>
                      <select value={innerFnId} onChange={(e) => pickInnerFn(e.target.value)}
                        style={{ fontSize: 13, padding: "6px 8px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }}>
                        <option value="base">원값 (팩터 그대로)</option>
                        {INNER_FUNCTIONS.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                      </select>
                      {innerFnId !== "base" && innerFn.params.filter((p) => p.kind !== "direction").map((p, i) => (
                        <div key={i} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          <span style={{ fontSize: 11, color: "var(--text-secondary)" }}>{p.label}</span>
                          <input type="number" value={innerParams[paramKey(p.kind, i)] ?? p.default} onChange={(e) => setInnerParam(p.kind, i, e.target.value)}
                            style={{ fontFamily: "var(--bs-font-mono)", fontSize: 13, width: 90, padding: "6px 10px", border: "1px solid var(--border-strong)", borderRadius: R, background: "var(--bg-card)", color: "var(--text-primary)" }} />
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 6 }}>조건식 미리보기</div>
                <div style={{ fontFamily: "var(--bs-font-mono)", fontSize: 15, color: "var(--text-primary)", background: "var(--bg-section)", borderRadius: R, padding: "11px 13px", wordBreak: "break-all" }}>{expr}</div>
              </div>
            </div>

            <div style={{ marginTop: 16, display: "flex", gap: 10 }}>
              <button type="button" onClick={() => setStep("factor")}
                style={{ flex: "0 0 auto", display: "flex", alignItems: "center", gap: 4, fontSize: 14, color: "var(--text-secondary)", background: "none", border: "1px solid var(--border-strong)", borderRadius: R, padding: "11px 22px", cursor: "pointer" }}>
                <ArrowLeft size={15} /> 이전 단계
              </button>
              <button type="button" onClick={submit}
                style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 5, fontSize: 14, color: "#fff", background: accent.accent, border: "none", borderRadius: R, padding: "11px 0", cursor: "pointer" }}>
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

function Crumb({ active, disabled, onClick, children }: { active: boolean; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled}
      style={{ background: "none", border: "none", cursor: disabled ? "default" : "pointer", padding: 0,
        fontSize: active ? 16 : 14, fontWeight: active ? 500 : 400,
        color: active ? "var(--text-primary)" : disabled ? "var(--text-muted)" : "var(--text-secondary)" }}>
      {children}
    </button>
  );
}

function FactorRow({ f, active, tone, sub, onClick }: { f: GpFactor; active: boolean; tone: Tone; sub?: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      style={{ display: "flex", alignItems: "baseline", gap: 6, width: "100%", textAlign: "left", border: "none", cursor: "pointer",
        fontSize: 13, padding: "5px 12px", borderRadius: 6,
        background: active ? TONES[tone].bg : "transparent", color: active ? TONES[tone].text : "var(--text-secondary)" }}>
      <span style={{ flex: 1 }}>{f.name}</span>
      {sub && <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{sub}</span>}
    </button>
  );
}

function FnRow({ name, active, tone, onClick }: { name: string; active: boolean; tone: Tone; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick}
      style={{ width: "100%", textAlign: "left", border: "none", cursor: "pointer", fontSize: 13, padding: "5px 12px", borderRadius: 6,
        background: active ? TONES[tone].bg : "transparent", color: active ? TONES[tone].text : "var(--text-secondary)" }}>
      {name}
    </button>
  );
}

function GroupLabel({ tone, dot, children }: { tone: Tone; dot?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: dot ? TONES[tone].text : "var(--text-secondary)", padding: "7px 9px", borderTop: dot ? undefined : "1px solid var(--border)", marginTop: dot ? undefined : 3 }}>
      {dot && <span style={{ width: 5, height: 5, borderRadius: "50%", background: TONES[tone].accent }} />}
      {children}
    </div>
  );
}
