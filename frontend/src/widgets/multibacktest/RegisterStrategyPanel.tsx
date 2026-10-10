"use client";

// ═══════════════════════════════════════════════════════════════════════════════
// 전략 등록 — 완료된 백테스트 실행을 멀티전략의 전략으로 (BG6)
//
// 백엔드: `POST /api/v1/multibacktest/strategies` (`StrategyRegistry.register`).
// ★등록은 그 실행을 다시 돌려 자산곡선이 저장본과 전부 같을 때만 받아들여진다★ —
// 다르면 409 + 사유(+ 첫 불일치 날짜). 그 사유를 그대로 보인다. 재실행이라 몇 초에서
// 수십 초가 걸린다.
// ═══════════════════════════════════════════════════════════════════════════════

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";

import { backtestRunApi, type RunStatusLite } from "@/entities/backtest-run";
import { multibacktestApi, type RegisteredStrategy } from "@/entities/multibacktest";

interface Props {
  strategies: RegisteredStrategy[];
  onChanged: () => void;
}

function dataText(mock: boolean | null | undefined): string {
  if (mock === true) return "mock";
  if (mock === false) return "실데이터";
  return "데이터 미상";
}

function when(ts: number | null | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ");
}

export default function RegisterStrategyPanel({ strategies, onChanged }: Props) {
  const [runs, setRuns] = useState<RunStatusLite[]>([]);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const { runs: all } = await backtestRunApi.list();
      setRuns((all || []).filter((r) => r.status === "completed"));
      setRunsError(null);
    } catch (e) {
      // ★빈 목록으로 조용히 넘기지 않는다★ — 못 읽었다고 말한다.
      setRuns([]);
      setRunsError(`백테스트 실행 목록을 읽지 못했어요 — ${String(e)}`);
    }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const registeredBy = useMemo(() => {
    const m: Record<string, RegisteredStrategy> = {};
    strategies.forEach((s) => { m[s.source_run_id] = s; });
    return m;
  }, [strategies]);

  const register = async (run: RunStatusLite) => {
    setBusy(run.run_id);
    setOutcome(null);
    try {
      const res = await multibacktestApi.register(run.run_id, names[run.run_id]);
      if (res.ok) {
        setOutcome({ ok: true,
          text: `등록했어요 — #${res.strategy.id} ${res.strategy.name} `
            + `(재현 ${res.strategy.repro?.compared_points ?? "?"}점 일치)` });
        onChanged();
      } else {
        const at = res.firstMismatchDate ? ` · 첫 불일치 ${res.firstMismatchDate}` : "";
        setOutcome({ ok: false, text: `등록 거절 (HTTP ${res.status}) — ${res.reason}${at}` });
      }
    } catch (e) {
      setOutcome({ ok: false, text: `등록 요청 실패 — ${String(e)}` });
    } finally {
      setBusy(null);
    }
  };

  const deactivate = async (s: RegisteredStrategy) => {
    setBusy(`s${s.id}`);
    setOutcome(null);
    try {
      await multibacktestApi.deactivate(s.id);
      setOutcome({ ok: true, text: `#${s.id} ${s.name} 을(를) 비활성했어요.` });
      onChanged();
    } catch (e) {
      setOutcome({ ok: false, text: `비활성 실패 — ${String(e)}` });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      {/* 완료된 실행 */}
      <div>
        <div style={labelStyle}>완료된 백테스트 실행 ({runs.length})</div>
        <div style={listStyle}>
          {runsError && <div style={{ ...rowText, color: "#ffab91" }}>{runsError}</div>}
          {!runsError && runs.length === 0 && (
            <div style={{ ...rowText, color: "#6b7fa3", textAlign: "center" }}>
              완료된 실행이 없어요 — 스크리너 → 백테스트를 먼저 실행하세요.
            </div>
          )}
          {runs.map((r) => {
            const reg = registeredBy[r.run_id];
            return (
              <div key={r.run_id} style={rowStyle}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ ...rowText, color: "#e0e8f5", fontWeight: 600 }}>
                    {r.strategy_name || r.run_id}
                  </div>
                  <div style={monoSmall}>
                    {r.run_id} · {when(r.completed_at)} · {dataText(r.is_mock_data)}
                  </div>
                </div>
                {reg ? (
                  <span style={{ ...monoSmall, color: "#69f0ae" }}>등록됨 #{reg.id}</span>
                ) : (
                  <>
                    <input
                      placeholder="이름(선택)"
                      value={names[r.run_id] ?? ""}
                      onChange={(e) => setNames({ ...names, [r.run_id]: e.target.value })}
                      style={inputStyle}
                    />
                    <button onClick={() => register(r)} disabled={busy !== null}
                            style={btnStyle(busy === null)}>
                      {busy === r.run_id ? <Loader2 size={11} className="spin" /> : <Plus size={11} />}
                      {busy === r.run_id ? "재실행·재현 검증 중" : "등록"}
                    </button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* 등록된 전략 */}
      <div>
        <div style={labelStyle}>등록된 전략 ({strategies.length})</div>
        <div style={listStyle}>
          {strategies.length === 0 && (
            <div style={{ ...rowText, color: "#6b7fa3", textAlign: "center" }}>
              등록된 전략이 없어요 — 왼쪽에서 완료된 실행을 등록하세요.
            </div>
          )}
          {strategies.map((s) => (
            <div key={s.id} style={rowStyle}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ ...rowText, color: "#e0e8f5", fontWeight: 600 }}>
                  #{s.id} · {s.name}
                </div>
                <div style={monoSmall}>
                  원천 {s.source_run_id} · {dataText(s.is_mock_data)} ·
                  {s.is_pit_verified === true ? " PIT 검증" : s.is_pit_verified === false ? " PIT 미검증" : " PIT 미상"}
                  {" · "}종목 {s.symbols?.length ?? 0}
                </div>
              </div>
              <button onClick={() => deactivate(s)} disabled={busy !== null}
                      style={btnStyle(busy === null)} title="비활성 — 지우지 않아요">
                {busy === `s${s.id}` ? <Loader2 size={11} className="spin" /> : <Trash2 size={11} />}
                비활성
              </button>
            </div>
          ))}
        </div>
      </div>

      {outcome && (
        <div style={{
          gridColumn: "1 / -1", padding: "8px 12px", borderRadius: 4, fontSize: 11,
          background: outcome.ok ? "rgba(105,240,174,0.08)" : "rgba(255,82,82,0.1)",
          border: `1px solid ${outcome.ok ? "rgba(105,240,174,0.3)" : "rgba(255,82,82,0.3)"}`,
          color: outcome.ok ? "#69f0ae" : "#ffab91",
        }}>
          {outcome.text}
        </div>
      )}
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  fontSize: 10, fontWeight: 600, color: "#6b7fa3", textTransform: "uppercase",
  letterSpacing: "0.05em", marginBottom: 4,
};

const listStyle: React.CSSProperties = {
  maxHeight: 220, overflowY: "auto", background: "#060a1a",
  border: "1px solid #1e2d4a", borderRadius: 6, padding: 6,
};

const rowStyle: React.CSSProperties = {
  display: "flex", alignItems: "center", gap: 8, padding: "6px 8px",
  borderBottom: "1px solid #0f1a33",
};

const rowText: React.CSSProperties = { fontSize: 11, padding: 4 };

const monoSmall: React.CSSProperties = {
  fontSize: 9, color: "#6b7fa3", fontFamily: "'Roboto Mono', monospace",
  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
};

const inputStyle: React.CSSProperties = {
  width: 110, padding: "4px 6px", background: "#0a0e27", color: "#e0e8f5",
  border: "1px solid #1e2d4a", borderRadius: 3, fontSize: 10, outline: "none",
};

const btnStyle = (enabled: boolean): React.CSSProperties => ({
  display: "flex", alignItems: "center", gap: 4, padding: "4px 8px",
  background: enabled ? "#0d47a1" : "#1e2d4a", color: "#fff", border: "none",
  borderRadius: 3, fontSize: 10, fontWeight: 600,
  cursor: enabled ? "pointer" : "not-allowed", opacity: enabled ? 1 : 0.6,
  whiteSpace: "nowrap",
});
