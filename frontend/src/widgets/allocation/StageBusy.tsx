"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// StageBusy — 결과 패널이 "계산 중"을 **글로** 말하는 한 줄 (A4-X1)
// ─────────────────────────────────────────────────────────────────────────────
// ★왜 새로 만드는가★
// `.as-loading` 은 5개 스테이지의 결과 패널 9곳에 붙어 `opacity: .55` 로 내용을
// 흐리게 만들고 있었다. 그중 4곳(optimize ×2 · ThreeWayPanel · ScenarioThreeWay)은
// 계산 중에도 **이전 결과를 계속 렌더한다**. 즉 화면에 있던 것은 "흐릿하지만 읽히는,
// 낡은 숫자"였다 — 읽지 말라는 신호가 색 하나뿐이고, 그 색은 AA 아래였다.
//
// 그래서 흐림을 걷어내고 대신 이 줄을 넣는다. `stale` 이 참이면 아래 숫자가 이전
// 계산 결과라는 사실을 **문장으로** 적는다. A1 이 superseded 배너에서 내린 결론과
// 같다: 데이터를 가리지 말고, 무엇을 보고 있는지 말해 줄 것.
//
// shared/ui 의 LoadingState(`.tstate-*`)는 화면 한복판을 차지하는 블록이라
// 카드 머리글 아래 한 줄로는 크다. 어휘는 같고 밀도만 다르다.
// ═══════════════════════════════════════════════════════════════════════════════

export function StageBusy({ label, stale = false }: {
  label: string;
  /** 계산 중에도 이전 결과가 화면에 남아 있는가. 남아 있다면 반드시 그렇게 적는다. */
  stale?: boolean;
}) {
  return (
    <div className="as-busy" role="status" aria-live="polite">
      <span className="as-busy-spin" aria-hidden="true" />
      <span className="as-busy-l">{label}</span>
      {stale && <span className="as-busy-stale">아래 수치는 이전 계산 결과입니다</span>}
    </div>
  );
}
