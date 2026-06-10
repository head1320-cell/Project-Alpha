"use client";

import { useState, Suspense } from "react";
import TerminalBacktester from "@/components/backtest/TerminalBacktester";
import CustomBacktestRunner from "@/components/backtest/CustomBacktestRunner";
import StrategyComparison from "@/components/backtest/StrategyComparison";
import { BuilderPanel } from "@/components/backtest/BuilderPanel";
import { useBuilderStore } from "@/lib/builder/store";
import { findStrategy, findByBuilderId, STRATEGY_CATALOG } from "@/lib/builder/strategyCatalog";
import type { BuilderState } from "@/types/builder";

// ═══════════════════════════════════════════════════════════════════════════════
// Backtester — 전략 실행(Execution) ⇄ 전략 설계(Builder) 완전 통합
//   기성 10종 + 커스텀 전략 모두 양방향 실행
// ═══════════════════════════════════════════════════════════════════════════════

type Mode = "execution" | "builder" | "comparison";

export default function BacktestPage() {
  const [mode, setMode] = useState<Mode>("execution");
  const [execStrategy, setExecStrategy] = useState<string>("GoldenCross");
  // 커스텀 전략 실행 상태 (null이면 기성 전략 모드)
  const [customSpec, setCustomSpec] = useState<BuilderState | null>(null);

  const loadState = useBuilderStore((s) => s.loadState);
  const builderState = useBuilderStore((s) => ({
    metadata: s.metadata, indicators: s.indicators,
    entry: s.entry, exit: s.exit, risk: s.risk,
  }));

  // 실행 → 설계: 기성 전략을 빌더로 로드
  const editInBuilder = (backendId: string) => {
    const entry = findStrategy(backendId);
    if (entry?.builderState) {
      loadState(entry.builderState);
      setMode("builder");
    }
  };

  // 설계 → 실행
  const currentExecutable = findByBuilderId(builderState.metadata.id);
  const runInExecution = () => {
    if (currentExecutable) {
      // 기성 전략과 매칭 → 기성 실행 모드
      setCustomSpec(null);
      setExecStrategy(currentExecutable.backendId);
    } else {
      // 커스텀 전략 → 커스텀 실행 모드 (현재 빌더 상태를 spec으로)
      setCustomSpec(builderState as BuilderState);
    }
    setMode("execution");
  };

  return (
    <div>
      {/* 모드 전환기 */}
      <div className="tbt-mode-switch">
        <button className={`tbt-mode${mode === "execution" ? " active" : ""}`} onClick={() => setMode("execution")}>
          <span className="tbt-mode-num">01</span>
          전략 실행
          <span className="tbt-mode-sub">Execution</span>
        </button>
        <button className={`tbt-mode${mode === "builder" ? " active" : ""}`} onClick={() => setMode("builder")}>
          <span className="tbt-mode-num">02</span>
          전략 설계
          <span className="tbt-mode-sub">Builder</span>
        </button>
        <button className={`tbt-mode${mode === "comparison" ? " active" : ""}`} onClick={() => setMode("comparison")}>
          <span className="tbt-mode-num">03</span>
          전략 비교
          <span className="tbt-mode-sub">Compare</span>
        </button>
      </div>

      {mode === "comparison" ? (
        <StrategyComparison />
      ) : mode === "execution" ? (
        customSpec ? (
          <CustomBacktestRunner
            spec={customSpec}
            onClearCustom={() => setCustomSpec(null)}
          />
        ) : (
          <TerminalBacktester
            key={execStrategy}
            defaultStrategy={execStrategy}
            onEditStrategy={editInBuilder}
          />
        )
      ) : (
        <div>
          <div className="meta-stamp">
            REF_ID: ALPHA_SB_201<br />
            MODE: STRATEGY_DESIGN<br />
            AUTH: SIG_VERIFIED
          </div>
          <div className="terminal-breadcrumb">Modules / Backtester / <span>Strategy Builder</span></div>
          <h1 className="terminal-h1">Strategy Design Studio</h1>

          {/* 실행 연결 배너 */}
          <div className="tbuilder-bridge">
            <div className="tbuilder-bridge-info">
              <span className="tbuilder-bridge-label">현재 설계 전략</span>
              <span className="tbuilder-bridge-name">{builderState.metadata.name || "이름 없는 전략"}</span>
              {currentExecutable ? (
                <span className="tbuilder-bridge-badge ok">✓ 기성 전략 ({currentExecutable.label})</span>
              ) : (
                <span className="tbuilder-bridge-badge custom">커스텀 전략 — 직접 실행 가능</span>
              )}
            </div>
            <button className="tbuilder-bridge-btn" onClick={runInExecution}>
              ▶ 이 전략 실행하기
            </button>
          </div>

          {/* 기성 전략 빠른 로드 */}
          <div className="tbuilder-presets">
            <span className="tbuilder-presets-label">기성 전략 불러오기:</span>
            {STRATEGY_CATALOG.map((s) => (
              <button
                key={s.backendId}
                className={`tbuilder-preset-chip${builderState.metadata.id === s.builderState?.metadata.id ? " active" : ""}`}
                onClick={() => s.builderState && loadState(s.builderState)}
              >
                {s.label}
              </button>
            ))}
          </div>

          <Suspense fallback={<div style={{ padding: 40, textAlign: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 12 }}>[ LOADING_BUILDER ]</div>}>
            <BuilderPanel />
          </Suspense>
        </div>
      )}
    </div>
  );
}
