"use client";
/**
 * 스튜디오·매크로 지능 패널이 같이 쓰는 작은 부품 (BU5c)
 * ==========================================================================
 * StudioPanel(차트 포함)을 매크로 첫 화면이 통째로 끌어오지 않게 따로 둔다.
 *  · ServerText — 서버 글의 `**굵게**` 만 굵게로 그린다(글자는 고치지 않는다)
 *  · RetryFail — 서버에 닿지 못한 실패(alert + 다시 시도). 서버가 답한 "미가용"과 다르다
 *  · ReasonWhy — 요건 코드가 붙은 사유를 사람 말로 + ★원래 사유는 "원래 사유 보기" 안에 그대로★(지우지 않는다)
 */
import { Fragment } from "react";
import { Notice } from "@/shared/ui/tx";
import { reasonKo, splitReason } from "./macroKo";

export function ServerText({ text }: { text: string }) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : <Fragment key={i}>{p}</Fragment>))}</>;
}

export function RetryFail({ title, onRetry }: { title: string; onRetry: () => void }) {
  return (
    <Notice tone="danger" title={title}>
      서버에 닿지 못했거나 계산이 실패했어요.
      <div className="ms-act"><button type="button" className="tx-btn tx-btn--sub" onClick={onRetry}>다시 시도</button></div>
    </Notice>
  );
}

export function ReasonWhy({ raw, rawClass }: { raw: string; rawClass: string }) {
  const lines = splitReason(raw).map((p) => ({ ko: reasonKo(p), raw: p.text }));
  return (
    <>
      <span className="ms-why">
        {lines.map((l, i) => (
          <span key={i} className="ms-why-l">{l.ko ?? <span data-server>{l.raw}</span>}</span>
        ))}
      </span>
      <details className={rawClass}>
        <summary>원래 사유 보기</summary>
        <span className="ms-raw-t" data-server>{raw}</span>
      </details>
    </>
  );
}
