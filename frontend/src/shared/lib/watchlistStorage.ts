// 관심그룹 (Watchlist) 저장/관리 — 사용자가 종목을 직접 묶어 백테스트 유니버스로 사용 (Phase ③)
// localStorage 기반. 종목 코드 리스트를 이름 붙여 보관.

export interface Watchlist {
  id: string;
  name: string;
  tickers: string[];
  updatedAt: string;
}

const KEY = "alpha_watchlists";

export function listWatchlists(): Watchlist[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function persist(list: Watchlist[]): void {
  localStorage.setItem(KEY, JSON.stringify(list.slice(0, 30)));
}

export function createWatchlist(name: string, tickers: string[] = []): Watchlist {
  const list = listWatchlists();
  const item: Watchlist = {
    id: `wl_${Date.now()}`,
    name: name.trim() || `관심그룹 ${list.length + 1}`,
    tickers: dedupeTickers(tickers),
    updatedAt: new Date().toISOString(),
  };
  list.unshift(item);
  persist(list);
  return item;
}

export function updateWatchlist(id: string, tickers: string[]): void {
  const list = listWatchlists();
  const wl = list.find((w) => w.id === id);
  if (!wl) return;
  wl.tickers = dedupeTickers(tickers);
  wl.updatedAt = new Date().toISOString();
  persist(list);
}

export function deleteWatchlist(id: string): void {
  persist(listWatchlists().filter((w) => w.id !== id));
}

export function addTicker(id: string, ticker: string): void {
  const code = normalizeTicker(ticker);
  if (!code) return;
  const list = listWatchlists();
  const wl = list.find((w) => w.id === id);
  if (!wl) return;
  if (!wl.tickers.includes(code)) {
    wl.tickers.push(code);
    wl.updatedAt = new Date().toISOString();
    persist(list);
  }
}

export function removeTicker(id: string, ticker: string): void {
  const list = listWatchlists();
  const wl = list.find((w) => w.id === id);
  if (!wl) return;
  wl.tickers = wl.tickers.filter((t) => t !== ticker);
  wl.updatedAt = new Date().toISOString();
  persist(list);
}

// 종목코드 정규화: 6자리 숫자만 (한국 종목코드)
function normalizeTicker(raw: string): string {
  const s = (raw || "").trim().replace(/[^0-9]/g, "");
  return s.length === 6 ? s : "";
}

function dedupeTickers(tickers: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const t of tickers) {
    const c = normalizeTicker(t);
    if (c && !seen.has(c)) {
      seen.add(c);
      out.push(c);
    }
  }
  return out;
}
