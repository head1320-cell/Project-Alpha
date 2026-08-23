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
          {/* ★롱숏이면 현금 대신 gross/net 을 말한다 (P3)★ `?? 0` 으로 삼키면
              달러중립 목표가 "현금 0%" 로 보이는데, 그건 넷이 0 이라는 뜻이지
              현금이 없다는 뜻이 아니다. 두 축을 그대로 낸다. */}
          {tv.cash_weight == null
            ? ` · 롱숏 (gross ${(tv.gross_after ?? 0).toFixed(1)}% · net ${(tv.net_after ?? 0).toFixed(1)}%)`
            : tv.cash_weight > 0.05 ? ` · 현금 ${tv.cash_weight.toFixed(1)}%` : ""}
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
          {tv && tv.cash_weight != null && tv.cash_weight > 0.05 && (
            <tr className="as-rob-basis-cash">
              <td>현금</td>
              <td className="num">—</td>
              <td className="num">{tv.cash_weight.toFixed(1)}%</td>
              <td className="num">＋{tv.cash_weight.toFixed(1)}%p</td>
            </tr>
          )}
          {tv && tv.cash_weight == null && (
            <tr className="as-rob-basis-cash as-ls-exposure-row">
              <td>노출 (gross / net)</td>
              <td className="num">—</td>
              <td className="num">
                {(tv.gross_after ?? 0).toFixed(1)}% / {(tv.net_after ?? 0).toFixed(1)}%
              </td>
              <td className="num">—</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

/** 같은 시나리오를 **두 기준**으로 돌린 결과를 나란히 놓는다 (R0-B2).
 *
 *  ★목표가 없으면 숫자를 만들지 않는다★ 현재 값을 복사하거나 0 을 넣지 않고
 *  미계산으로 남긴다 — 이 화면이 A6-Z 에서 이미 초록 `+0.0%` 로 값을 치른 자리다. */
export function BasisShock({ current, target, targetMissing }: {
  current: number | null;
  target: number | null;
  /** 목표 기준 자체가 없다(최적화 결과 없음 등). 계산 실패와 구분한다. */
  targetMissing: boolean;
}) {
  const num = (v: number | null) =>
    v != null && Number.isFinite(v)
      ? <b className="num" style={{ color: v >= 0 ? "var(--color-bull)" : "var(--color-bear)" }}>
          {v >= 0 ? "+" : ""}{v.toFixed(1)}%</b>
      : <span className="aas-cmp-na">미계산</span>;

  const delta = (current != null && target != null
    && Number.isFinite(current) && Number.isFinite(target))
    ? target - current : null;

  return (
    <div className="as-rob-kpi2">
      <span><em>현재 보유</em> {num(current)}</span>
      <span><em>목표</em> {targetMissing ? <span className="aas-cmp-na">미계산</span> : num(target)}</span>
      <span><em>Δ</em> {delta == null
        ? <span className="aas-cmp-na">미계산</span>
        : <b className="num">{delta >= 0 ? "+" : ""}{delta.toFixed(1)}%p</b>}</span>
    </div>
  );
}
