/**
 * 매매일지 — 체결 내역 파일을 ★이 브라우저에서★ 읽어 서버가 받는 줄로 맞춘다 (설계 2026-11-14 매매일지 §4).
 * ==========================================================================
 * 순수 함수만 둔다(화면·서버 호출 없음). 흐름: 바이트 → 글자(`decodeBytes`) → 표(`parseTable`) → 열 어림(`guessMapping`) → 줄(`normalizeRows`).
 *
 * ★어림은 열 고르기까지만 한다★ — 값은 지어내지 않는다. 읽지 못한 숫자·일시는 원문 그대로 보내고, 서버가 그 줄을 사유와 함께 버린다
 * (버린 줄은 화면에 줄 번호와 사유로 보인다). 딱 하나 고치는 것: 숫자로만 된 6자리 미만 종목코드의 앞자리 0(엑셀이 지운 것) — 고친 건수를 돌려준다.
 * 서버로 가는 것은 맞춘 열뿐이다. 파일의 다른 열(계좌번호 등)은 이 함수 밖으로 나가지 않는다.
 */
import type { FillRow } from "./types";

// ── 바이트 → 글자 ────────────────────────────────────────────────────────────

export type Encoding = "UTF-8" | "UTF-16LE" | "UTF-16BE" | "EUC-KR";
export type Decoded = { text: string; encoding: Encoding };

/** BOM 을 먼저 본다. 없으면 UTF-8 로 엄격하게 읽고, 깨지면 EUC-KR(국내 HTS·엑셀의 CSV 기본값)로 읽는다. */
export function decodeBytes(buf: ArrayBuffer): Decoded {
  const b = new Uint8Array(buf);
  if (b.length >= 3 && b[0] === 0xef && b[1] === 0xbb && b[2] === 0xbf) return { text: new TextDecoder("utf-8").decode(b.subarray(3)), encoding: "UTF-8" };
  if (b.length >= 2 && b[0] === 0xff && b[1] === 0xfe) return { text: new TextDecoder("utf-16le").decode(b.subarray(2)), encoding: "UTF-16LE" };
  if (b.length >= 2 && b[0] === 0xfe && b[1] === 0xff) return { text: new TextDecoder("utf-16be").decode(b.subarray(2)), encoding: "UTF-16BE" };
  try {
    return { text: new TextDecoder("utf-8", { fatal: true }).decode(b), encoding: "UTF-8" };
  } catch {
    return { text: new TextDecoder("euc-kr").decode(b), encoding: "EUC-KR" };
  }
}

// ── 글자 → 표 ────────────────────────────────────────────────────────────────

export type Delimiter = "," | "\t" | ";" | "|";
export const DELIMITER_KO: Record<Delimiter, string> = { ",": "쉼표", "\t": "탭", ";": "세미콜론", "|": "세로선" };

export type Table = {
  headers: string[];
  rows: string[][];
  /** 자료 줄마다 파일의 몇 번째 줄에서 시작했는지(1부터) — 버린 줄을 파일의 줄 번호로 말하려고 둔다. */
  lines: number[];
  delimiter: Delimiter;
};
export type TableError = { error: string };

function splitRecords(text: string, delimiter: Delimiter): { cells: string[]; line: number }[] {
  const out: { cells: string[]; line: number }[] = [];
  let cells: string[] = [];
  let cell = "";
  let quoted = false;
  let line = 1;
  let start = 1;
  const endCell = () => { cells.push(cell); cell = ""; };
  const endRecord = () => { endCell(); out.push({ cells, line: start }); cells = []; };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false; }
      else { if (ch === "\n") line++; cell += ch; }
      continue;
    }
    if (ch === '"' && cell === "") { quoted = true; continue; }
    if (ch === delimiter) { endCell(); continue; }
    if (ch === "\r") { if (text[i + 1] === "\n") continue; endRecord(); line++; start = line; continue; }
    if (ch === "\n") { endRecord(); line++; start = line; continue; }
    cell += ch;
  }
  if (cell !== "" || cells.length) endRecord();
  return out;
}

function detectDelimiter(text: string): Delimiter | null {
  const head = text.split(/\r?\n/).find((l) => l.trim() !== "") ?? "";
  let best: Delimiter | null = null;
  let bestN = 0;
  for (const d of [",", "\t", ";", "|"] as Delimiter[]) {
    let n = 0;
    let q = false;
    for (const ch of head) { if (ch === '"') q = !q; else if (ch === d && !q) n++; }
    if (n > bestN) { best = d; bestN = n; }
  }
  return best;
}

/** 첫 줄(비지 않은 첫 줄)이 열 이름이다. 빈 줄은 건너뛴다. 열 이름이 비었거나 겹치면 "열 N" 으로 부른다. */
export function parseTable(text: string): Table | TableError {
  if (!text.trim()) return { error: "파일이 비어 있습니다." };
  const delimiter = detectDelimiter(text);
  if (!delimiter) return { error: "열 구분 기호를 찾지 못했습니다. 쉼표·탭·세미콜론으로 나뉜 텍스트 파일(CSV)만 읽습니다." };
  const records = splitRecords(text, delimiter).filter((r) => r.cells.some((c) => c.trim() !== ""));
  if (records.length < 2) return { error: "열 이름 줄 아래에 체결 줄이 없습니다." };
  const seen = new Set<string>();
  const headers = records[0].cells.map((raw, i) => {
    const h = raw.trim();
    const name = h && !seen.has(h) ? h : `열 ${i + 1}`;
    seen.add(name);
    return name;
  });
  const body = records.slice(1);
  return { headers, rows: body.map((r) => r.cells), lines: body.map((r) => r.line), delimiter };
}

// ── 열 어림 ──────────────────────────────────────────────────────────────────

export type FieldKey = "date" | "time" | "symbol" | "name" | "side" | "quantity" | "price" | "fee" | "tax" | "market" | "instrument";
export type Mapping = Record<FieldKey, number | null>;

export const REQUIRED: FieldKey[] = ["date", "symbol", "side", "quantity", "price"];
export const FIELD_KO: Record<FieldKey, string> = {
  date: "체결 일시", time: "체결 시각", symbol: "종목", name: "종목명", side: "매수·매도", quantity: "수량", price: "단가",
  fee: "수수료", tax: "세금", market: "시장", instrument: "상품 구분",
};

/** 앞의 것부터 찾는다 — 더 구체적인 이름(체결수량)이 일반적인 이름(수량)보다 먼저다. */
const PATTERNS: [FieldKey, RegExp[]][] = [
  ["date", [/체결\s*일시/, /거래\s*일시/, /주문\s*일시/, /일시/, /체결\s*일자?$/, /거래\s*일자?$/, /매매\s*일자?$/, /일자|날짜/, /date/i]],
  ["time", [/체결\s*시[간각]/, /거래\s*시[간각]/, /주문\s*시[간각]/, /시[간각]/, /time/i]],
  ["symbol", [/종목\s*코드/, /단축\s*코드/, /코드/, /symbol|ticker|code/i, /종목\s*명/, /종목/]],
  ["name", [/종목\s*명/, /종목/, /name/i]],
  ["side", [/매매\s*구분/, /매수\s*매도/, /매도\s*매수/, /거래\s*구분/, /구분/, /매매/, /side|buy.?sell/i]],
  ["quantity", [/체결\s*수량/, /거래\s*수량/, /수량/, /qty|quantity|shares/i]],
  ["price", [/체결\s*단가/, /체결\s*가$/, /거래\s*단가/, /단가/, /가격/, /price/i]],
  ["fee", [/수수료/, /commission|fee/i]],
  ["tax", [/제?세금/, /거래세/, /tax/i]],
  ["market", [/시장/, /market/i]],
  ["instrument", [/상품/, /instrument|asset.?type/i]],
];
const HAS_TIME = /일시|date.?time|timestamp/i;

export function guessMapping(headers: string[]): Mapping {
  const map: Mapping = { date: null, time: null, symbol: null, name: null, side: null, quantity: null, price: null, fee: null, tax: null, market: null, instrument: null };
  const taken = new Set<number>();
  for (const [field, patterns] of PATTERNS) {
    if (field === "time" && map.date !== null && HAS_TIME.test(headers[map.date])) continue;      // 일시 열이 시각까지 갖고 있다
    for (const p of patterns) {
      const i = headers.findIndex((h, k) => !taken.has(k) && p.test(h));
      if (i >= 0) { map[field] = i; taken.add(i); break; }
    }
  }
  return map;
}

export const missingRequired = (m: Mapping): FieldKey[] => REQUIRED.filter((f) => m[f] === null);

// ── 값 읽기 ──────────────────────────────────────────────────────────────────

const pad2 = (n: number) => String(n).padStart(2, "0");

/** 시각 글자 → "HH:MM:SS". 비었으면 `""`(날짜만), 읽지 못하면 `null`. */
export function toTime(raw: string): string | null {
  const s = raw.trim();
  if (!s) return "";
  let m = s.match(/^(오전|오후|AM|PM)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*(오전|오후|AM|PM)?$/i);
  let h: number, mi: number, se: number;
  if (m) {
    const half = (m[1] ?? m[5] ?? "").toUpperCase();
    h = Number(m[2]); mi = Number(m[3]); se = Number(m[4] ?? 0);
    if (half) {
      if (h < 1 || h > 12) return null;
      const pm = half === "오후" || half === "PM";
      h = (h % 12) + (pm ? 12 : 0);
    }
  } else if ((m = s.match(/^(\d{2})(\d{2})(\d{2})?$/))) {
    h = Number(m[1]); mi = Number(m[2]); se = Number(m[3] ?? 0);
  } else if ((m = s.match(/^(\d{1,2})시\s*(\d{1,2})분(?:\s*(\d{1,2})초)?$/))) {
    h = Number(m[1]); mi = Number(m[2]); se = Number(m[3] ?? 0);
  } else return null;
  return h <= 23 && mi <= 59 && se <= 59 ? `${pad2(h)}:${pad2(mi)}:${pad2(se)}` : null;
}

/**
 * 일시 글자(+ 따로 있는 시각 열) → "YYYY-MM-DD HH:MM:SS" 또는 날짜만 "YYYY-MM-DD".
 * ★읽지 못하면 원문을 그대로 돌려준다★ — 서버가 그 줄을 '체결 일시를 읽지 못했습니다' 로 버린다(조용히 고치지 않는다).
 */
export function toDateTime(dateRaw: string, timeRaw = ""): string {
  const s = dateRaw.trim();
  const raw = [s, timeRaw.trim()].filter(Boolean).join(" ");
  const m = s.match(/^(\d{4})[-./]\s?(\d{1,2})[-./]\s?(\d{1,2})\.?(?:[ T]+(.+))?$/)
    ?? s.match(/^(\d{4})(\d{2})(\d{2})(?:[ T]*(.+))?$/)
    ?? s.match(/^(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일(?:\s*(.+))?$/);
  if (!m) return raw;
  const [mo, d] = [Number(m[2]), Number(m[3])];
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return raw;
  const date = `${m[1]}-${pad2(mo)}-${pad2(d)}`;
  const time = toTime(m[4] ?? timeRaw);
  if (time === null) return raw;
  return time ? `${date} ${time}` : date;
}

/** 숫자 글자 → 수. 쉼표·공백·끝의 '원'·'주'를 걷는다. 비었으면 `null`, ★읽지 못하면 원문 그대로★(서버가 사유와 함께 버린다). */
export function toNumber(raw: string | undefined): number | string | null {
  const s = (raw ?? "").trim();
  if (!s || s === "-") return null;                 // '-' 는 빈칸으로 본다(0 으로 읽지 않는다)
  const t = s.replace(/[,\s]/g, "").replace(/(원|주|KRW)$/i, "");
  return /^[-+]?\d+(\.\d+)?$/.test(t) ? Number(t) : s;
}

/** 종목 글자 — 엑셀이 붙인 글자 표지(`'005930` · `="005930"`)를 걷고, 숫자로만 된 6자리 미만 코드는 앞에 0 을 채운다. */
export function toSymbol(raw: string | undefined): { symbol: string; padded: boolean } {
  const s = (raw ?? "").trim().replace(/^="(.*)"$/, "$1").replace(/^'/, "").trim();
  if (/^\d{1,5}$/.test(s)) return { symbol: s.padStart(6, "0"), padded: true };
  return { symbol: s, padded: false };
}

export type Side = "buy" | "sell";
/** 매수·매도 글자의 어림 — 숫자 코드(1·2)는 증권사마다 뜻이 달라 어림하지 않는다(사용자가 고른다). */
export function guessSide(value: string): Side | null {
  const v = value.trim();
  const buy = /매수|^buy$|^b$/i.test(v), sell = /매도|^sell$|^s$/i.test(v);
  return buy === sell ? null : buy ? "buy" : "sell";
}

export function toMarket(raw: string | undefined): "KOSPI" | "KOSDAQ" | "KONEX" | null {
  const v = (raw ?? "").trim();
  if (/코스닥|kosdaq/i.test(v)) return "KOSDAQ";
  if (/코넥스|konex/i.test(v)) return "KONEX";
  if (/코스피|kospi|유가/i.test(v)) return "KOSPI";
  return null;
}

export function toInstrument(raw: string | undefined): "stock" | "etf" | null {
  const v = (raw ?? "").trim();
  if (/^etf$/i.test(v)) return "etf";
  if (/^(주식|보통주|우선주|stock)$/i.test(v)) return "stock";
  return null;
}

/** 한 열의 서로 다른 값(나온 순서) — 매수·매도 값 대응을 고르게 하려고 쓴다. */
export function distinctValues(table: Table, col: number, limit = 12): { values: string[]; more: boolean } {
  const seen: string[] = [];
  const set = new Set<string>();
  for (const r of table.rows) {
    const v = (r[col] ?? "").trim();
    if (set.has(v)) continue;
    set.add(v);
    if (seen.length < limit) seen.push(v);
  }
  return { values: seen, more: set.size > seen.length };
}

// ── 표 → 서버가 받는 줄 ──────────────────────────────────────────────────────

export type SideChoice = Side | "skip";
export type NormalizeOptions = {
  mapping: Mapping;
  /** 매수·매도 열의 값 → 뜻. 여기 없는 값은 `null` 로 보낸다(서버가 '매수·매도를 알 수 없습니다' 로 버린다). */
  sides: Record<string, SideChoice>;
  feeFromFile: boolean;
  taxFromFile: boolean;
};
export type Normalized = {
  fills: FillRow[];
  /** `fills[i]` 가 파일의 몇 번째 줄인지. */
  lines: number[];
  /** '제외'로 지정해 보내지 않은 줄 수(입금·출금처럼 체결이 아닌 줄). */
  skipped: number;
  /** 앞자리 0 을 채운 종목코드의 줄 수. */
  padded: number;
};

export function normalizeRows(table: Table, o: NormalizeOptions): Normalized {
  const m = o.mapping;
  const at = (r: string[], f: FieldKey) => (m[f] === null ? undefined : r[m[f] as number]);
  const fills: FillRow[] = [];
  const lines: number[] = [];
  let skipped = 0, padded = 0;
  table.rows.forEach((r, i) => {
    const sideRaw = (at(r, "side") ?? "").trim();
    const choice = o.sides[sideRaw] ?? null;
    if (choice === "skip") { skipped++; return; }
    const sym = toSymbol(at(r, "symbol"));
    if (sym.padded) padded++;
    const row: FillRow = {
      executed_at: toDateTime(at(r, "date") ?? "", at(r, "time") ?? "") || null,
      symbol: sym.symbol || null,
      side: choice,
      quantity: toNumber(at(r, "quantity")),
      price: toNumber(at(r, "price")),
    };
    if (o.feeFromFile && m.fee !== null) row.fee = toNumber(at(r, "fee"));
    if (o.taxFromFile && m.tax !== null) row.tax = toNumber(at(r, "tax"));
    const market = toMarket(at(r, "market"));
    if (market) row.market = market;
    const instrument = toInstrument(at(r, "instrument"));
    if (instrument) row.instrument = instrument;
    const name = (at(r, "name") ?? "").trim();
    if (name) row.name = name;
    fills.push(row);
    lines.push(table.lines[i]);
  });
  return { fills, lines, skipped, padded };
}
