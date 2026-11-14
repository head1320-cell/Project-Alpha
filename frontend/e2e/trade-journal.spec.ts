import path from "node:path";
import { test, expect, type Page, type Request } from "./fixtures";
import { contrastAudit, voiceAudit, type AuditResult, type VoiceResult } from "./helpers";

// ════════════════════════════════════════════════════════════════════════════
// 매매일지 v1 — `/trade-journal` (★실제 서버★ — 계산을 가로채지 않는다. 설계 `docs/superpowers/specs/2026-11-14-trade-journal-design.md`)
// ────────────────────────────────────────────────────────────────────────────
// 체결 내역 파일 → 열 맞추기 → 결과. 거는 것:
//  · ★화면의 값 = 손으로 계산한 값★(거래 여섯 — 계산 과정은 `tests/test_trade_journal_analyze.py` 머리)
//  · 파일은 브라우저에서 읽는다 — 서버로 가는 본문에는 맞춘 열만(계좌번호 열은 나가지 않는다)
//  · EUC-KR · UTF-16(탭) · 날짜와 시각이 두 열 · 오전/오후 · 쉼표 숫자 · 앞자리 0 이 빠진 코드
//  · ★미상 ≠ 0★ — 수수료를 모르면 비용 후는 N/A + 사유(짝: 요율을 넣으면 값) · 시장을 모르면 세금 미상(짝: 가정을 고르면 '가정' 표지)
//  · 버린 줄은 파일의 줄 번호와 서버 사유로 · 매수 없는 매도 · 미청산은 따로
//  · 상한 초과는 서버 사유 그대로(잘라 계산하지 않는다) · 로그인 만료 · 서버 실패는 재시도
//  · 곡선의 읽는 줄(키보드) · 라이트/다크 AA · 문체(개조식 + 합니다체 · 줄표 없음 · 툴팁 없음) · 390px
// ════════════════════════════════════════════════════════════════════════════

const API = "/api/backend/api/v1";
const FIX = path.join(__dirname, "fixtures", "trade-journal");
const MINUS = "−";

async function login(page: Page): Promise<void> {
  const r = await page.request.post(`${API}/auth/login`, { data: { username: "admin", password: "frm123!" } });
  expect(r.ok(), await r.text()).toBe(true);
  const token = (await r.json()).access_token as string;
  await page.addInitScript((t) => { try { localStorage.setItem("project-alpha.auth-token", t); } catch { /* */ } }, token);
}

async function open(page: Page) {
  await login(page);
  await page.goto("/trade-journal", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".tj-file")).toBeVisible();
}

const upload = (page: Page, file: string | { name: string; mimeType: string; buffer: Buffer }) =>
  page.locator(".tj-file-input").setInputFiles(typeof file === "string" ? path.join(FIX, file) : file);

const csv = (name: string, text: string) => ({ name, mimeType: "text/csv", buffer: Buffer.from(text, "utf-8") });

const col = (page: Page, field: string) => page.locator(`select.tj-col[data-field="${field}"]`);
const picked = async (page: Page, field: string) => col(page, field).evaluate((el) => (el as HTMLSelectElement).selectedOptions[0]?.textContent ?? "");

async function setRate(page: Page, pctText: string) {
  await page.locator(".tj-fee-mode").getByRole("radio", { name: "요율 입력" }).click();
  await page.locator(".tj-fee-rate").fill(pctText);
}

async function run(page: Page): Promise<Request> {
  const sent = page.waitForRequest((r) => r.url().includes("/trade-journal/analyze") && r.method() === "POST");
  await page.locator(".tj-run").click();
  const req = await sent;
  await expect(page.locator(".tj-result")).toBeVisible();
  return req;
}

const sum = (page: Page, k: string, side: "gross" | "net") => page.locator(`.tj-sum tr[data-k="${k}"] .tj-sum-${side}`);
const cost = (page: Page, k: string) => page.locator(`.tj-costs [data-k="${k}"]`);
const bucket = (page: Page, key: string) => page.locator(`.tj-bucket-row[data-key="${key}"]`);
const tab = (page: Page, name: string) => page.locator(".tj-buckets").getByRole("tab", { name });

test("로그인 전에는 로그인하라고만 말한다 · 메뉴에 '매매일지'", async ({ page }) => {
  await page.goto("/trade-journal", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".tj-signed-out")).toContainText("로그인");
  await expect(page.locator(".tj-signed-out a")).toHaveAttribute("href", /\/login\?next=%2Ftrade-journal/);
  await expect(page.locator('.nav-item[href="/trade-journal"]')).toContainText("매매일지");
  await expect(page.locator(".tj-file")).toHaveCount(0);
});

test("파일 → 열 어림 → 분석: 화면의 값이 손 계산과 같다 · 서버로는 맞춘 열만 간다", async ({ page }) => {
  await open(page);
  await upload(page, "six-trades.csv");
  await expect(page.locator(".tj-file-meta")).toContainText("six-trades.csv");
  await expect(page.locator(".tj-file-meta")).toContainText("UTF-8");
  await expect(page.locator(".tj-file-meta")).toContainText("12줄");

  // 열 어림 — 이름으로 골라져 있다
  expect(await picked(page, "date")).toBe("체결일시");
  expect(await picked(page, "symbol")).toBe("종목코드");
  expect(await picked(page, "name")).toBe("종목명");
  expect(await picked(page, "side")).toBe("매매구분");
  expect(await picked(page, "quantity")).toBe("체결수량");
  expect(await picked(page, "price")).toBe("체결단가");
  expect(await picked(page, "market")).toBe("시장");
  expect(await picked(page, "instrument")).toBe("상품");
  await expect(page.locator('.tj-side-row[data-value="매수"] [aria-checked="true"]')).toHaveText("매수");
  await expect(page.locator('.tj-side-row[data-value="매도"] [aria-checked="true"]')).toHaveText("매도");
  // 미리 보기 — 쉼표 숫자를 수로 읽었다
  await expect(page.locator(".tj-preview tbody tr")).toHaveCount(5);
  await expect(page.locator(".tj-preview tbody tr").first()).toContainText("10,000");

  await setRate(page, "0.1");
  const req = await run(page);

  // ── 서버로 간 본문: 맞춘 열만 ──
  const body = req.postDataJSON() as { fills: Record<string, unknown>[]; commission_bp: number; unknown_market: unknown };
  expect(body.commission_bp).toBe(10);
  expect(body.unknown_market).toBeNull();
  expect(body.fills).toHaveLength(12);
  expect(body.fills[1]).toEqual({ executed_at: "2026-03-04 09:00:40", symbol: "TJA001", side: "sell", quantity: 100, price: 10200,
                                  market: "KOSPI", instrument: "stock", name: "시험 종목 A" });
  expect(req.postData() ?? "").not.toContain("5012-88-123456");
  expect(req.postData() ?? "").not.toContain("계좌번호");

  // ── 답 ──
  await expect(page.locator(".tj-result .tx-answer-s")).toContainText("거래 6건");
  await expect(page.locator(".tj-result .tx-answer-s")).toContainText("비용 후 실현손익 +27,175원");

  // ── 요약: 비용 전 | 비용 후 ──
  await expect(sum(page, "n", "gross")).toHaveText("6건");
  await expect(sum(page, "win_rate", "net")).toHaveText("50.0%");
  await expect(sum(page, "avg_win", "net")).toHaveText("+22,053원");
  await expect(sum(page, "avg_loss", "net")).toHaveText(`${MINUS}12,995원`);
  await expect(sum(page, "payoff", "net")).toHaveText("1.70");
  await expect(sum(page, "payoff", "gross")).toHaveText("3.20");
  await expect(sum(page, "expectancy", "net")).toHaveText("+4,529원");
  await expect(sum(page, "profit_factor", "net")).toHaveText("1.70");
  await expect(sum(page, "breakeven", "net")).toHaveText("37.1%");
  await expect(sum(page, "edge", "net")).toHaveText("+12.9%p");
  await expect(sum(page, "total", "gross")).toHaveText("+55,000원");
  await expect(sum(page, "total", "net")).toHaveText("+27,175원");
  await expect(sum(page, "streak", "net")).toHaveText(`2회 · ${MINUS}22,995원`);
  await expect(page.locator(".tj-small-sample")).toContainText("30건 미만");

  // ── 비용 ──
  await expect(cost(page, "fees")).toContainText("16,875원");
  await expect(cost(page, "taxes")).toContainText("10,950원");
  await expect(cost(page, "total")).toContainText("27,825원");
  await expect(page.locator(".tj-costs-read")).toContainText("50.6%");
  await expect(page.locator(".tj-costs-read")).toContainText("16.5bp");
  await expect(page.locator(".tj-costs .tj-basis-tag", { hasText: "가정" }).first()).toBeVisible();
  await expect(page.locator(".tj-costs .tj-basis-tag", { hasText: "추론" }).first()).toBeVisible();

  // ── 곡선: 읽는 줄은 마지막 거래에서 시작한다 ──
  await expect(page.locator(".tj-curve")).toBeVisible();
  await expect(page.locator(".tj-curve-read")).toContainText("+27,175원");
  await expect(page.locator(".tj-curve-read")).toContainText("15,990원");
  await expect(page.locator(".tj-curve-max")).toContainText("22,995원");

  // ── 구간별 ──
  await expect(bucket(page, "lt_1m")).toContainText("1건");
  await expect(bucket(page, "5m_30m")).toContainText("2건");
  await expect(bucket(page, "5m_30m")).toContainText(`${MINUS}25,015원`);
  await expect(bucket(page, "overnight")).toContainText("+22,310원");
  await tab(page, "진입 시간대").click();
  await expect(bucket(page, "9")).toContainText("4건");
  await expect(bucket(page, "10")).toContainText("2건");
  await tab(page, "요일").click();
  await expect(page.locator(".tj-bucket-row")).toHaveCount(3);
  await expect(bucket(page, "2")).toContainText("수");
  await tab(page, "일별").click();
  await expect(bucket(page, "2026-03-04")).toContainText("+20,855원");
  await expect(bucket(page, "2026-03-06")).toContainText("+6,320원");
  await tab(page, "종목").click();
  await expect(page.locator(".tj-bucket-row").first()).toContainText("시험 종목 C");
  await expect(bucket(page, "TJE004")).toContainText(`${MINUS}15,990원`);

  // ── 손실 직후 진입 ──
  await expect(page.locator('.tj-after-loss [data-k="after"]')).toContainText("1건");
  await expect(page.locator('.tj-after-loss [data-k="after"]')).toContainText(`${MINUS}9,025원`);
  await expect(page.locator('.tj-after-loss [data-k="other"]')).toContainText("5건");
  await expect(page.locator(".tj-after-loss")).toContainText("10분");

  // ── 가장 큰 손실 · 거래 표 ──
  await expect(page.locator(".tj-worst li").first()).toContainText("시험 ETF");
  await expect(page.locator(".tj-worst li").first()).toContainText(`${MINUS}15,990원`);
  await expect(page.locator(".tj-trades tbody tr")).toHaveCount(6);
  await expect(page.locator(".tj-trades tbody tr").first()).toContainText("+15,940원");
  await expect(page.locator(".tj-trades tbody tr").first()).toContainText("40초");

  // ── 근거와 범위 ──
  await expect(page.locator(".tj-basis")).toContainText("20bp");
  await expect(page.locator(".tj-basis")).toContainText("T1");
  await expect(page.locator(".tj-basis a").first()).toHaveAttribute("href", /^https:\/\//);
  await expect(page.locator(".tj-not-covered li")).not.toHaveCount(0);
  await expect(page.locator(".tj-not-covered")).toContainText("양도소득세");
  await expect(page.locator(".tj-excluded")).toContainText("버린 줄 0건");
});

test("EUC-KR 파일도 깨지지 않는다 — 열 이름을 한글로 읽고 같은 답을 낸다", async ({ page }) => {
  await open(page);
  await upload(page, "six-trades-euckr.csv");
  await expect(page.locator(".tj-file-meta")).toContainText("EUC-KR");
  expect(await picked(page, "side")).toBe("매매구분");
  await expect(page.locator(".tj-preview")).toContainText("시험 종목 A");
  await setRate(page, "0.1");
  await run(page);
  await expect(sum(page, "total", "net")).toHaveText("+27,175원");
  await expect(page.locator(".tj-trades")).toContainText("시험 ETF");
});

test("탭 구분 · UTF-16 · 날짜와 시각이 두 열 · 오전/오후 · 빠진 앞자리 0 · 파일의 수수료·세금은 '관측'", async ({ page }) => {
  await open(page);
  await upload(page, "split-datetime.tsv");
  await expect(page.locator(".tj-file-meta")).toContainText("UTF-16");
  await expect(page.locator(".tj-file-meta")).toContainText("탭");
  expect(await picked(page, "date")).toBe("거래일자");
  expect(await picked(page, "time")).toBe("거래시간");
  expect(await picked(page, "fee")).toBe("수수료");
  expect(await picked(page, "tax")).toBe("제세금");
  await expect(page.locator(".tj-fee-mode [aria-checked='true']")).toHaveText("파일의 열");
  await expect(page.locator(".tj-tax-mode [aria-checked='true']")).toHaveText("파일의 열");
  await expect(page.locator(".tj-padded")).toContainText("4줄");
  // '입금' 은 매수도 매도도 아니다 — 어림하지 않고 사용자가 고르게 둔다
  await expect(page.locator('.tj-side-row[data-value="입금"] [aria-checked="true"]')).toHaveCount(0);
  await expect(page.locator(".tj-run")).toBeDisabled();
  await expect(page.locator(".tj-map-miss")).toContainText("입금");
  await page.locator('.tj-side-row[data-value="입금"]').getByRole("radio", { name: "제외" }).click();

  const req = await run(page);
  const body = req.postDataJSON() as { fills: Record<string, unknown>[]; commission_bp: unknown };
  expect(body.fills).toHaveLength(4);
  expect(body.commission_bp).toBeNull();
  expect(body.fills[1]).toEqual({ executed_at: "2026-03-04 13:30:00", symbol: "005930", side: "sell", quantity: 10, price: 71000,
                                  fee: 106, tax: 1420, market: "KOSPI" });

  await expect(sum(page, "total", "gross")).toHaveText("+5,000원");
  await expect(sum(page, "total", "net")).toHaveText("+1,886원");
  await expect(cost(page, "fees")).toContainText("404원");
  await expect(cost(page, "taxes")).toContainText("2,710원");
  await expect(page.locator(".tj-costs .tj-basis-tag", { hasText: "관측" }).first()).toBeVisible();
  await expect(page.locator(".tj-costs .tj-basis-tag", { hasText: "추론" })).toHaveCount(0);
  await expect(page.locator(".tj-trades tbody tr").first()).toContainText("삼성전자");      // 이름은 서버의 종목 마스터
  await expect(page.locator(".tj-excluded")).toContainText("제외로 지정한 줄 1건");
});

test("★미상 ≠ 0★ 수수료를 모르면 비용 후는 N/A + 사유 · 곡선은 비용 전 기준이라고 말한다(짝: 요율 0 은 값이다)", async ({ page }) => {
  await open(page);
  await upload(page, "six-trades.csv");
  await expect(page.locator(".tj-fee-mode [aria-checked='true']")).toHaveText("모름");      // 요율을 지어 넣지 않는다
  await run(page);
  await expect(page.locator(".tj-result .tx-answer-s")).toContainText("비용 전 실현손익 +55,000원");
  await expect(sum(page, "total", "net")).toContainText("N/A");
  await expect(sum(page, "win_rate", "net")).toContainText("N/A");
  await expect(page.locator(".tj-net-missing")).toContainText("6건");
  await expect(page.locator(".tj-net-missing")).toContainText("수수료");
  await expect(cost(page, "fees")).toContainText("N/A");
  await expect(cost(page, "taxes")).toContainText("10,950원");          // 아는 성분은 그대로
  await expect(cost(page, "total")).toContainText("N/A");
  await expect(page.locator(".tj-curve-basis")).toContainText("비용 전");
  await expect(page.locator(".tj-trades tbody tr").first()).toContainText("N/A");
  await expect(page.locator(".tj-result")).not.toContainText("+27,175원");

  // 짝 — 0% 는 사용자가 준 값이다(수수료 0 계좌)
  await setRate(page, "0");
  await run(page);
  await expect(sum(page, "total", "net")).toHaveText("+44,050원");       // 55,000 − 세금 10,950
  await expect(cost(page, "fees")).toContainText("0원");
});

test("시장을 모르는 종목의 세금은 미상이다 — 가정을 고르면 '가정' 표지와 함께 계산한다", async ({ page }) => {
  await open(page);
  await upload(page, csv("no-market.csv", [
    "일시,종목,구분,수량,단가",
    "2026-03-04 09:00:00,ZZTJ01,매수,100,10000", "2026-03-04 09:30:00,ZZTJ01,매도,100,10200",
  ].join("\n")));
  expect(await picked(page, "market")).toBe("선택 안 함");
  await setRate(page, "0.1");
  await run(page);
  await expect(sum(page, "total", "gross")).toHaveText("+20,000원");
  await expect(sum(page, "total", "net")).toContainText("N/A");
  await expect(page.locator(".tj-net-missing")).toContainText("시장·상품 구분");
  await expect(cost(page, "taxes")).toContainText("N/A");

  await page.locator(".tj-unknown-market").getByRole("radio", { name: "코스피 주식으로 가정" }).click();
  const req = await run(page);
  expect((req.postDataJSON() as { unknown_market: string; unknown_instrument: string }).unknown_market).toBe("KOSPI");
  expect((req.postDataJSON() as { unknown_instrument: string }).unknown_instrument).toBe("stock");
  await expect(sum(page, "total", "net")).toHaveText("+15,940원");
  await expect(cost(page, "taxes")).toContainText("2,040원");
  await expect(cost(page, "taxes").locator(".tj-basis-tag")).toHaveText("가정");
});

test("버린 줄은 파일의 줄 번호와 서버 사유로 · 매수 없는 매도 · 미청산은 따로 적는다", async ({ page }) => {
  await open(page);
  await upload(page, csv("messy.csv", [
    "체결일시,종목코드,매매구분,수량,단가,시장",
    "2026-03-04 09:00:00,ZZTJ01,매수,100,10000,코스피",
    "어제 아침,ZZTJ01,매도,100,10200,코스피",                       // 3번째 줄 — 일시를 읽지 못한다
    "2026-03-04 09:20:00,ZZTJ01,매도,0,10200,코스피",               // 4번째 줄 — 수량 0
    "2026-03-04 09:30:00,ZZTJ01,매도,60,10200,코스피",
    "2026-03-04 09:40:00,ZZTJ02,매도,5,5000,코스피",                // 매수 없는 매도
  ].join("\n")));
  await setRate(page, "0");
  await run(page);
  await expect(page.locator(".tj-excluded")).toContainText("버린 줄 2건");
  const rejects = page.locator(".tj-rejects li");
  await expect(rejects).toHaveCount(2);
  await expect(rejects.nth(0)).toContainText("3번째 줄");
  await expect(rejects.nth(0)).toContainText("체결 일시를 읽지 못했습니다");
  await expect(rejects.nth(1)).toContainText("4번째 줄");
  await expect(rejects.nth(1)).toContainText("수량이 양수가 아닙니다");
  await expect(page.locator(".tj-unmatched")).toContainText("ZZTJ02");
  await expect(page.locator(".tj-unmatched")).toContainText("매수 기록이 파일에 없습니다");
  await expect(page.locator(".tj-open")).toContainText("ZZTJ01");
  await expect(page.locator(".tj-open")).toContainText("40주");
  await expect(page.locator(".tj-open")).toContainText("+12,000원");          // 실현분(비용 전) 60주 × 200원
  // 청산된 거래가 없다 — 승률을 지어내지 않는다
  await expect(page.locator(".tj-result .tx-answer-s")).toContainText("청산된 거래 없음");
  await expect(page.locator(".tj-sum")).toHaveCount(0);
});

test("상한을 넘는 파일은 서버 사유 그대로 — 잘라서 계산하지 않는다", async ({ page }) => {
  await open(page);
  const lines = ["체결일시,종목코드,매매구분,수량,단가,시장"];
  for (let i = 0; i < 20_001; i++) lines.push(`2026-03-04 09:00:00,ZZTJ01,${i % 2 ? "매도" : "매수"},1,1000,코스피`);
  await upload(page, csv("big.csv", lines.join("\n")));
  await expect(page.locator(".tj-file-meta")).toContainText("20,001줄");
  await page.locator(".tj-run").click();
  await expect(page.locator(".tj-run-fail")).toContainText("20,001건");
  await expect(page.locator(".tj-run-fail")).toContainText("상한 20,000건");
  await expect(page.locator(".tj-result")).toHaveCount(0);
});

test("필수 열이 없으면 분석 단추가 꺼져 있고 무엇이 빠졌는지 말한다 · 열을 고르면 켜진다", async ({ page }) => {
  await open(page);
  await upload(page, csv("odd-headers.csv", ["when,what,how,n,p", "2026-03-04 09:00:00,ZZTJ01,매수,1,1000", "2026-03-04 09:10:00,ZZTJ01,매도,1,1100"].join("\n")));
  await expect(page.locator(".tj-run")).toBeDisabled();
  await expect(page.locator(".tj-map-miss")).toContainText("체결 일시");
  await expect(page.locator(".tj-map-miss")).toContainText("수량");
  await col(page, "date").selectOption({ label: "when" });
  await col(page, "symbol").selectOption({ label: "what" });
  await col(page, "side").selectOption({ label: "how" });
  await col(page, "quantity").selectOption({ label: "n" });
  await col(page, "price").selectOption({ label: "p" });
  await expect(page.locator(".tj-map-miss")).toHaveCount(0);
  await expect(page.locator(".tj-run")).toBeEnabled();
  await setRate(page, "0");
  await run(page);
  await expect(sum(page, "total", "gross")).toHaveText("+100원");
});

test("읽을 수 없는 파일은 사유를 말한다(빈 파일 · 구분 기호 없음)", async ({ page }) => {
  await open(page);
  await upload(page, csv("empty.csv", "   \n"));
  await expect(page.locator(".tj-file-fail")).toContainText("비어 있습니다");
  await upload(page, csv("prose.txt", "이것은 체결 내역이 아닙니다\n그냥 글입니다"));
  await expect(page.locator(".tj-file-fail")).toContainText("구분 기호");
  await expect(page.locator(".tj-map")).toHaveCount(0);
});

test("곡선의 읽는 줄 — 키보드로 거래를 옮기면 값이 따라온다(툴팁 없음)", async ({ page }) => {
  await open(page);
  await page.locator(".tj-sample").click();
  await setRate(page, "0.1");
  await run(page);
  const read = page.locator(".tj-curve-read");
  await expect(read).toContainText("6번째 거래");
  await page.locator(".tj-curve").focus();
  await page.keyboard.press("Home");
  await expect(read).toContainText("1번째 거래");
  await expect(read).toContainText("+15,940원");
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(read).toContainText("3번째 거래");
  await expect(read).toContainText(`${MINUS}7,055원`);
  await expect(read).toContainText("22,995원");                    // 고점 대비 하락의 최댓값이 이 거래다
  await page.keyboard.press("End");
  await expect(read).toContainText("6번째 거래");
  expect(await page.locator(".tj [title], .tj svg title").count()).toBe(0);
});

test("예시 불러오기 — 예시라는 표지가 결과에 붙는다 · 다른 파일을 고르면 결과가 비워진다", async ({ page }) => {
  await open(page);
  await page.locator(".tj-sample").click();
  await expect(page.locator(".tj-file-meta")).toContainText("예시 체결 내역");
  await setRate(page, "0.1");
  await run(page);
  await expect(page.locator(".tj-result .tx-chip", { hasText: "예시 파일" })).toBeVisible();
  await expect(sum(page, "total", "net")).toHaveText("+27,175원");
  // 열 맞추기를 바꾸면 앞의 결과는 낡은 것이다 — 남겨 두지 않는다
  await page.locator(".tj-fee-mode").getByRole("radio", { name: "모름" }).click();
  await expect(page.locator(".tj-result")).toHaveCount(0);
  await expect(page.locator(".tj-stale")).toContainText("재계산");
});

test("로그인이 끝났으면 다시 로그인하라고 말한다 · 서버 실패는 재시도", async ({ page }) => {
  await open(page);
  await page.locator(".tj-sample").click();
  let mode: "401" | "500" | "pass" = "401";
  await page.route("**/api/v1/trade-journal/analyze", (r) => mode === "pass" ? r.continue()
    : r.fulfill({ status: Number(mode), json: { detail: mode === "401" ? "인증 토큰이 만료됐습니다." : "계산 실패(시험)" } }));
  await page.locator(".tj-run").click();
  await expect(page.locator(".tj-run-fail")).toContainText("로그인");
  await expect(page.locator(".tj-run-fail a")).toHaveAttribute("href", /\/login\?next=%2Ftrade-journal/);
  mode = "500";
  await page.locator(".tj-run").click();
  await expect(page.locator(".tj-run-fail")).toContainText("계산 실패(시험)");
  mode = "pass";
  await page.locator(".tj-run-fail").getByRole("button", { name: "재시도" }).click();
  await expect(page.locator(".tj-result")).toBeVisible();
});

for (const theme of ["light", "dark"] as const) {
  test(`대비(${theme}) AA · 문체 · 좁은 화면에서 넘치지 않는다`, async ({ page }) => {
    await page.addInitScript((t) => { try { localStorage.setItem("alpha_theme", t); } catch { /* */ } }, theme);
    await open(page);
    await page.locator(".tj-sample").click();
    await setRate(page, "0.1");
    await run(page);
    await expect(page.locator("html")).toHaveClass(theme === "dark" ? /dark/ : /^(?!.*dark).*$/);
    for (const name of ["보유 시간", "진입 시간대", "요일", "일별", "종목"]) {
      await tab(page, name).click();
      const a = (await page.evaluate(contrastAudit(".tj"))) as AuditResult;
      expect(a.checked).toBeGreaterThan(80);
      expect(a.low, `${theme} · ${name}`).toEqual([]);
    }
    const v = (await page.evaluate(voiceAudit(".tj"))) as VoiceResult;
    expect(v.checked).toBeGreaterThan(80);
    expect(v.haeyo).toEqual([]);
    expect(v.dash).toEqual([]);
    expect(v.banned).toEqual([]);
    expect(v.titles).toBe(0);

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator(".tj-curve")).toBeVisible();
    const over = await page.evaluate(() => {
      const root = document.querySelector(".tj") as HTMLElement;
      const w = document.documentElement.clientWidth;
      return [...root.querySelectorAll<HTMLElement>(".tx-sec, .tx-answer, .tj-curve")].filter((el) => el.getBoundingClientRect().right > w + 1)
        .map((el) => el.className);
    });
    expect(over).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    // ★잘림★ — 화면이 옆으로 밀리지 않아도 표·막대가 제 절(카드) 밖으로 나가 잘릴 수 있다(스크린샷 검수가 찾은 것).
    // 제 상자 안에서 스크롤하는 것(`.tj-scroll` · `.tj-scroll-x` · `.tj-bucket-list`)은 넘겨도 된다 — 그 밖은 절의 안쪽 폭에 들어와야 한다.
    for (const name of ["보유 시간", "종목"]) {
      await tab(page, name).click();
      const clipped = await page.evaluate(() => {
        const out: string[] = [];
        for (const sec of document.querySelectorAll<HTMLElement>(".tj .tx-sec, .tj .tx-answer")) {
          const cs = getComputedStyle(sec);
          const right = sec.getBoundingClientRect().right - parseFloat(cs.paddingRight) + 1;
          for (const el of sec.querySelectorAll<HTMLElement>("table, ul, ol, dl, p, svg, li, td, th, span, b")) {
            if (!el.getClientRects().length || el.closest(".tj-scroll, .tj-scroll-x, .tj-bucket-list, .tx-tablist, .tx-sr")) continue;
            if (el.getBoundingClientRect().right > right) out.push(`${el.tagName}.${el.className} :: ${(el.textContent ?? "").trim().slice(0, 24)}`);
          }
        }
        return [...new Set(out)].slice(0, 12);
      });
      expect(clipped, `${theme} · 390px · ${name} 탭에서 절 밖으로 나간 것`).toEqual([]);
    }
  });
}
