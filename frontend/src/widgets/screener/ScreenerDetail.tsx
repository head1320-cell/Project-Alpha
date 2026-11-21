// ═══════════════════════════════════════════════════════════════════════════════
// 종목 찾기 — 고른 줄의 상세 본문 (U1-c)
//   · 그릇이 둘이다: 넓은 창(1280px 이상)에서는 표 옆 판, 그보다 좁으면 시트. ★본문은 이 부품 하나★ — 한 번에 한 그릇만 그린다.
//   · 값은 서버 값 그대로. 값이 없으면 `N/A` + 사유(0 · 빈칸 · 줄표가 아니다 — '미상 ≠ 0'). 사유는 관측 그대로다(응답에 값이 없다).
//   · 합성 표시는 표와 같은 근거(서버의 mock 게이트)다 — 밀도 · 그릇과 무관하게 보인다.
//   · 클래스(`scr-sheet-figs` · `scr-sheet-fig` · `scr-sheet-act`)는 E2E 계약이다(시트 때의 이름 그대로).
// ═══════════════════════════════════════════════════════════════════════════════
import Link from "next/link";
import type { ReactNode } from "react";
import type { ScreenerItem } from "@/shared/model/domain";
import { num, priceWon } from "@/shared/lib/krFormat";
import { Chips, Unknown } from "@/shared/ui/tx";

/** 값이 없는 까닭 — 서버 응답에 그 값이 없다는 관측이다(왜 없는지는 화면이 알지 못한다). */
export const NO_VALUE_REASON = "응답에 값이 없습니다";

const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

function Fig({ label, children }: { label: string; children: ReactNode }) {
  return <div className="scr-sheet-fig"><dt>{label}</dt><dd>{children}</dd></div>;
}

export function ScreenerDetail({ item, cols, mock }: {
  item: ScreenerItem;
  /** 표에 보이는 값 열 — 같은 이름 · 같은 소수 자리로 적는다. */
  cols: { id: string; label: string; digits: number }[];
  mock: boolean;
}) {
  const na = <Unknown reason={NO_VALUE_REASON} />;
  return (
    <>
      <dl className="scr-sheet-figs">
        <Fig label="현재가">{finite(item.current_price) ? priceWon(item.current_price) : na}</Fig>
        <Fig label="종합점수">{finite(item.composite_score) ? num(item.composite_score, 1) : na}</Fig>
        <Fig label="판정"><span className="tx-chip" data-tone="plain">{item.verdict || "판정 없음"}</span></Fig>
        {finite(item.market_cap_억) && <Fig label="시가총액">{num(Math.round(item.market_cap_억))}억</Fig>}
        {cols.map((c) => {
          const v = (item as Record<string, unknown>)[c.id];
          return <Fig key={c.id} label={c.label}>{finite(v) ? num(v, c.digits) : na}</Fig>;
        })}
      </dl>
      <Chips items={mock ? [{ label: "합성 시세", tone: "practice" }] : []} label="이 값의 근거" />
      <div className="scr-sheet-act">
        <Link className="tx-btn tx-btn--main" href={`/insights?code=${item.stock_code}`}>기업 분석 열기</Link>
        <Link className="tx-btn tx-btn--sub" href={`/allocation?tickers=${item.stock_code}`}>설계에 추가</Link>
      </div>
    </>
  );
}
