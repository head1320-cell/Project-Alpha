"use client";
/**
 * 첫 화면 히어로 · 근거 짚기 (BU8a 개정 2)
 * ==========================================================================
 * "답마다 근거가 함께 붙어요" 를 말로만 하지 않고, 바로 옆 ★서버가 지금 내는 답 카드★에서 그 근거 칩을 짚어 보인다.
 * 단추 셋(어디서 왔는지 · 무엇으로 쟀는지 · 언제 기준인지)을 누르거나 올리면 히어로에 `data-focus` 를 붙이고, CSS 가
 * 답 카드의 같은 `data-ev` 칩(출처 · 잰 모형 · 기준 시각 — `MacroAnswer` 가 붙인다)에 테두리를 두르고 나머지를 흐린다.
 * ★칩 글자는 서버 값이다★ 여기서는 어느 칩을 짚을지만 고른다(새 판단·새 숫자 없음).
 * 처음 열 때 한 번만 저절로 차례로 짚고 멈춘다(손이 닿으면 바로 그친다) · 감속 모션이면 저절로 돌지 않는다.
 */
import { useEffect, useRef, useState, type CSSProperties } from "react";

const EV = [
  { k: "source", t: "어디서 왔는지", d: "답에 쓴 데이터가 연습용인지 실데이터인지, 서버 연결 상태로 밝혀요." },
  { k: "model", t: "무엇으로 쟀는지", d: "어떤 모형으로 쟀는지 적어서, 무엇을 재지 않았는지도 알 수 있어요." },
  { k: "asof", t: "언제 기준인지", d: "언제 계산한 값인지 기준 시각을 붙여요." },
] as const;
type Key = (typeof EV)[number]["k"];

export function EvidencePointer({ className = "", style }: { className?: string; style?: CSSProperties }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const touched = useRef(false);
  const [on, setOn] = useState<Key | null>(null);

  useEffect(() => {
    const hero = ref.current?.closest<HTMLElement>(".ld-hero");
    if (!hero) return;
    if (on) hero.setAttribute("data-focus", on);
    else hero.removeAttribute("data-focus");
  }, [on]);

  // 처음 한 번만 저절로 차례로 짚는다 — 답 카드가 떠오른 뒤에.
  useEffect(() => {
    if (typeof window.matchMedia !== "function" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const seq: (Key | null)[] = ["source", "model", "asof", null];
    const timers = seq.map((k, j) => window.setTimeout(() => { if (!touched.current) setOn(k); }, 2600 + j * 1600));
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, []);

  const pick = (k: Key | null) => { touched.current = true; setOn(k); };
  const cur = EV.find((e) => e.k === on);
  return (
    <div className={`ld-ev ${className}`.trim()} style={style} ref={ref} onMouseLeave={() => { if (touched.current) setOn(null); }}>
      <p className="ld-ev-k">답마다 근거가 함께 붙어요</p>
      <div className="ld-ev-row" role="group" aria-label="답 카드에서 짚어 볼 근거">
        {EV.map((e) => (
          <button key={e.k} type="button" className="ld-ev-btn" data-ev={e.k} aria-pressed={on === e.k}
                  onClick={() => pick(e.k)} onMouseEnter={() => pick(e.k)} onFocus={() => pick(e.k)}>
            <i aria-hidden />{e.t}
          </button>
        ))}
      </div>
      <p className="ld-ev-d">{cur ? cur.d : "누르면 답 카드에서 그 근거를 짚어 드려요."}</p>
    </div>
  );
}
