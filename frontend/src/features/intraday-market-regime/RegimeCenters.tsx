"use client";
/**
 * 비중을 더한 답의 국면별 중심 — 마지막 적합 창에서 각 국면 성분의 평균(20거래일 로그 수익 · 실현 변동성(연율) · 하루 유형 비중) (구현 계획 §7.6 · K5)
 * 국면이 비중의 어느 높이에 앉았는지 읽는 표다. 숫자는 서버 값을 서식만 한다. 관측이며 결정에 쓰지 않는다 — 국면에 뜻을 붙인 이름은 없다.
 */
import { useId } from "react";
import type { RegimeCenter } from "@/entities/intraday";
import { dailyText, probText, stateFill, volText } from "./format";

export function RegimeCenters({ centers, k }: { centers: RegimeCenter[]; k: number }) {
  const capId = useId();
  return (
    <div className="itd-mr-tablebox itd-mrs-centersbox">
      <p className="itd-mr-cap" id={capId}>비중을 더한 답의 국면별 중심(마지막 적합 창의 성분 평균 · 관측이며 결정에 쓰지 않습니다)</p>
      <div className="itd-mr-scroll" role="region" tabIndex={0} aria-labelledby={capId}>
        <table className="pg-table itd-mrs-centers" aria-labelledby={capId}>
          <thead>
            <tr><th>국면</th><th className="pg-td-num">20거래일 수익(로그)</th><th className="pg-td-num">실현 변동성(연율)</th><th className="pg-td-num">하루 유형 비중</th></tr>
          </thead>
          <tbody>
            {centers.map((c) => (
              <tr key={c.state} data-state={c.state}>
                <td><i className="itd-mr-chip" style={{ background: stateFill(c.state, k) }} aria-hidden="true" />국면 {c.state}</td>
                <td className="pg-td-num">{dailyText(c.r20)}</td>
                <td className="pg-td-num">{volText(c.sigma20)}</td>
                <td className="pg-td-num">{probText(c.share)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
