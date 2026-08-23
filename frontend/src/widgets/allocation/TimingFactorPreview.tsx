"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// TimingFactorPreview — 팩터 과거 미리보기 (스펙 §8.1 요구 4, Phase 6b-2)
//   값 / 임계 / **3-상태** / 상태전환 횟수를 우측 패널에 그린다.
//
// 정직성 규칙이 이 컴포넌트의 대부분을 결정한다
// ─────────────────────────────────────────────────────────────────────────────
// · **결측은 빈칸으로 둔다.** 0 으로 찍거나 선을 이어 버리면 데이터가 있었던 것처럼 보인다.
//   결측 구간은 막대를 그리지 않고 회색 바닥만 남긴다.
// · **한계(limitations)를 접어 숨기지 않는다.** 월 표본이라 일간 팩터의 전환 횟수가
//   과소집계된다는 사실은 이 숫자를 읽는 데 필요한 정보다.
// · 값이 없으면 "없음" 이라고 쓴다. 미리보기 실패는 에러가 아니라 상태다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import type { TimingFactorHistory, SignalStateValue } from "@/entities/allocation";

const STATE_LABEL: Record<SignalStateValue, string> = {
  risk_on: "위험-온", risk_off: "위험-오프", unavailable: "결측",
};

function fmt(v: number | null, unit: string): string {
  if (v == null) return "없음";
  const s = Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3);
  return unit ? `${s} ${unit}` : s;
}

export function TimingFactorPreview({ history, loading, error, unit }: {
  history?: TimingFactorHistory;
  loading?: boolean;
  error?: boolean;
  unit?: string;
}) {
  if (loading) return <div className="tfm-hist"><div className="as-empty">미리보기 계산 중…</div></div>;
  if (error) {
    return (
      <div className="tfm-hist">
        <div className="as-err">미리보기를 불러오지 못했습니다.</div>
      </div>
    );
  }
  if (!history) return null;

  const pts = history.points;
  const vals = pts.map((p) => p.value).filter((v): v is number => v != null);
  const lo = vals.length ? Math.min(...vals, history.threshold) : 0;
  const hi = vals.length ? Math.max(...vals, history.threshold) : 1;
  const span = hi - lo || 1;
  const pct = (v: number) => ((v - lo) / span) * 100;
  const latest = pts.length ? pts[pts.length - 1] : null;

  return (
    <div className="tfm-hist">
      <div className="tfm-hist-l">
        과거 미리보기
        <span className="as-note-inline">
          {pts.length ? `${pts.length}개 표본 · ${history.step === "month" ? "월" : history.step} 간격` : "표본 없음"}
        </span>
      </div>

      {pts.length > 0 && (
        <>
          <div className="tfm-hist-bars" role="img"
            aria-label={`과거 ${pts.length}개 표본의 신호 상태 추이`}>
            {pts.map((p) => (
              <span key={p.months_back}
                className={`tfm-hist-bar s-${p.state}`}
                title={`${p.months_back === 0 ? "현재" : `${p.months_back}개월 전`} · ` +
                  `${fmt(p.value, unit ?? "")} · ${STATE_LABEL[p.state]}`}
                style={p.value == null ? undefined : { height: `${Math.max(4, pct(p.value))}%` }} />
            ))}
          </div>

          <div className="tfm-hist-stats">
            <span>현재 <b className="num">{fmt(latest?.value ?? null, unit ?? "")}</b></span>
            <span>임계 <b className="num">{fmt(history.threshold, unit ?? "")}</b>
              <em className="as-note-inline">{history.direction === "above" ? "초과 시 온" : "미만 시 온"}</em>
            </span>
            <span>상태 <b className={`tfm-hist-st s-${latest?.state ?? "unavailable"}`}>
              {STATE_LABEL[latest?.state ?? "unavailable"]}</b></span>
            <span>전환 <b className="num">{history.state_changes}</b>회</span>
          </div>

          {history.unavailable_count > 0 && (
            <div className="tfm-hist-miss">
              {history.unavailable_count}개 표본은 값을 얻지 못해 <b>빈칸</b>입니다 — 0 으로 채우지 않았습니다.
            </div>
          )}
        </>
      )}

      {history.limitations.length > 0 && (
        <ul className="tfm-hist-lim">
          {history.limitations.map((t, i) => <li key={i}>{t.replace(/\*\*/g, "")}</li>)}
        </ul>
      )}
    </div>
  );
}
