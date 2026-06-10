"use client";

import { useState, useEffect } from "react";
import {
  backtestBridgeApi, type ScreenToBacktestResult,
  type FilterGroupNode, type BacktestTrade, type MonthlyReturn,
} from "@/lib/screenerApi";
import { getScreenerHandoff, clearScreenerHandoff, type ScreenerStrategyHandoff } from "@/lib/screenerHandoff";
import {
  listStrategies, saveStrategy, deleteStrategy, exportTradesCsv, exportSummaryCsv,
  type SavedStrategy,
} from "@/lib/strategyStorage";
import {
  listWatchlists, createWatchlist, deleteWatchlist, addTicker, removeTicker,
  type Watchlist,
} from "@/lib/watchlistStorage";

// ═══════════════════════════════════════════════════════════════════════════════
// TerminalBacktester — Variant "Strategy Performance Engine" 스타일
//   실제 run_backtest (screen-to-backtest 브릿지) 사용. 대형주 유니버스 자동 선정.
// ═══════════════════════════════════════════════════════════════════════════════

// 유동성 게이트 통과용 최소 필터 (PER은 mock에서도 항상 존재)
function largeCapFilter(): FilterGroupNode {
  return {
    logic: "AND",
    conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }] as FilterGroupNode["conditions"],
    groups: [],
  };
}

export default function TerminalBacktester({ onEditStrategy, defaultStrategy }: { onEditStrategy?: (backendId: string) => void; defaultStrategy?: string } = {}) {
  const [strategies, setStrategies] = useState<Array<{ id: string; label: string }>>([]);
  const [strategy, setStrategy] = useState(defaultStrategy || "GoldenCross");
  const [universe, setUniverse] = useState("kospi200");
  const [startDate, setStartDate] = useState("2023-01-01");
  const [endDate, setEndDate] = useState("2024-12-31");
  const [maxTickers, setMaxTickers] = useState(10);
  const [capital, setCapital] = useState(100_000_000);
  // 고급 옵션
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [commissionBps, setCommissionBps] = useState(15);   // 0.15% = 15bp
  const [slippageBps, setSlippageBps] = useState(5);         // 0.05% = 5bp
  const [stopLoss, setStopLoss] = useState<number | "">("");
  const [takeProfit, setTakeProfit] = useState<number | "">("");
  // 체결가 유형 (Phase 1)
  const [buyFillType, setBuyFillType] = useState("close");
  const [sellFillType, setSellFillType] = useState("close");
  const [fillGroups, setFillGroups] = useState<Array<{ id: string; label: string; types: Array<{ id: string; label: string }> }>>([]);
  // 종목 선택 확장 (Phase 4) — 업종
  const [sectors, setSectors] = useState<Array<{ id: string; label: string; size: number }>>([]);
  // 매도 정밀화 (Phase 2)
  const [maxHoldDays, setMaxHoldDays] = useState<number | "">("");
  const [minHoldDays, setMinHoldDays] = useState<number | "">("");
  const [sellDividePct, setSellDividePct] = useState(100);
  const [maxSellDivisions, setMaxSellDivisions] = useState<number | "">("");
  // 매수 정밀화 (Phase 3)
  const [buyWeightMode, setBuyWeightMode] = useState("equal");
  const [buyDividePct, setBuyDividePct] = useState(100);
  const [maxBuyPerDay, setMaxBuyPerDay] = useState<number | "">("");
  const [maxBuyCount, setMaxBuyCount] = useState<number | "">("");
  const [result, setResult] = useState<ScreenToBacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  // 스크리너에서 넘어온 조건식 (있으면 유니버스 필터로 사용)
  const [handoff, setHandoff] = useState<ScreenerStrategyHandoff | null>(null);
  // 전략 저장/불러오기 (Phase 5-A)
  const [savedList, setSavedList] = useState<SavedStrategy[]>([]);
  const [showSaved, setShowSaved] = useState(false);
  const [saveName, setSaveName] = useState("");
  // 관심그룹 (Phase ③)
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [showWatch, setShowWatch] = useState(false);
  const [newWatchName, setNewWatchName] = useState("");
  const [tickerInput, setTickerInput] = useState<Record<string, string>>({});

  useEffect(() => {
    backtestBridgeApi.strategies().then((d) => setStrategies(d.strategies)).catch(() => {});
    backtestBridgeApi.fillPriceTypes().then((d) => setFillGroups(d.groups)).catch(() => {});
    backtestBridgeApi.sectors().then((d) => setSectors(d.sectors)).catch(() => {});
    setSavedList(listStrategies());
    setWatchlists(listWatchlists());
    // 스크리너 전략 전달 감지
    const h = getScreenerHandoff();
    if (h) {
      setHandoff(h);
      setUniverse(h.universe);
    }
  }, []);

  // 현재 설정을 객체로 수집 (저장용)
  const collectConfig = (): SavedStrategy["config"] => ({
    strategy, universe, startDate, endDate, maxTickers, capital,
    commissionBps, slippageBps, stopLoss, takeProfit, buyFillType, sellFillType,
    maxHoldDays, minHoldDays, sellDividePct, maxSellDivisions,
    buyWeightMode, buyDividePct, maxBuyPerDay, maxBuyCount,
  });

  const handleSave = () => {
    saveStrategy(saveName, collectConfig());
    setSavedList(listStrategies());
    setSaveName("");
  };

  const handleApply = (s: SavedStrategy) => {
    const c = s.config;
    setStrategy(c.strategy); setUniverse(c.universe);
    setStartDate(c.startDate); setEndDate(c.endDate);
    setMaxTickers(c.maxTickers); setCapital(c.capital);
    setCommissionBps(c.commissionBps); setSlippageBps(c.slippageBps);
    setStopLoss(c.stopLoss); setTakeProfit(c.takeProfit);
    setBuyFillType(c.buyFillType); setSellFillType(c.sellFillType);
    setMaxHoldDays(c.maxHoldDays); setMinHoldDays(c.minHoldDays);
    setSellDividePct(c.sellDividePct); setMaxSellDivisions(c.maxSellDivisions);
    setBuyWeightMode(c.buyWeightMode); setBuyDividePct(c.buyDividePct);
    setMaxBuyPerDay(c.maxBuyPerDay); setMaxBuyCount(c.maxBuyCount);
    setShowSaved(false);
  };

  const handleDelete = (id: string) => {
    deleteStrategy(id);
    setSavedList(listStrategies());
  };

  // 관심그룹 핸들러 (Phase ③)
  const handleCreateWatch = () => {
    createWatchlist(newWatchName);
    setWatchlists(listWatchlists());
    setNewWatchName("");
  };
  const handleDeleteWatch = (id: string) => {
    deleteWatchlist(id);
    setWatchlists(listWatchlists());
    // 삭제된 관심그룹이 현재 선택돼 있으면 기본으로 되돌림
    if (universe === `watchlist:${id}`) setUniverse("kospi200");
  };
  const handleAddTicker = (id: string) => {
    const code = (tickerInput[id] || "").trim();
    if (!code) return;
    addTicker(id, code);
    setWatchlists(listWatchlists());
    setTickerInput((m) => ({ ...m, [id]: "" }));
  };
  const handleRemoveTicker = (id: string, ticker: string) => {
    removeTicker(id, ticker);
    setWatchlists(listWatchlists());
  };

  const run = async () => {
    setLoading(true); setErr(null); setResult(null);
    try {
      // 관심그룹 선택 시 종목 리스트를 custom_tickers로 전달
      let customTickers: string[] | null = null;
      let effUniverse = universe;
      if (universe.startsWith("watchlist:")) {
        const wid = universe.slice("watchlist:".length);
        const wl = watchlists.find((w) => w.id === wid);
        customTickers = wl && wl.tickers.length > 0 ? wl.tickers : null;
        effUniverse = "custom";
      }
      const r = await backtestBridgeApi.screenToBacktest({
        universe: effUniverse,
        custom_tickers: customTickers,
        filter_ast: handoff ? handoff.filterAst : largeCapFilter(),
        liquidity_floor: "standard",
        max_tickers: maxTickers, strategy_name: strategy,
        start_date: startDate, end_date: endDate, initial_capital: capital,
        commission_rate: commissionBps / 10000,
        slippage_rate: slippageBps / 10000,
        stop_loss_pct: stopLoss === "" ? null : Number(stopLoss),
        take_profit_pct: takeProfit === "" ? null : Number(takeProfit),
        buy_fill_type: buyFillType,
        sell_fill_type: sellFillType,
        max_hold_days: maxHoldDays === "" ? null : Number(maxHoldDays),
        min_hold_days: minHoldDays === "" ? 0 : Number(minHoldDays),
        sell_divide_pct: sellDividePct,
        max_sell_divisions: maxSellDivisions === "" ? null : Number(maxSellDivisions),
        buy_weight_mode: buyWeightMode,
        buy_divide_pct: buyDividePct,
        max_buy_per_day: maxBuyPerDay === "" ? null : Number(maxBuyPerDay),
        max_buy_count: maxBuyCount === "" ? null : Number(maxBuyCount),
      });
      if (r.error) setErr(r.message || "백테스트 실패");
      else setResult(r);
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  };

  const st = result?.backtest?.statistics;
  const fmt = (v: number | undefined, suffix = "", digits = 1) =>
    v === undefined ? "—" : `${v >= 0 && suffix === "%" ? "+" : ""}${v.toFixed(digits)}${suffix}`;
  const posColor = (v: number | undefined) => ((v ?? 0) >= 0 ? "#16a34a" : "#dc2626");

  return (
    <div>
      <div className="meta-stamp">
        REF_ID: ALPHA_BT_088<br />
        ENGINE: V2.0.4<br />
        AUTH: SIG_VERIFIED
      </div>

      <div className="terminal-breadcrumb">Modules / <span>Backtester</span></div>
      <h1 className="terminal-h1">Strategy Performance Engine</h1>

      {/* 스크리너 전략 전달 배너 */}
      {handoff && (
        <div className="tscreener-handoff">
          <div className="tscreener-handoff-main">
            <span className="tscreener-handoff-badge">스크리너 전략</span>
            <span className="tscreener-handoff-text">
              {handoff.conditionSummary.length}개 조건으로 검색된 종목에 백테스트
              {handoff.resultCount > 0 && <span className="tscreener-handoff-count"> · {handoff.resultCount}종목 매칭</span>}
            </span>
            <div className="tscreener-handoff-conds">
              {handoff.conditionSummary.map((c, i) => (
                <span key={i} className="tscreener-handoff-cond">{c}</span>
              ))}
            </div>
          </div>
          <button className="tscreener-handoff-clear" onClick={() => { clearScreenerHandoff(); setHandoff(null); }}>
            ✕ 해제
          </button>
        </div>
      )}

      <div className="tbt-grid">
        {/* 설정 패널 */}
        <div className="tbt-config">
          <div className="tbt-group">
            <label className="tbt-label">Strategy Template</label>
            <select className="tbt-input" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {strategies.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            {onEditStrategy && (
              <button
                onClick={() => onEditStrategy(strategy)}
                style={{
                  marginTop: 6, fontFamily: "var(--t-mono)", fontSize: 10,
                  color: "var(--t-accent)", background: "transparent",
                  border: "1px dashed var(--t-border)", borderRadius: 2,
                  padding: "5px 8px", cursor: "pointer", textTransform: "uppercase",
                  letterSpacing: "0.05em", width: "100%",
                }}
              >
                ✎ 전략 설계에서 편집
              </button>
            )}
          </div>
          <div className="tbt-group">
            <label className="tbt-label">Asset Universe</label>
            <select className="tbt-input" value={universe} onChange={(e) => setUniverse(e.target.value)}>
              <option value="kospi50">KOSPI 50</option>
              <option value="kospi200">KOSPI 200</option>
              <option value="kosdaq150">KOSDAQ 150</option>
              {sectors.length > 0 && (
                <optgroup label="업종·테마">
                  {sectors.map((s) => (
                    <option key={s.id} value={s.id}>{s.label} ({s.size})</option>
                  ))}
                </optgroup>
              )}
              {watchlists.length > 0 && (
                <optgroup label="관심그룹">
                  {watchlists.map((w) => (
                    <option key={w.id} value={`watchlist:${w.id}`} disabled={w.tickers.length === 0}>
                      {w.name} ({w.tickers.length})
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
            <button className="tbt-watch-toggle" onClick={() => setShowWatch((v) => !v)}>
              {showWatch ? "▾" : "▸"} 관심그룹 관리 ({watchlists.length})
            </button>
          </div>
          {showWatch && (
            <div className="tbt-watch-panel">
              <div className="tbt-watch-create">
                <input type="text" className="tbt-input" value={newWatchName} placeholder="새 관심그룹 이름"
                  onChange={(e) => setNewWatchName(e.target.value)} />
                <button className="tbt-save-btn" onClick={handleCreateWatch}>추가</button>
              </div>
              {watchlists.length === 0 && (
                <div className="tbt-saved-empty">관심그룹이 없습니다. 종목코드 6자리로 직접 묶어보세요.</div>
              )}
              {watchlists.map((w) => (
                <div key={w.id} className="tbt-watch-item">
                  <div className="tbt-watch-item-head">
                    <span className="tbt-watch-name">{w.name} <span className="tbt-watch-count">{w.tickers.length}종목</span></span>
                    <button className="tbt-saved-del" onClick={() => handleDeleteWatch(w.id)} title="그룹 삭제">✕</button>
                  </div>
                  <div className="tbt-watch-chips">
                    {w.tickers.map((t) => (
                      <span key={t} className="tbt-watch-chip">
                        {t}<button onClick={() => handleRemoveTicker(w.id, t)} title="제거">×</button>
                      </span>
                    ))}
                    {w.tickers.length === 0 && <span className="tbt-watch-empty-hint">종목 없음</span>}
                  </div>
                  <div className="tbt-watch-add">
                    <input type="text" className="tbt-input" value={tickerInput[w.id] || ""} placeholder="종목코드 (예: 005930)"
                      maxLength={6}
                      onChange={(e) => setTickerInput((m) => ({ ...m, [w.id]: e.target.value.replace(/[^0-9]/g, "") }))}
                      onKeyDown={(e) => { if (e.key === "Enter") handleAddTicker(w.id); }} />
                    <button className="tbt-save-btn" onClick={() => handleAddTicker(w.id)}>+</button>
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="tbt-group">
            <label className="tbt-label">Simulation Period</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input type="text" className="tbt-input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              <input type="text" className="tbt-input" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
          </div>
          <div className="tbt-group">
            <label className="tbt-label">Max Positions ({maxTickers})</label>
            <input type="range" min="3" max="20" value={maxTickers} onChange={(e) => setMaxTickers(+e.target.value)} style={{ accentColor: "#1200ff" }} />
          </div>
          <div className="tbt-group">
            <label className="tbt-label">Initial Capital (₩)</label>
            <input type="text" className="tbt-input" value={capital.toLocaleString()} onChange={(e) => setCapital(Number(e.target.value.replace(/[^0-9]/g, "")) || 0)} />
          </div>

          {/* 고급 옵션 (접이식) */}
          <button className="tbt-advanced-toggle" onClick={() => setShowAdvanced((v) => !v)}>
            {showAdvanced ? "▾" : "▸"} 고급 옵션 (체결가·수수료·손익절)
          </button>
          {showAdvanced && (
            <div className="tbt-advanced">
              <div className="tbt-group">
                <label className="tbt-label">매수 체결가</label>
                <select className="tbt-input" value={buyFillType} onChange={(e) => setBuyFillType(e.target.value)}>
                  {fillGroups.map((g) => (
                    <optgroup key={g.id} label={g.label}>
                      {g.types.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div className="tbt-group">
                <label className="tbt-label">매도 체결가</label>
                <select className="tbt-input" value={sellFillType} onChange={(e) => setSellFillType(e.target.value)}>
                  {fillGroups.map((g) => (
                    <optgroup key={g.id} label={g.label}>
                      {g.types.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div className="tbt-divider-label">매도 정밀화</div>
              <div className="tbt-group">
                <label className="tbt-label">보유기간 매도 (일, 비우면 미적용)</label>
                <input type="text" className="tbt-input" value={maxHoldDays} placeholder="예: 20"
                  onChange={(e) => { const v = e.target.value.replace(/[^0-9]/g, ""); setMaxHoldDays(v === "" ? "" : Number(v)); }} />
              </div>
              <div className="tbt-group">
                <label className="tbt-label">최소 보유 (일, 조기청산 방지)</label>
                <input type="text" className="tbt-input" value={minHoldDays} placeholder="예: 5"
                  onChange={(e) => { const v = e.target.value.replace(/[^0-9]/g, ""); setMinHoldDays(v === "" ? "" : Number(v)); }} />
              </div>
              <div className="tbt-group">
                <label className="tbt-label">매도 비중 ({sellDividePct}% {sellDividePct < 100 ? "분할" : "전량"})</label>
                <input type="range" min="10" max="100" step="10" value={sellDividePct} onChange={(e) => setSellDividePct(+e.target.value)} style={{ accentColor: "#1200ff" }} />
              </div>
              {sellDividePct < 100 && (
                <div className="tbt-group">
                  <label className="tbt-label">분할 매도 최대 횟수 (비우면 무제한)</label>
                  <input type="text" className="tbt-input" value={maxSellDivisions} placeholder="예: 3"
                    onChange={(e) => { const v = e.target.value.replace(/[^0-9]/g, ""); setMaxSellDivisions(v === "" ? "" : Number(v)); }} />
                </div>
              )}
              <div className="tbt-divider-label">매수 정밀화</div>
              <div className="tbt-group">
                <label className="tbt-label">매수 비중 방식</label>
                <select className="tbt-input" value={buyWeightMode} onChange={(e) => setBuyWeightMode(e.target.value)}>
                  <option value="equal">동일가중 (균등 배분)</option>
                  <option value="factor">팩터가중 (점수 비례)</option>
                </select>
              </div>
              <div className="tbt-group">
                <label className="tbt-label">매수 비중 ({buyDividePct}% {buyDividePct < 100 ? "분할" : "한번에"})</label>
                <input type="range" min="10" max="100" step="10" value={buyDividePct} onChange={(e) => setBuyDividePct(+e.target.value)} style={{ accentColor: "#1200ff" }} />
              </div>
              {buyDividePct < 100 && (
                <div className="tbt-group">
                  <label className="tbt-label">분할 매수 최대 횟수 (비우면 미적용)</label>
                  <input type="text" className="tbt-input" value={maxBuyCount} placeholder="예: 3"
                    onChange={(e) => { const v = e.target.value.replace(/[^0-9]/g, ""); setMaxBuyCount(v === "" ? "" : Number(v)); }} />
                </div>
              )}
              <div className="tbt-group">
                <label className="tbt-label">일일 최대 매수 종목 (비우면 무제한)</label>
                <input type="text" className="tbt-input" value={maxBuyPerDay} placeholder="예: 2"
                  onChange={(e) => { const v = e.target.value.replace(/[^0-9]/g, ""); setMaxBuyPerDay(v === "" ? "" : Number(v)); }} />
              </div>
              <div className="tbt-divider-label">비용·손익절</div>
              <div className="tbt-group">
                <label className="tbt-label">수수료 ({(commissionBps / 100).toFixed(2)}%)</label>
                <input type="range" min="0" max="50" value={commissionBps} onChange={(e) => setCommissionBps(+e.target.value)} style={{ accentColor: "#1200ff" }} />
              </div>
              <div className="tbt-group">
                <label className="tbt-label">슬리피지 ({(slippageBps / 100).toFixed(2)}%)</label>
                <input type="range" min="0" max="30" value={slippageBps} onChange={(e) => setSlippageBps(+e.target.value)} style={{ accentColor: "#1200ff" }} />
              </div>
              <div className="tbt-group">
                <label className="tbt-label">손절 % (비우면 미적용)</label>
                <input type="text" className="tbt-input" value={stopLoss} placeholder="예: 5"
                  onChange={(e) => { const v = e.target.value.replace(/[^0-9.]/g, ""); setStopLoss(v === "" ? "" : Number(v)); }} />
              </div>
              <div className="tbt-group">
                <label className="tbt-label">익절 % (비우면 미적용)</label>
                <input type="text" className="tbt-input" value={takeProfit} placeholder="예: 15"
                  onChange={(e) => { const v = e.target.value.replace(/[^0-9.]/g, ""); setTakeProfit(v === "" ? "" : Number(v)); }} />
              </div>
            </div>
          )}

          <button className="tbt-run" onClick={run} disabled={loading}>
            {loading ? "Running Simulation..." : "Run Simulation"}
          </button>

          {/* 전략 저장/불러오기 (Phase 5-A) */}
          <div className="tbt-save-row">
            <input type="text" className="tbt-input tbt-save-name" value={saveName} placeholder="전략 이름"
              onChange={(e) => setSaveName(e.target.value)} />
            <button className="tbt-save-btn" onClick={handleSave}>저장</button>
            <button className="tbt-save-btn" onClick={() => setShowSaved((v) => !v)}>
              저장됨 ({savedList.length})
            </button>
          </div>
          {showSaved && savedList.length > 0 && (
            <div className="tbt-saved-list">
              {savedList.map((s) => (
                <div key={s.id} className="tbt-saved-item">
                  <button className="tbt-saved-apply" onClick={() => handleApply(s)} title="이 전략 불러오기">
                    <span className="tbt-saved-name">{s.name}</span>
                    <span className="tbt-saved-meta">{s.config.strategy} · {s.config.universe}</span>
                  </button>
                  <button className="tbt-saved-del" onClick={() => handleDelete(s.id)} title="삭제">✕</button>
                </div>
              ))}
            </div>
          )}
          {showSaved && savedList.length === 0 && (
            <div className="tbt-saved-empty">저장된 전략이 없습니다</div>
          )}
          {loading && (
            <div style={{ fontFamily: "var(--t-mono)", fontSize: 10, color: "var(--t-muted)", marginTop: -8, lineHeight: 1.5 }}>
              과거 시세 로드 + 전략 시뮬레이션 중...<br />최대 ~15초 소요됩니다.
            </div>
          )}

          {st && (
            <div className="tbt-quickstat">
              <div className="tbt-label" style={{ marginBottom: 8 }}>Quick Stats</div>
              TRADES: {st.num_trades}<br />
              WIN RATE: {st.win_rate}%<br />
              SHARPE: {st.sharpe_ratio}
            </div>
          )}
        </div>

        {/* 분석 뷰포트 */}
        <div className="tbt-viewport">
          {err && (
            <div className="tbt-empty" style={{ color: "#dc2626" }}>
              <div>
                <div style={{ fontFamily: "var(--t-mono)", fontSize: 11, marginBottom: 8 }}>[ ERROR ]</div>
                {err}
              </div>
            </div>
          )}

          {!result && !err && !loading && (
            <div className="tbt-empty">
              <div>
                <div style={{ fontFamily: "var(--t-mono)", fontSize: 11, marginBottom: 16 }}>[ EMPTY_STATE_NULL ]</div>
                Initialize simulation parameters to begin analysis
              </div>
            </div>
          )}

          {loading && (
            <div className="animate-fade-in">
              <div className="tbt-progress-head">
                <span className="tbt-spinner" />
                <span className="tbt-progress-label">SIMULATION RUNNING</span>
              </div>
              <BacktestProgress />
              {/* 결과 스켈레톤 미리보기 */}
              <div className="tbt-skeleton-stats">
                {[...Array(6)].map((_, i) => (
                  <div className="tbt-skeleton-card" key={i} style={{ animationDelay: `${i * 0.08}s` }}>
                    <div className="tbt-skeleton-line short" />
                    <div className="tbt-skeleton-line" />
                  </div>
                ))}
              </div>
              <div className="tbt-skeleton-chart" />
            </div>
          )}

          {result && st && (
            <div className="animate-fade-in">
              {/* 데이터 출처 배너 (Phase ① 실데이터 준비) */}
              <div className={`tbt-prov ${result.data_source.fully_real ? "real" : "mock"}`}>
                <span className="tbt-prov-dot" />
                <span className="tbt-prov-main">
                  {result.data_source.fully_real ? "실데이터 백테스트" : "Mock 데이터 백테스트"}
                </span>
                <span className="tbt-prov-detail">
                  시세 <b className={result.data_source.market_data === "kis_real" ? "on" : ""}>{result.data_source.market_data === "kis_real" ? "KIS 실데이터" : "mock"}</b>
                  <span className="tbt-prov-sep">·</span>
                  재무 <b className={result.data_source.fundamentals === "dart_real" ? "on" : ""}>{result.data_source.fundamentals === "dart_real" ? "DART 실데이터" : "mock"}</b>
                </span>
                {!result.data_source.fully_real && (
                  <span className="tbt-prov-note">결과는 합성 데이터 기준 — 실데이터는 GCP 배포 시</span>
                )}
              </div>
              {/* CSV 내보내기 툴바 (Phase 5-B) */}
              <div className="tbt-export-bar">
                <span className="tbt-export-label">내보내기</span>
                <button className="tbt-export-btn" onClick={() => exportTradesCsv((result.backtest.trades || []) as unknown as Array<Record<string, unknown>>, strategy)}>
                  거래내역 CSV
                </button>
                <button className="tbt-export-btn" onClick={() => exportSummaryCsv(st as unknown as Record<string, number>, result.backtest.monthly_returns || [], strategy)}>
                  요약·월별 CSV
                </button>
              </div>
              {/* 6개 지표 카드 */}
              <div className="tbt-stats tbt-stats-6">
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Total Return</div>
                  <div className="tbt-stat-value" style={{ color: posColor(st.total_return_pct) }}>{fmt(st.total_return_pct, "%")}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">CAGR</div>
                  <div className="tbt-stat-value" style={{ color: posColor(st.cagr) }}>{fmt(st.cagr, "%")}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Sharpe</div>
                  <div className="tbt-stat-value" style={{ color: (st.sharpe_ratio ?? 0) >= 1 ? "#16a34a" : "var(--t-ink)" }}>{fmt(st.sharpe_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Sortino</div>
                  <div className="tbt-stat-value">{fmt(st.sortino_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Calmar</div>
                  <div className="tbt-stat-value" style={{ color: (st.calmar_ratio ?? 0) >= 0 ? "var(--t-ink)" : "#dc2626" }}>{fmt(st.calmar_ratio, "", 2)}</div>
                </div>
                <div className="tbt-stat">
                  <div className="tbt-stat-label">Max DD</div>
                  <div className="tbt-stat-value" style={{ color: "#dc2626" }}>-{Math.abs(st.max_drawdown_pct)}%</div>
                </div>
              </div>

              {/* 보조 지표 바 (승률·손익비·수수료) */}
              <div className="tbt-substats">
                <span>승률 <b>{st.win_rate}%</b></span>
                <span>손익비(PF) <b style={{ color: (st.profit_factor ?? 0) >= 1 ? "#16a34a" : "#dc2626" }}>{fmt(st.profit_factor, "", 2)}</b></span>
                <span>거래 <b>{st.num_trades}회</b></span>
                <span>평균손익 <b style={{ color: posColor(st.avg_trade_return) }}>{fmt(st.avg_trade_return, "%", 2)}</b></span>
                <span>수수료 <b>₩{Math.round(st.total_commission).toLocaleString()}</b></span>
                <span>슬리피지 <b>₩{Math.round(st.total_slippage).toLocaleString()}</b></span>
              </div>

              {/* 자산 곡선 */}
              <div className="tbt-chart">
                <div className="tbt-chart-head">
                  <div className="tbt-chart-title">Equity Curve</div>
                  <div className="tbt-chart-title">{result.backtest_config.period}</div>
                </div>
                {result.backtest.benchmark?.curve && result.backtest.benchmark.curve.length > 1 && (
                  <div className="tbt-bench-legend">
                    <span className="tbt-bench-item"><span className="tbt-bench-line strat" />전략</span>
                    <span className="tbt-bench-item"><span className="tbt-bench-line bench" />{result.backtest.benchmark.label}</span>
                  </div>
                )}
                <EquityChart curve={result.backtest.equity_curve} benchmark={result.backtest.benchmark?.curve} />
                {result.backtest.benchmark && result.backtest.benchmark.curve?.length > 1 && (
                  <div className="tbt-bench-metrics">
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">벤치마크 수익</span>
                      <span className="tbt-bench-val">{result.backtest.benchmark.total_return_pct >= 0 ? "+" : ""}{result.backtest.benchmark.total_return_pct}%</span>
                    </div>
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">초과수익 (α 원천)</span>
                      <span className="tbt-bench-val" style={{ color: result.backtest.benchmark.excess_return_pct >= 0 ? "#16a34a" : "#dc2626" }}>
                        {result.backtest.benchmark.excess_return_pct >= 0 ? "+" : ""}{result.backtest.benchmark.excess_return_pct}%
                      </span>
                    </div>
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">베타 (β)</span>
                      <span className="tbt-bench-val">{result.backtest.benchmark.beta}</span>
                    </div>
                    <div className="tbt-bench-metric">
                      <span className="tbt-bench-label">알파 (α, 연율)</span>
                      <span className="tbt-bench-val">{result.backtest.benchmark.alpha_pct >= 0 ? "+" : ""}{result.backtest.benchmark.alpha_pct}%</span>
                    </div>
                  </div>
                )}
              </div>

              {/* 낙폭 곡선 (Drawdown) */}
              {result.backtest.drawdown_curve?.length > 0 && (
                <div className="tbt-chart">
                  <div className="tbt-chart-head">
                    <div className="tbt-chart-title">Drawdown</div>
                    <div className="tbt-chart-title" style={{ color: "#dc2626" }}>최대 -{Math.abs(st.max_drawdown_pct)}%</div>
                  </div>
                  <DrawdownChart curve={result.backtest.drawdown_curve} />
                </div>
              )}

              {/* 월별 수익률 히트맵 */}
              {result.backtest.monthly_returns?.length > 0 && (
                <div className="tbt-chart">
                  <div className="tbt-chart-head">
                    <div className="tbt-chart-title">Monthly Returns</div>
                  </div>
                  <MonthlyHeatmap data={result.backtest.monthly_returns} />
                </div>
              )}

              {/* 거래 내역 */}
              {result.backtest.trades?.length > 0 && (
                <div className="tbt-chart">
                  <div className="tbt-chart-head">
                    <div className="tbt-chart-title">Trade Log ({result.backtest.trades.length})</div>
                    <div className="tbt-chart-title">최근 {Math.min(15, result.backtest.trades.length)}건</div>
                  </div>
                  <TradeLog trades={result.backtest.trades} />
                </div>
              )}

              {/* 종목 + 데이터 출처 */}
              <div className="tbt-chart">
                <div className="tbt-chart-head">
                  <div className="tbt-chart-title">Constituents ({result.screened_count})</div>
                  <span style={{ fontFamily: "var(--t-mono)", fontSize: 10, padding: "2px 8px", borderRadius: 2, background: result.data_source.fully_real ? "#dcfce7" : "#fafafa", color: result.data_source.fully_real ? "#15803d" : "var(--t-muted)", border: "1px solid var(--t-border)" }}>
                    {result.data_source.fully_real ? "REAL_DATA" : "MOCK_DATA"}
                  </span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {result.screened_tickers.slice(0, 12).map((t) => (
                    <span key={t.stock_code} style={{ fontFamily: "var(--t-mono)", fontSize: 12, padding: "4px 10px", border: "1px solid var(--t-border)", borderRadius: 2 }}>
                      {t.corp_name || t.stock_code}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// 자산 곡선 SVG
function EquityChart({ curve, benchmark }: { curve: number[]; benchmark?: number[] }) {
  if (!curve || curve.length < 2) {
    return <div style={{ height: 240, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 11 }}>NO_DATA</div>;
  }
  const W = 1000, H = 240;
  // 전략·벤치마크 공통 스케일 (둘 다 같은 축에서 비교)
  const hasBench = benchmark && benchmark.length >= 2;
  const allVals = hasBench ? [...curve, ...benchmark!] : curve;
  const min = Math.min(...allVals), max = Math.max(...allVals);
  const range = max - min || 1;
  const toPts = (arr: number[]) => arr.map((v, i) => {
    const x = (i / (arr.length - 1)) * W;
    const y = H - ((v - min) / range) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const pts = toPts(curve);
  const up = curve[curve.length - 1] >= curve[0];
  const color = up ? "#16a34a" : "#dc2626";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 240, borderBottom: "1px solid var(--t-border)", borderLeft: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polygon points={`0,${H} ${pts} ${W},${H}`} fill={color} opacity="0.06" />
      {hasBench && (
        <polyline points={toPts(benchmark!)} fill="none" stroke="#71717a" strokeWidth="1.5" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" opacity="0.8" />
      )}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// 낙폭 곡선 (0 이하 음수 영역)
function DrawdownChart({ curve }: { curve: number[] }) {
  if (!curve || curve.length < 2) {
    return <div style={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--t-muted)", fontFamily: "var(--t-mono)", fontSize: 11 }}>NO_DATA</div>;
  }
  // drawdown_curve는 음수(%) 또는 비율. 절대값 최대로 정규화
  const W = 1000, H = 140;
  const vals = curve.map((v) => (v > 0 ? -v : v)); // 양수로 들어오면 음수화
  const minV = Math.min(...vals, 0);
  const range = Math.abs(minV) || 1;
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * W;
    const y = (Math.abs(v) / range) * H; // 위에서 아래로 (0=top)
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 140, borderTop: "1px solid var(--t-border)" }} preserveAspectRatio="none">
      <polygon points={`0,0 ${pts} ${W},0`} fill="#dc2626" opacity="0.08" />
      <polyline points={pts} fill="none" stroke="#dc2626" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

// 월별 수익률 히트맵
function MonthlyHeatmap({ data }: { data: Array<MonthlyReturn | number> }) {
  // data가 숫자 배열이거나 {month, return_pct} 배열 둘 다 지원
  const cells = data.map((d, i) => {
    if (typeof d === "number") return { label: `M${i + 1}`, val: d };
    return { label: d.month || `M${i + 1}`, val: d.return_pct ?? 0 };
  });
  const maxAbs = Math.max(...cells.map((c) => Math.abs(c.val)), 1);
  const colorFor = (v: number) => {
    const intensity = Math.min(1, Math.abs(v) / maxAbs);
    if (v >= 0) return `rgba(22, 163, 74, ${0.15 + intensity * 0.6})`;
    return `rgba(220, 38, 38, ${0.15 + intensity * 0.6})`;
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(64px, 1fr))", gap: 4 }}>
      {cells.map((c, i) => (
        <div key={i} style={{ padding: "10px 4px", borderRadius: 2, background: colorFor(c.val), textAlign: "center" }}>
          <div style={{ fontFamily: "var(--t-mono)", fontSize: 9, color: "var(--t-muted)", marginBottom: 2 }}>{c.label}</div>
          <div style={{ fontFamily: "var(--t-mono)", fontSize: 12, fontWeight: 600, color: c.val >= 0 ? "#15803d" : "#b91c1c" }}>
            {c.val >= 0 ? "+" : ""}{c.val.toFixed(1)}
          </div>
        </div>
      ))}
    </div>
  );
}

// 거래 내역 테이블
function TradeLog({ trades }: { trades: BacktestTrade[] }) {
  const rows = trades.slice(-15).reverse();
  const f = (v: number | undefined) => (v == null ? "—" : v.toLocaleString());
  return (
    <table className="tbt-tradelog">
      <thead>
        <tr>
          <th>종목</th><th>진입일</th><th>청산일</th>
          <th className="num">진입가</th><th className="num">청산가</th><th className="num">수익률</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((t, i) => (
          <tr key={i}>
            <td>{t.corp_name || t.stock_code || "—"}</td>
            <td>{t.entry_date || "—"}</td>
            <td>{t.exit_date || "—"}</td>
            <td className="num">{f(t.entry_price)}</td>
            <td className="num">{f(t.exit_price)}</td>
            <td className="num" style={{ color: (t.return_pct ?? 0) >= 0 ? "#16a34a" : "#dc2626", fontWeight: 600 }}>
              {t.return_pct == null ? "—" : `${t.return_pct >= 0 ? "+" : ""}${t.return_pct.toFixed(2)}%`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// 백테스트 진행 단계 표시 (15초 대기 체감 단축)
function BacktestProgress() {
  const stages = [
    "과거 시세 데이터 로드",
    "종목별 지표 계산",
    "진입·청산 시그널 생성",
    "포지션 시뮬레이션",
    "성과 지표 집계",
  ];
  const [stage, setStage] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setStage((s) => Math.min(s + 1, stages.length - 1)), 3200);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="tbt-stages">
      {stages.map((label, i) => (
        <div key={i} className={`tbt-stage${i < stage ? " done" : i === stage ? " active" : ""}`}>
          <span className="tbt-stage-dot">{i < stage ? "✓" : i + 1}</span>
          <span className="tbt-stage-label">{label}</span>
        </div>
      ))}
    </div>
  );
}
