"use client";
/**
 * 첫 화면 · 포트폴리오 설계 스튜디오 둘러보기 (BU8a 개정 — 사용자: "캔버스 설계 스튜디오가 메인 도구니 그것을 설명하는 느낌으로")
 * ==========================================================================
 * 왼쪽 글 네 단계를 내려 읽으면, 오른쪽에 붙어 있는 ★실제 스튜디오 화면(연습용 데이터로 계산한 캡처)★이 그 단계가 말하는 부위로
 * 다가가고(확대) 그 부위만 밝게 비춘다. 그림을 지어내지 않는다 — 부위 좌표는 캡처할 때 실제 DOM 상자에서 잰 값이다
 * (`scratchpad/bu8_studio.cjs` · 1280×800 뷰포트 대비 %). 화면을 다시 찍으면 좌표도 같이 다시 잰다.
 *
 * 움직임: 어느 단계가 화면 가운데에 왔는지는 IntersectionObserver 로만 안다(스크롤 이벤트를 듣지 않는다).
 * 확대·비춤은 transform·opacity 전환뿐 · 감속 모션이면 전환 없이 바로 바뀐다(globals BU8a 절) · 단계 제목은 단추라 키보드로도 고른다.
 */
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

type Box = { x: number; y: number; w: number; h: number };
const STEPS: { t: string; d: string; box: Box }[] = [
  {
    t: "필요한 부품을 골라요",
    d: "종목 고르기부터 신호, 점검까지 왼쪽 목록에서 골라 캔버스에 놓아요. 절차 탭이 다음에 붙일 것을 알려 줘요.",
    box: { x: 5.31, y: 16.63, w: 16.25, h: 50 },
  },
  {
    t: "선으로 이어 흐름을 만들어요",
    d: "같은 색 점끼리 이으면 값이 흘러요. 선 모양은 근거를 말해요. 점선이면 연습용 값이, 끊긴 회색이면 흐르지 않은 값이에요.",
    box: { x: 22.5, y: 43.5, w: 48.8, h: 33.5 },
  },
  {
    t: "계산하면 관문을 확인해요",
    d: "데이터 무결성부터 실계좌까지 관문마다 확인했는지, 건너뛰었는지 알려 줘요. 건너뛴 관문은 통과가 아니에요.",
    box: { x: 37.21, y: 16.63, w: 19.34, h: 4.5 },
  },
  {
    t: "결과를 이야기로 읽어요",
    d: "숫자마다 어디서 왔고 무엇을 재지 않았는지 오른쪽 이야기가 풀어 줘요. 연습용 데이터면 그 사실부터 말해요.",
    box: { x: 72.19, y: 16.63, w: 26.88, h: 45 },
  },
];

/** 부위가 틀의 80% 안에 들어오게 확대하고, 그 가운데가 틀 가운데로 오게 옮긴다(그림이 틀 밖으로 비지 않게 가둔다). */
export function viewOf(box: Box | null): { z: number; tx: number; ty: number } {
  if (!box) return { z: 1, tx: 0, ty: 0 };
  const z = Math.min(2.2, Math.max(1.15, Math.min(80 / box.w, 80 / box.h)));
  const clamp = (v: number) => Math.min(0, Math.max(100 - 100 * z, v));
  return { z, tx: clamp(50 - (box.x + box.w / 2) * z), ty: clamp(50 - (box.y + box.h / 2) * z) };
}

export function StudioTour() {
  const [active, setActive] = useState(0);          // 0 = 한눈에(아직 단계에 닿지 않음)
  const [seen, setSeen] = useState(false);
  const [armed, setArmed] = useState(false);       // JS 가 붙은 뒤에만 '등장 전' 모습을 건다(서버 렌더·JS 없음에서 숨지 않게)
  const steps = useRef<(HTMLLIElement | null)[]>([]);
  const root = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    setArmed(true);
    // 화면 가운데 가는 띠에 들어온 단계가 지금 단계다.
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.step));
    }, { rootMargin: "-45% 0px -45% 0px" });
    steps.current.forEach((el) => el && io.observe(el));
    const enter = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setSeen(true); enter.disconnect(); }
    }, { threshold: 0.15 });
    if (root.current) enter.observe(root.current);
    return () => { io.disconnect(); enter.disconnect(); };
  }, []);

  const v = viewOf(active ? STEPS[active - 1].box : null);
  return (
    <div className="ld-tour" ref={root} data-active={active} data-arm={armed || undefined} data-in={seen || undefined}
         style={{ ["--p" as string]: active / STEPS.length }}>
      <ol className="ld-tour-steps">
        {STEPS.map((s, i) => (
          <li key={s.t} className="ld-tour-step" data-step={i + 1} data-on={active === i + 1 || undefined}
              ref={(el) => { steps.current[i] = el; }}>
            <button type="button" className="ld-tour-btn" aria-pressed={active === i + 1} onClick={() => setActive(i + 1)}>
              <span className="ld-tour-n" aria-hidden>{i + 1}</span>
              <span className="ld-tour-t">{s.t}</span>
            </button>
            <p className="ld-tour-d">{s.d}</p>
          </li>
        ))}
      </ol>
      <div className="ld-tour-stage">
        <figure className="ld-tour-fig">
          <div className="ld-tour-frame">
            <div className="ld-tour-zoom"
                 style={{ transform: `translate(${v.tx}%, ${v.ty}%) scale(${v.z})` }}>
              <Image className="ld-shot-light" src="/landing/studio-light.webp" width={1920} height={1200} unoptimized
                     sizes="(max-width: 1080px) 100vw, 720px"
                     alt="포트폴리오 설계 스튜디오 화면. 왼쪽에 노드 목록, 가운데에 종목 고르기에서 비중 계산까지 선으로 이은 노드들, 위에 관문 확인 알약, 오른쪽에 연습용 결과라는 안내와 설계 이야기가 있어요." />
              <Image className="ld-shot-dark" src="/landing/studio-dark.webp" width={1920} height={1200} unoptimized
                     sizes="(max-width: 1080px) 100vw, 720px"
                     alt="포트폴리오 설계 스튜디오 화면(어두운 테마). 노드 목록, 선으로 이은 노드들, 관문 알약, 설계 이야기가 있어요." />
              {STEPS.map((s, i) => (
                <span key={s.t} className="ld-spot" data-spot={i + 1} data-on={active === i + 1 || undefined} aria-hidden
                      style={{ left: `${s.box.x}%`, top: `${s.box.y}%`, width: `${s.box.w}%`, height: `${s.box.h}%` }} />
              ))}
            </div>
          </div>
          <figcaption className="ld-shot-cap">연습용 데이터로 계산한 실제 스튜디오 화면이에요(2026년 10월). 실제 성과가 아니에요.</figcaption>
        </figure>
      </div>
    </div>
  );
}
