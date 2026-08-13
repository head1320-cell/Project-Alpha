"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// StressBasisBand — 스트레스가 **무엇을** 스트레스하는지 밝히는 밴드 (R0-B)
//
// ★고치는 결함★ 06 STRESS 의 비중 소비자 셋이 전부 **현재 보유**를 썼다:
//   · `slices/ScenarioContext.tsx:62`  stress(holdingsMap, …)
//   · `stress/page.tsx:61`             stressCorrelation({weights: holdingsMap})
//   · `stress/page.tsx:166`            ScenarioThreeWay holdings={holdingsMap}
// 즉 "이 배분이 충격에 견디는가"를 묻는 화면이 **주문할 배분이 아니라 지금 들고 있는 것**을
// 답했다. 타이밍 오버레이로 노출을 줄여도 스트레스 숫자는 꿈쩍하지 않았다.
//
// ★목표로 갈아끼우지 않는다★ 갈아끼우면 같은 자리에서 답이 조용히 바뀌고, 사용자는 어느
// 쪽을 보고 있는지 알 수 없다. 그래서 **둘 다 놓고 대조**한다.
//
// ★컴파일러는 계속 하나다★ 목표는 `dry_run` 으로 서버에서 컴파일한다 — 화면이 다시
// `before × exposure` 를 계산하면 R0 이 없앤 갈라짐이 그대로 돌아온다.
// ═══════════════════════════════════════════════════════════════════════════════
import React from "react";
import { useQuery } from "@tanstack/react-query";

import { targetVersionApi, type TargetVersion } from "@/entities/allocation/targetVersion";

/** 목표 기준을 컴파일한다. 최적화 결과가 없으면 **요청하지 않는다**(목표가 없다는 사실). */
export function useTargetBasis(
  optimized: Record<string, number> | null,
  overlay: { exposure: number; source: string } | null,
) {
  return useQuery<TargetVersion>({
    queryKey: ["allocation", "target-version", "preview", optimized, overlay],
    queryFn: () => targetVersionApi.create({
      base_weights: optimized!,
      overlay: overlay ? { exposure: overlay.exposure, source: overlay.source } : null,
      dry_run: true,
    }),
    enabled: !!optimized && Object.keys(optimized).length > 0,
    staleTime: 60_000,
  });
}

/** 두 비중 맵이 (부동소수 여유 안에서) 같은가. */
function sameWeights(a: Record<string, number>, b: Record<string, number>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) if (Math.abs((a[k] ?? 0) - (b[k] ?? 0)) > 0.05) return false;
  return keys.size > 0;
}

export function StressBasisBand({
  current, tv, nameOf, reason,
}: {
  current: Record<string, number>;
  /** 목표 버전 — 없으면 `null`(최적화 결과 없음 등). */
  tv: TargetVersion | null;
  nameOf: (code: string) => string;
  /** 목표가 없는 이유. 없으면 화면이 "왜 없는지"를 말할 수 없다. */
  reason: string;
}) {
  const codes = Array.from(new Set([...Object.keys(current), ...Object.keys(tv?.final_weights ?? {})]));
  const identical = !!tv && sameWeights(current, tv.final_weights) && (tv.cash_weight ?? 0) < 0.05;

  return (
    <section className="as-card as-rob-basis">
      <div className="as-card-title">
        스트레스 기준
        <span className="as-note-inline">현재 보유와 목표를 나란히 — 무엇을 스트레스하는지 밝힙니다</span>
      </div>

      {!tv ? (
        // ★현재 값을 복사해 목표인 척하지 않는다★ 없으면 없다고 적는다.
        <div className="as-note as-rob-basis-na">
          목표 기준 <b>미계산</b> — {reason} 아래 결과는 <b>현재 보유</b> 기준입니다.
        </div>
      ) : identical ? (
        // 같은 숫자가 두 번 찍혀 둘 중 하나가 틀린 것처럼 보이는 함정(A5 의 중복 HHI) 방지.
        <div className="as-note as-rob-basis-same">
          두 기준이 <b>같습니다</b> — 타이밍 오버레이가 없고 보유 비중이 최적화 비중과 일치합니다.
          아래 결과의 두 열이 같은 것은 오류가 아니라 그 사실입니다.
        </div>
      ) : (
        <div className="as-note as-rob-basis-meta">
          목표 버전{tv.overlay ? ` · 노출 ${(tv.overlay.exposure * 100).toFixed(0)}%` : " · 오버레이 없음"}
          {tv.cash_weight > 0.05 && ` · 현금 ${tv.cash_weight.toFixed(1)}%`}
        </div>
      )}

      <table className="as-metrics as-rob-basis-table">
        <thead>
          <tr>
            <th scope="col">자산</th>
            <th scope="col">현재 보유</th>
            <th scope="col">목표</th>
            <th scope="col">Δ</th>
          </tr>
        </thead>
        <tbody>
          {codes.map((c) => {
            const cur = current[c] ?? 0;
            const t = tv ? (tv.final_weights[c] ?? 0) : null;
            return (
              <tr key={c}>
                <td>{nameOf(c)}</td>
                <td className="num">{cur.toFixed(1)}%</td>
                <td className="num">{t == null ? <span className="aas-cmp-na">미계산</span> : `${t.toFixed(1)}%`}</td>
                <td className="num as-rob-basis-d">
                  {t == null ? <span className="aas-cmp-na">미계산</span> : `${(t - cur).toFixed(1)}%p`}
                </td>
              </tr>
            );
          })}
          {tv && tv.cash_weight > 0.05 && (
            <tr className="as-rob-basis-cash">
              <td>현금</td>
              <td className="num">—</td>
              <td className="num">{tv.cash_weight.toFixed(1)}%</td>
              <td className="num">＋{tv.cash_weight.toFixed(1)}%p</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
