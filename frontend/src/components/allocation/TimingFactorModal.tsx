"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// TimingFactorModal — AAS TIMING 통합 팩터 창
//   백테스터 팩터 창(FactorPickerModal) UX를 타이밍 시그널에 적용: 검색 + 패밀리 카테고리
//   + 팩터 목록 + 파라미터/임계 설정. 기존 카나리(13612W·절대모멘텀·이동평균·지표)와
//   신규 팩터(평균절대모멘텀·가속·이격도·돌파·오버나이트·Defense First)를 한 창에서 관리.
//   저장 단위는 TimingRule 공통 스키마(백엔드 dataclass와 1:1).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  allocationApi, type CanaryInput, type CanarySignalType, type TimingFactorMeta,
} from "@/lib/allocationApi";

const PARAM_LABEL: Record<string, string> = {
  months: "개월", days: "일", max_months: "최대 개월", ma_days: "이평 일수", k: "k 계수",
};

/** 팩터 메타 → 기본 카나리(=TimingRule 스펙의 시그널 부분) */
export function canaryFromFactor(f: TimingFactorMeta): CanaryInput {
  const p = { ...(f.params || {}) };
  const primary = Object.keys(p)[0];
  return {
    kind: f.id === "indicator" ? "indicator" : "asset",
    id: f.id === "indicator" ? "VIXCLS" : "SPY",
    signal: f.id as CanarySignalType,
    lookback: primary ? Number(p[primary]) || 12 : 12,
    threshold: f.default_threshold,
    direction: f.default_direction,
    params: p,
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
  const [q, setQ] = useState("");
  const [fam, setFam] = useState<string>("momentum");
  const [sel, setSel] = useState<TimingFactorMeta | null>(null);
  const [draft, setDraft] = useState<CanaryInput | null>(null);

  const groups = catQ.data?.groups ?? [];
  const flat = useMemo(() => groups.flatMap((g) => g.factors), [groups]);
  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return groups.find((g) => g.family === fam)?.factors ?? [];
    return flat.filter((f) =>
      f.label.toLowerCase().includes(s) || f.desc.toLowerCase().includes(s) ||
      f.id.includes(s) || f.provenance.toLowerCase().includes(s));
  }, [q, fam, groups, flat]);

  useEffect(() => { if (!open) { setQ(""); setSel(null); setDraft(null); } }, [open]);

  const pick = (f: TimingFactorMeta) => { setSel(f); setDraft(canaryFromFactor(f)); };
  const upd = (patch: Partial<CanaryInput>) => setDraft((d) => (d ? { ...d, ...patch } : d));
  const updParam = (k: string, v: number) =>
    setDraft((d) => (d ? { ...d, params: { ...(d.params || {}), [k]: v }, lookback: v } : d));

  if (!open) return null;
  return (
    <div className="tfm-backdrop" onClick={onClose}>
      <div className="tfm" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="타이밍 팩터 추가">
        <div className="tfm-head">
          <div className="tfm-title">타이밍 팩터 <span className="as-note-inline">시그널을 골라 파라미터를 맞추세요</span></div>
          <button className="as-x" onClick={onClose} aria-label="닫기">×</button>
        </div>

        <div className="tfm-body">
          {/* 좌: 검색 + 패밀리 + 목록 */}
          <div className="tfm-left">
            <input className="tfm-search" placeholder="팩터 검색 — 이름·설명·출처"
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
              {results.map((f) => (
                <button key={f.id} className={`tfm-row${sel?.id === f.id ? " on" : ""}`} onClick={() => pick(f)}>
                  <span className="tfm-row-t">
                    {f.label}
                    {!f.existing && <em className="tfm-new">NEW</em>}
                  </span>
                  <span className="tfm-row-d">{f.desc}</span>
                  <span className="tfm-row-p">{f.provenance}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 우: 선택 팩터 설정 */}
          <div className="tfm-right">
            {!draft || !sel ? (
              <div className="as-empty">왼쪽에서 팩터를 선택하세요.</div>
            ) : (
              <>
                <div className="tfm-sel-t">{sel.label}</div>
                <div className="tfm-sel-d">{sel.desc}</div>
                <label className="as-tm-set">
                  <span>{sel.id === "indicator" ? "매크로 시리즈 id" : "대상 티커"}</span>
                  <input className="as-tm-id" value={draft.id}
                    onChange={(e) => upd({ id: e.target.value.toUpperCase() })} />
                </label>
                {Object.entries(sel.params || {}).map(([k, dflt]) => (
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
                <button className="as-fb-apply" onClick={() => { onAdd(draft); onClose(); }}>
                  이 팩터 추가 →
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
