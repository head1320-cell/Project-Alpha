"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// StressScenarioModal — 06 STRESS 통합 시나리오 창
//   시나리오가 세 곳에 흩어져 있었다: 좌측 레일의 가상 4 + 역사 4 버튼, 우측
//   KrScenarioPack 카드 안의 국내 7 버튼. 검색도 분류도 없고, 미가용 사유는 disabled
//   버튼 툴팁에만 있었다. 15종을 한 창에서 검색·분류·선택하고 강도(severity)까지
//   같은 자리에서 맞춘다. .tfm-* 스타일 공유(타이밍·알파 팩터 창과 동일 조작감).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { allocationApi, type StressScenarioItem } from "@/lib/allocationApi";

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
  const [q, setQ] = useState("");
  const [fam, setFam] = useState<string>("hypothetical");
  const [sel, setSel] = useState<StressScenarioItem | null>(null);

  const groups = catQ.data?.groups ?? [];
  const flat = useMemo(() => groups.flatMap((g) => g.items), [groups]);
  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return groups.find((g) => g.family === fam)?.items ?? [];
    return flat.filter((i) =>
      i.label.toLowerCase().includes(s) || i.description.toLowerCase().includes(s) ||
      i.source.toLowerCase().includes(s) || i.id.toLowerCase().includes(s));
  }, [q, fam, groups, flat]);

  // 창을 열면 현재 선택된 시나리오를 그대로 보여준다(맥락 유지)
  useEffect(() => {
    if (!open) { setQ(""); setSel(null); return; }
    const cur = flat.find((i) => i.id === selectedId);
    if (cur) { setSel(cur); setFam(cur.family); }
  }, [open, selectedId, flat]);

  if (!open) return null;
  return (
    <div className="tfm-backdrop" onClick={onClose}>
      <div className="tfm" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="스트레스 시나리오 선택">
        <div className="tfm-head">
          <div className="tfm-title">스트레스 시나리오 <span className="as-note-inline">가상 · 역사 리플레이 · 국내팩을 한 창에서</span></div>
          <button className="as-x" onClick={onClose} aria-label="닫기">×</button>
        </div>

        <div className="tfm-body">
          <div className="tfm-left">
            <input className="tfm-search" placeholder="시나리오 검색 — 이름·설명·출처"
              value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
            {!q && (
              <div className="tfm-fams">
                {(catQ.data?.families ?? []).map((f) => (
                  <button key={f.id} className={fam === f.id ? "on" : ""} onClick={() => setFam(f.id)}>{f.label}</button>
                ))}
              </div>
            )}
            <div className="tfm-list">
              {catQ.isLoading && <div className="as-empty">시나리오 불러오는 중…</div>}
              {catQ.isError && <div className="as-err">시나리오를 불러오지 못했습니다.</div>}
              {!catQ.isLoading && results.length === 0 && <div className="as-empty">검색 결과가 없습니다</div>}
              {results.map((i) => (
                <button key={i.id} className={`tfm-row${sel?.id === i.id ? " on" : ""}${!i.available ? " off" : ""}`}
                  onClick={() => setSel(i)}>
                  <span className="tfm-row-t">
                    {i.label}
                    {selectedId === i.id && <em className="tfm-kind">선택됨</em>}
                    {!i.available && <em className="tfm-off">미가용</em>}
                  </span>
                  <span className="tfm-row-d">{i.description}</span>
                  {/* 미가용 사유를 툴팁이 아니라 목록에 그대로 — 왜 못 쓰는지 바로 보이게 */}
                  <span className="tfm-row-p">{i.available ? i.source : i.reason || "데이터 미보유"}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="tfm-right">
            {!sel ? (
              <div className="as-empty">왼쪽에서 시나리오를 선택하세요.</div>
            ) : (
              <>
                <div className="tfm-sel-t">{sel.label}</div>
                <div className="tfm-sel-d">{sel.description}</div>
                <div className="tfm-row-p">출처 · {sel.source}</div>

                {sel.severity_applies ? (
                  <label className="as-param">
                    <span>시나리오 강도 <b className="num">{severity.toFixed(2)}×</b></span>
                    <input type="range" min={0.25} max={3} step={0.25} value={severity}
                      onChange={(e) => onSeverity(parseFloat(e.target.value))} />
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
                <button className="as-fb-apply" disabled={!sel.available}
                  onClick={() => { onPick(sel); onClose(); }}>
                  이 시나리오로 검증 →
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
