"use client";
/**
 * 첫 화면 히어로 바탕 · 포인터를 따라 밝아지는 점 + 그림의 작은 기울기 (BU8a 개정 2)
 * ==========================================================================
 * 바탕은 스튜디오 캔버스와 같은 점 무늬다. 포인터가 히어로 위에 있으면 그 둘레의 점만 파랗게 밝아지고(마스크),
 * 스튜디오 그림·답 카드가 포인터 쪽으로 아주 조금 기운다. ★연속 값은 React 상태로 들고 있지 않는다★ — 포인터 위치는
 * requestAnimationFrame 한 번에 한 번만 히어로의 CSS 변수(--mx·--my·--px·--py)로 옮긴다(다시 그리기 0).
 * 정밀한 포인터(마우스)일 때만 · 감속 모션이면 아예 듣지 않는다 · 스크롤 이벤트는 듣지 않는다.
 */
import { useEffect, useRef } from "react";

export function HeroFx() {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const hero = ref.current?.closest<HTMLElement>(".ld-hero");
    if (!hero || typeof window.matchMedia !== "function") return;
    if (!window.matchMedia("(pointer: fine)").matches || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let x = 0;
    let y = 0;
    const apply = () => {
      raf = 0;
      const r = hero.getBoundingClientRect();
      const clamp = (v: number) => Math.max(-1, Math.min(1, v));
      hero.style.setProperty("--mx", `${Math.round(x - r.left)}px`);
      hero.style.setProperty("--my", `${Math.round(y - r.top)}px`);
      hero.style.setProperty("--px", clamp((x - (r.left + r.width / 2)) / (r.width / 2)).toFixed(3));
      hero.style.setProperty("--py", clamp((y - (r.top + r.height / 2)) / (r.height / 2)).toFixed(3));
      hero.setAttribute("data-ptr", "");
    };
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      x = e.clientX;
      y = e.clientY;
      if (!raf) raf = requestAnimationFrame(apply);
    };
    const leave = () => {
      hero.removeAttribute("data-ptr");
      hero.style.setProperty("--px", "0");
      hero.style.setProperty("--py", "0");
    };
    hero.addEventListener("pointermove", move, { passive: true });
    hero.addEventListener("pointerleave", leave);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      hero.removeEventListener("pointermove", move);
      hero.removeEventListener("pointerleave", leave);
    };
  }, []);

  return (
    <div className="ld-hero-fx" ref={ref} aria-hidden>
      <div className="ld-hero-glow" />
      <div className="ld-hero-ptr" />
    </div>
  );
}
