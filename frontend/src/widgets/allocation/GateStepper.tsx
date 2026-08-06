"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// GateStepper — 목표 게이트 상단의 3단계 진행 표시 (A2b)
// ─────────────────────────────────────────────────────────────────────────────
// 브리프의 `1. Setup (Active) → 2. Logic → 3. Validation`.
//
// ★왜 WizardTracker 를 재사용하지 않았나★
// WizardTracker 는 **11개 스테이지**를 그린다. 게이트에서 요구된 것은 그 위 계층인
// 3개 페이즈다. 게다가 게이트에서는 활성 스테이지가 없어서 `stageIndex()` 가 0 으로
// 폴백하고, 그러면 "00 OVERVIEW 진행 중"이라고 거짓말을 한다. 다른 물건이다.
//
// ★데이터는 새로 만들지 않는다★
// `PHASES`(AllocationProvider)가 이미 setup/logic/validation 을 ko 라벨과 함께 들고 있다.
// 여기서 라벨을 다시 적으면 두 번째 진실이 생긴다 — 레지스트리를 읽는다.
//
// ★2·3 단계를 버튼으로 만들지 않았다★
// 목표를 고르기 전에는 갈 곳이 없다. 눌러도 아무 일 없는 버튼은 어포던스 거짓말이라,
// 앞 단계는 그냥 <li> 로 둔다. 현재 위치만 aria-current="step" 으로 알린다.
import React from "react";
import { PHASES } from "./AllocationProvider";

export function GateStepper() {
  return (
    <nav className="aas-gstep" aria-label="포트폴리오 수립 진행 단계">
      <ol className="aas-gstep-list">
        {PHASES.map((p, i) => {
          const active = i === 0; // 게이트 = Setup 진입 직전. 완료된 단계는 아직 없다.
          return (
            <li
              key={p.key}
              className={`aas-gstep-item${active ? " on" : ""}`}
              aria-current={active ? "step" : undefined}
            >
              <span className="aas-gstep-n num">{i + 1}</span>
              <span className="aas-gstep-lab">{p.label}</span>
              <span className="aas-gstep-ko">{p.ko}</span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
