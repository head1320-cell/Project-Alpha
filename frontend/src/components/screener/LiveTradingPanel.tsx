"use client";

import { useState, useEffect } from "react";
import { Wallet, ShieldAlert, Play, Loader2, AlertTriangle, Ban, CheckCircle2, XCircle } from "lucide-react";
import {
  tradingApi, type FilterGroupNode, type TradingMode,
  type AccountStatus, type TradeExecutionResult, type SafetyConfig, DEFAULT_SAFETY,
} from "@/lib/screenerApi";

// ═══════════════════════════════════════════════════════════════════════════════
// LiveTradingPanel — 스크리너 통과 종목 자동매매 (안전 최우선)
// ═══════════════════════════════════════════════════════════════════════════════

export function LiveTradingPanel({ group, universe, liquidityFloor }: {
  group: FilterGroupNode;
  universe: string;
  liquidityFloor: string;
}) {
  const [mode, setMode] = useState<TradingMode | null>(null);
  const [account, setAccount] = useState<AccountStatus | null>(null);
  const [result, setResult] = useState<TradeExecutionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // 안전장치 (사용자 조정 가능)
  const [dryRun, setDryRun] = useState(true);
  const [maxTickers, setMaxTickers] = useState(5);
  const [maxPositionPct, setMaxPositionPct] = useState(20);
  const [maxOrderAmount, setMaxOrderAmount] = useState(10_000_000);
  const [killSwitch, setKillSwitch] = useState(false);
  const [confirmReal, setConfirmReal] = useState(false);

  useEffect(() => {
    tradingApi.mode().then(setMode).catch(() => {});
    tradingApi.status().then(setAccount).catch(() => {});
  }, []);

  const isReal = mode?.mode === "real";
  const canExecute = group.conditions.length > 0 && !killSwitch &&
    (!isReal || !dryRun ? confirmReal || dryRun : true);

  const run = async () => {
    if (isReal && !dryRun && !confirmReal) {
      setErr("실계좌 주문은 확인 체크가 필요합니다");
      return;
    }
    setLoading(true); setErr(null); setResult(null);
    try {
      const safety: Partial<SafetyConfig> = {
        ...DEFAULT_SAFETY, dry_run: dryRun, kill_switch: killSwitch,
        max_position_pct: maxPositionPct / 100, max_order_amount_krw: maxOrderAmount,
      };
      const r = await tradingApi.screenToTrade({
        universe, filter_ast: group, liquidity_floor: liquidityFloor,
        max_tickers: maxTickers, action: "buy", equal_weight: true, safety,
      });
      setResult(r);
      tradingApi.status().then(setAccount).catch(() => {});
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  };

  const modeColor = mode?.mode === "real" ? "#dc2626" : mode?.mode === "paper" ? "#d97706" : "#71718a";
  const modeBg = mode?.mode === "real" ? "#fef2f2" : mode?.mode === "paper" ? "#fef3c7" : "#f1f1f6";

  return (
    <div className="card-md p-4" style={{ borderLeft: `3px solid ${modeColor}` }}>
      {/* 헤더 + 모드 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span style={{ background: modeBg, color: modeColor, width: 22, height: 22, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Wallet size={13} />
          </span>
          <span className="text-sm font-bold" style={{ color: modeColor }}>자동매매 (실거래)</span>
          {mode && (
            <span className="text-[9px] px-2 py-0.5 rounded-full font-bold" style={{ background: modeBg, color: modeColor }}>
              {mode.mode === "real" ? "⚠ 실계좌" : mode.mode === "paper" ? "모의투자" : "Mock"}
            </span>
          )}
        </div>
        {account && (
          <div className="text-[10px] text-secondary font-mono">
            현금 {(account.cash_krw / 10000).toLocaleString()}만 · 보유 {account.n_positions}종목
          </div>
        )}
      </div>

      {/* 모드 설명 */}
      {mode && (
        <div className="text-[10px] mb-3 px-2.5 py-1.5 rounded-md" style={{ background: modeBg, color: modeColor }}>
          {mode.mode === "real" && <AlertTriangle size={11} className="inline mr-1" />}
          {mode.description}
        </div>
      )}

      {/* 안전장치 컨트롤 */}
      <div className="bg-light rounded-lg p-3 mb-3">
        <div className="flex items-center gap-1.5 mb-2.5">
          <ShieldAlert size={12} style={{ color: "#16a34a" }} />
          <span className="text-[10px] font-bold uppercase tracking-wider text-secondary">안전장치</span>
        </div>
        {/* Dry-run 토글 */}
        <label className="flex items-center justify-between mb-2.5 cursor-pointer">
          <span className="text-[11px]">
            <b>모의 계산 (Dry-run)</b>
            <span className="text-secondary"> — 실주문 없이 시뮬</span>
          </span>
          <input type="checkbox" checked={dryRun} onChange={e => { setDryRun(e.target.checked); setConfirmReal(false); }}
            style={{ accentColor: "#16a34a", width: 16, height: 16 }} />
        </label>
        {/* 슬라이더들 */}
        <div className="grid grid-cols-3 gap-2 mb-1">
          <div>
            <label className="text-[9px] text-secondary block mb-0.5">종목 수 ({maxTickers})</label>
            <input type="range" min="1" max="15" value={maxTickers} onChange={e => setMaxTickers(+e.target.value)} className="w-full" style={{ accentColor: modeColor }} />
          </div>
          <div>
            <label className="text-[9px] text-secondary block mb-0.5">종목당 비중 ({maxPositionPct}%)</label>
            <input type="range" min="5" max="50" value={maxPositionPct} onChange={e => setMaxPositionPct(+e.target.value)} className="w-full" style={{ accentColor: modeColor }} />
          </div>
          <div>
            <label className="text-[9px] text-secondary block mb-0.5">종목당 상한 ({(maxOrderAmount / 10000).toLocaleString()}만)</label>
            <input type="range" min="1000000" max="50000000" step="1000000" value={maxOrderAmount} onChange={e => setMaxOrderAmount(+e.target.value)} className="w-full" style={{ accentColor: modeColor }} />
          </div>
        </div>
      </div>

      {/* 실계좌 확인 */}
      {isReal && !dryRun && (
        <label className="flex items-center gap-2 mb-3 p-2.5 rounded-md cursor-pointer" style={{ background: "#fef2f2", border: "1px solid #fecaca" }}>
          <input type="checkbox" checked={confirmReal} onChange={e => setConfirmReal(e.target.checked)} style={{ accentColor: "#dc2626", width: 16, height: 16 }} />
          <span className="text-[11px]" style={{ color: "#dc2626" }}>
            <b>실제 자금이 거래됨을 확인합니다.</b> 위 조건의 종목을 실계좌에서 매수합니다.
          </span>
        </label>
      )}

      {/* 실행 버튼 */}
      <div className="flex items-center gap-2 mb-1">
        <button onClick={run} disabled={loading || !group.conditions.length || killSwitch}
          className="flex-1 text-[12px] px-3 py-2.5 rounded-md text-white flex items-center justify-center gap-1.5 disabled:opacity-50 font-bold"
          style={{ background: dryRun ? "#16a34a" : modeColor }}>
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
          {dryRun ? "모의 실행 (Dry-run)" : isReal ? "⚠ 실계좌 매수 실행" : "모의투자 매수 실행"}
        </button>
        <button onClick={() => setKillSwitch(!killSwitch)}
          className="text-[11px] px-3 py-2.5 rounded-md flex items-center gap-1.5 font-bold"
          style={{ background: killSwitch ? "#dc2626" : "#f1f1f6", color: killSwitch ? "#fff" : "#71718a" }}>
          <Ban size={13} /> {killSwitch ? "차단 중" : "Kill"}
        </button>
      </div>

      {!result && !err && (
        <div className="text-[11px] text-secondary mt-2">현재 필터 통과 종목을 균등 비중으로 매수합니다. 기본 Dry-run으로 안전하게 시뮬합니다.</div>
      )}

      {err && (
        <div className="text-[11px] flex items-center gap-1.5 mt-2" style={{ color: "#dc2626" }}>
          <AlertTriangle size={12} /> {err}
        </div>
      )}

      {/* 결과 */}
      {result && (
        <div className="animate-fade-in mt-3 pt-3 border-t border-default">
          <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold" style={{ background: result.mode === "dry_run" ? "#dcfce7" : result.mode === "real" ? "#fef2f2" : "#fef3c7", color: result.mode === "dry_run" ? "#15803d" : result.mode === "real" ? "#dc2626" : "#a16207" }}>
                {result.mode === "dry_run" ? "모의 계산" : result.mode === "real" ? "실계좌 체결" : "모의투자 체결"}
              </span>
              <span className="text-[10px] text-secondary">{result.screened_count}종목 스크리닝</span>
            </div>
            <div className="text-[10px] text-secondary font-mono">
              투자 {(result.summary.daily_invested_krw / 10000).toLocaleString()}만원
            </div>
          </div>

          {/* 실행된 주문 */}
          {result.executed.length > 0 && (
            <div className="mb-2">
              {result.executed.map((e, i) => (
                <div key={i} className="flex items-center justify-between py-1 text-[11px]">
                  <span className="flex items-center gap-1.5">
                    <CheckCircle2 size={12} style={{ color: "#16a34a" }} />
                    <span className="font-medium">{e.stock_name}</span>
                    <span className="text-secondary">{e.action === "buy" ? "매수" : "매도"}</span>
                  </span>
                  <span className="font-mono text-secondary">{e.quantity}주 @ {e.price.toLocaleString()} = {(e.amount_krw / 10000).toLocaleString()}만</span>
                </div>
              ))}
            </div>
          )}

          {/* 차단된 주문 */}
          {result.blocked.length > 0 && (
            <div className="mb-1">
              {result.blocked.map((b, i) => (
                <div key={i} className="flex items-center justify-between py-1 text-[11px]">
                  <span className="flex items-center gap-1.5" style={{ color: "#d97706" }}>
                    <XCircle size={12} />
                    <span className="font-medium">{b.stock_name || b.stock_code}</span>
                  </span>
                  <span className="text-[10px]" style={{ color: "#d97706" }}>{b.blocked_by}</span>
                </div>
              ))}
            </div>
          )}

          {/* 경고 */}
          {result.summary.warnings.length > 0 && (
            <div className="mt-2 text-[10px]" style={{ color: "#d97706" }}>
              {result.summary.warnings.map((w, i) => <div key={i}>{w}</div>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
