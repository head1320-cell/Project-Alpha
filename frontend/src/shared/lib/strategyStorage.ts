// 백테스트 전략 저장/불러오기 + CSV 내보내기 (Phase 5-A, 5-B)
// 전략 설정 전체를 localStorage에 보관. 서버 불필요 — 브라우저 로컬.

export interface SavedStrategy {
  id: string;
  name: string;
  savedAt: string;
  config: {
    strategy: string;
    universe: string;
    startDate: string;
    endDate: string;
    maxTickers: number;
    capital: number;
    commissionBps: number;
    slippageBps: number;
    stopLoss: number | "";
    takeProfit: number | "";
    buyFillType: string;
    sellFillType: string;
    maxHoldDays: number | "";
    minHoldDays: number | "";
    sellDividePct: number;
    maxSellDivisions: number | "";
    buyWeightMode: string;
    buyDividePct: number;
    maxBuyPerDay: number | "";
    maxBuyCount: number | "";
  };
}

const KEY = "alpha_saved_strategies";

export function listStrategies(): SavedStrategy[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function saveStrategy(name: string, config: SavedStrategy["config"]): SavedStrategy {
  const list = listStrategies();
  const item: SavedStrategy = {
    id: `strat_${Date.now()}`,
    name: name.trim() || `전략 ${list.length + 1}`,
    savedAt: new Date().toISOString(),
    config,
  };
  list.unshift(item);
  // 최대 30개 보관
  localStorage.setItem(KEY, JSON.stringify(list.slice(0, 30)));
  return item;
}

export function deleteStrategy(id: string): void {
  const list = listStrategies().filter((s) => s.id !== id);
  localStorage.setItem(KEY, JSON.stringify(list));
}

// ─── CSV 내보내기 ───

function downloadCsv(filename: string, rows: (string | number)[][]): void {
  const csv = rows.map((r) => r.map((c) => {
    const s = String(c ?? "");
    // 콤마·따옴표·줄바꿈 포함 시 이스케이프
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }).join(",")).join("\n");
  // BOM 추가 (엑셀 한글 깨짐 방지)
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function exportTradesCsv(trades: Array<Record<string, unknown>>, strategyName: string): void {
  const header = ["날짜", "종목", "구분", "체결가", "수량", "금액", "손익", "사유"];
  const rows: (string | number)[][] = [header];
  for (const t of trades) {
    const side = String(t.side ?? "");
    const price = Number(t.price ?? t.entry_price ?? 0);
    const qty = Number(t.quantity ?? 0);
    const val = Number(t.value ?? 0);
    const pnl = t.pnl != null ? Math.round(Number(t.pnl)) : "";
    rows.push([
      String(t.date ?? t.entry_date ?? ""),
      String(t.ticker ?? t.stock_code ?? ""),
      side === "buy" ? "매수" : side === "sell" ? "매도" : side,
      Math.round(price), qty, Math.round(val), pnl, String(t.reason ?? ""),
    ]);
  }
  downloadCsv(`${strategyName}_거래내역.csv`, rows);
}

interface MonthlyRow { month?: string; return_pct?: number }

export function exportSummaryCsv(
  stats: Record<string, number>,
  monthly: Array<MonthlyRow | number>,
  strategyName: string,
): void {
  const rows: (string | number)[][] = [];
  // 지표 섹션
  rows.push(["지표", "값"]);
  const metricLabels: Record<string, string> = {
    total_return_pct: "총수익률(%)", cagr: "CAGR(%)", sharpe_ratio: "샤프",
    sortino_ratio: "소르티노", calmar_ratio: "칼마", max_drawdown_pct: "최대낙폭(%)",
    win_rate: "승률(%)", num_trades: "거래수", profit_factor: "손익비",
  };
  for (const [k, label] of Object.entries(metricLabels)) {
    if (stats[k] != null) rows.push([label, stats[k]]);
  }
  // 월별 수익 섹션
  rows.push([]);
  rows.push(["월", "수익률(%)"]);
  monthly.forEach((m, i) => {
    if (typeof m === "number") rows.push([`M${i + 1}`, m]);
    else rows.push([m.month || `M${i + 1}`, m.return_pct ?? 0]);
  });
  downloadCsv(`${strategyName}_요약.csv`, rows);
}
