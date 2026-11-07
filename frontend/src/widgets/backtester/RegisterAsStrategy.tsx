"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// 이 실행을 전략으로 등록 — 캔버스 "전략 백테스트"·"기록 견고성" 노드가 고르는 목록에 넣는다.
//
// 예전에는 여러 전략 백테스트 화면(/admin/multi-backtest)의 등록 판에만 있었다. 그 화면을 없애며
// (ST2, 2026-10-15) 등록은 결과를 본 바로 이 자리로 옮겼다. 요청은 그대로다:
// `POST /api/v1/multibacktest/strategies {run_id, name}` — 서버가 실행을 다시 돌려 자산곡선이
// 저장본과 전부 같을 때만 받는다. 거절(409)은 사유와 첫 불일치 날짜를 그대로 보인다.
// ═══════════════════════════════════════════════════════════════════════════════

import { useState } from "react";
import Link from "next/link";

import { multibacktestApi, type RegisteredStrategy } from "@/entities/multibacktest";
import { Notice } from "@/shared/ui/tx";

type Phase =
  | { k: "idle" }
  | { k: "checking" }
  | { k: "already"; s: RegisteredStrategy }
  | { k: "form" }
  | { k: "busy" }
  | { k: "done"; s: RegisteredStrategy }
  | { k: "refused"; reason: string; date: string | null; status: number }
  | { k: "failed"; reason: string };

export function RegisterAsStrategy({ runId, defaultName }: { runId: string; defaultName: string }) {
  const [phase, setPhase] = useState<Phase>({ k: "idle" });
  const [name, setName] = useState(defaultName);

  // 열 때만 목록을 읽는다 — 결과 화면을 여는 것만으로 요청을 늘리지 않는다.
  const open = async () => {
    setPhase({ k: "checking" });
    try {
      const all = await multibacktestApi.strategies(false);
      const hit = all.find((s) => s.source_run_id === runId);
      setPhase(hit ? { k: "already", s: hit } : { k: "form" });
    } catch (e) {
      setPhase({ k: "failed", reason: String(e instanceof Error ? e.message : e) });
    }
  };

  const submit = async () => {
    setPhase({ k: "busy" });
    try {
      const r = await multibacktestApi.register(runId, name);
      if (r.ok) setPhase({ k: "done", s: r.strategy });
      else setPhase({ k: "refused", reason: r.reason, date: r.firstMismatchDate, status: r.status });
    } catch (e) {
      setPhase({ k: "failed", reason: String(e instanceof Error ? e.message : e) });
    }
  };

  if (phase.k === "idle") {
    return (
      <button type="button" className="tx-btn tx-btn--sub" data-act="reg-open" onClick={open}>
        전략으로 등록
      </button>
    );
  }

  return (
    <div className="rs-reg" role="group" aria-label="전략으로 등록">
      {phase.k === "checking" && <p className="rs-reg-note">이미 등록했는지 확인하는 중이에요.</p>}

      {phase.k === "already" && (
        <p className="rs-reg-ok">
          이 실행은 이미 ‘{phase.s.name}’ 전략(#{phase.s.id})으로 등록돼 있어요
          {phase.s.is_active ? "." : " · 지금은 비활성이에요."}
        </p>
      )}

      {(phase.k === "form" || phase.k === "busy" || phase.k === "refused") && (
        <>
          <label className="rs-reg-label" htmlFor="rs-reg-name">전략 이름</label>
          <div className="rs-reg-row">
            <input id="rs-reg-name" className="ma-input" data-act="reg-name" value={name} maxLength={64}
              onChange={(e) => setName(e.target.value)} disabled={phase.k === "busy"} />
            <button type="button" className="tx-btn tx-btn--sub" data-act="reg-go" onClick={submit}
              disabled={phase.k === "busy"} aria-busy={phase.k === "busy"}>
              {phase.k === "busy" ? "다시 돌려 확인하는 중이에요" : "등록하기"}
            </button>
          </div>
          <p className="rs-reg-note">
            서버가 이 실행을 다시 돌려 자산곡선이 저장본과 같을 때만 받아요. 몇십 초 걸릴 수 있어요.
          </p>
        </>
      )}

      {phase.k === "refused" && (
        <Notice tone="danger" title="등록하지 않았어요">
          <span data-server>{phase.reason}</span>
          {phase.date && <> · 처음 달라진 날 {phase.date}</>}
        </Notice>
      )}

      {phase.k === "done" && (
        <p className="rs-reg-ok" role="status">
          ‘{phase.s.name}’ 전략(#{phase.s.id})으로 등록했어요. <Link href="/allocation">포트폴리오 설계</Link>의 전략 노드에서 고를 수 있어요.
        </p>
      )}

      {phase.k === "failed" && (
        <Notice tone="danger" title="등록 상태를 확인하지 못했어요">
          <span data-server>{phase.reason}</span>
          <button type="button" className="tx-btn tx-btn--sub rs-reg-retry" onClick={open}>다시 시도</button>
        </Notice>
      )}
    </div>
  );
}
