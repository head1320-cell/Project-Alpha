"use client";
/**
 * 달마다 격자 — 해 × 달, 등락 두 팔 색(세기는 |수익| 비례) + 칸 안 숫자(부호) · 글자는 잉크 (2026-11-09 · 캔버스 성과 그림 문법 §4.1 시트 ③)
 * ★서버 `periods.monthly` 그대로★ — 없는 달은 빈 칸(0 이 아니다), 일부만 있는 달은 점선 테두리 + 아래 글. 이 격자가 곧 표라 쌍둥이가 따로 없다.
 */
import type { CSSProperties } from "react";
import { fmtSignedPct, type PerfView } from "./perfView";

const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);
const MIX_MIN = 8, MIX_MAX = 45;      // 색 세기(%) — 글자(잉크)가 늘 읽히는 범위

export function MonthGrid({ view }: { view: PerfView }) {
  const rows = view.periods?.monthly ?? null;
  if (!rows) return <p className="pg-note">달마다 수익은 이 결과에 없어요 — 서버가 기간별 수익을 주지 않았어요.</p>;
  if (!rows.length) return <p className="pg-note">달마다 수익을 셀 만큼 긴 곡선이 아니에요.</p>;
  const years = [...new Set(rows.map((r) => r.year))].sort((a, b) => a - b);
  const byKey = new Map(rows.map((r) => [`${r.year}-${String(r.month).padStart(2, "0")}`, r]));
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(r.return_pct)));
  const anyPartial = rows.some((r) => r.partial);
  return (
    <div className="pf-months-wrap">
      <table className="pf-months">
        <thead><tr><th className="pf-months-y">해</th>{MONTHS.map((m) => <th key={m}>{m}월</th>)}</tr></thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <th className="pf-months-y">{y}</th>
              {MONTHS.map((m) => {
                const key = `${y}-${String(m).padStart(2, "0")}`;
                const r = byKey.get(key);
                if (!r) return <td key={m} className="pf-month pf-month--none" />;
                const mix = MIX_MIN + ((MIX_MAX - MIX_MIN) * Math.abs(r.return_pct)) / max;
                return (
                  <td key={m} className="pf-month" data-month={key} data-partial={r.partial ? "true" : "false"}
                      data-tone={r.return_pct >= 0 ? "up" : "down"} style={{ "--pf-mix": `${mix.toFixed(0)}%` } as CSSProperties}>
                    {fmtSignedPct(r.return_pct)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="pg-note pf-months-note">
        빨강은 오른 달, 파랑은 내린 달이고 진할수록 폭이 커요. 빈 칸은 자료가 없는 달이에요(0 이 아니에요).
        {anyPartial ? " 점선 테두리는 그 달의 일부만 있는 달이에요 — 그 기간 수익 그대로예요." : ""}
      </p>
    </div>
  );
}
