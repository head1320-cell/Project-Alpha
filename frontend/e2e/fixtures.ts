/**
 * 시험의 API 클라이언트가 ★쉰 연결을 다시 쓰지 않게★ 한다 (2026-11-07 · `e2e/api-no-reuse.spec.ts`).
 * ──────────────────────────────────────────────────────────────────────────
 * Playwright 의 API 클라이언트(page.request · request 고정 · route.fetch · 시험 안에서 만든 맥락)는 프로세스 전체가 같은 keep-alive
 * 연결 묶음을 쓰고, 빈 연결에 스스로 시한을 두지 않는다. Node 는 서버의 `Keep-Alive: timeout=5` 힌트를 에이전트에 시한이 있을 때만
 * 줄이는 데 쓴다(없으면 무시). 백엔드(uvicorn)와 Next 는 5초 쉰 연결을 닫으므로, 5초쯤 쉰 연결을 다시 쓰는 순간 서버가 닫으면
 * `socket hang up` 이다 — 전체 E2E 에서 정리 DELETE 가 5,007ms 쉰 연결로 실패했다.
 *
 * 그래서 이 고정을 거친 모든 API 요청에 `connection: close` 를 붙여 연결을 한 번만 쓴다. ★재시도로 덮지 않는다★(POST 를 두 번 보내지
 * 않는다). ★브라우저 요청은 건드리지 않는다★ — 브라우저의 실제 연결 동작이 시험 대상이다.
 * 모든 스펙은 `test`·`expect` 를 여기서 가져온다(`export *` 로 나머지 이름도 그대로 — 검사는 api-no-reuse 스펙).
 */
import { test as base, type APIRequestContext, type Browser } from "@playwright/test";

export * from "@playwright/test";

type FetchOptions = { headers?: Record<string, string>; request?: { headers(): Record<string, string> } } & Record<string, unknown>;
type Inner = { _innerFetch?: (options?: FetchOptions) => Promise<unknown>; __closeAfterUse?: true };

/**
 * 모든 동사(get·post·put·patch·delete·head·fetch)와 route.fetch 가 지나는 한 곳(`_innerFetch`)에서 `connection: close` 를 더한다.
 * 비공개 메서드라 Playwright 가 바뀌어 없어지면 ★조용히 넘어가지 않고 실패한다★(그때 이 파일을 고칠 것).
 */
export function closeAfterUse(r: APIRequestContext): APIRequestContext {
  const t = r as unknown as Inner;
  if (t.__closeAfterUse) return r;
  if (typeof t._innerFetch !== "function") {
    throw new Error("Playwright API 클라이언트에 _innerFetch 가 없어요 — 버전이 바뀌었으니 e2e/fixtures.ts 의 '쉰 연결 다시 쓰지 않기'를 고쳐야 해요.");
  }
  const inner = t._innerFetch.bind(r);
  t._innerFetch = (options: FetchOptions = {}) => {
    // route.fetch 는 머리글을 주지 않고 가로챈 브라우저 요청의 머리글을 쓴다 — 그것을 그대로 두고 connection 만 더한다.
    const given = options.headers ?? options.request?.headers() ?? {};
    return inner({ ...options, headers: { ...given, connection: "close" } });
  };
  t.__closeAfterUse = true;
  return r;
}

function patchNewContext(browser: Browser): Browser {
  const b = browser as Browser & { __closeAfterUse?: true };
  if (b.__closeAfterUse) return browser;
  const orig = browser.newContext.bind(browser);
  b.newContext = async (...args: Parameters<Browser["newContext"]>) => {
    const ctx = await orig(...args);
    closeAfterUse(ctx.request);
    return ctx;
  };
  b.__closeAfterUse = true;
  return browser;
}

// 기본 맥락(page.request)도 browser.newContext 로 만들어진다(Playwright 1.61.1) — 그래서 browser 하나로 기본 맥락과 시험 안에서 만든
// 맥락을 함께 고친다. 따로 context 고정을 덧대면 지워도 통과하는 줄이 된다(변이로 확인). 바뀌면 api-no-reuse 의 page.request 시험이 깨진다.
export const test = base.extend<object, object>({
  browser: [async ({ browser }, use) => { await use(patchNewContext(browser)); }, { scope: "worker" }],
  request: async ({ request }, use) => { closeAfterUse(request); await use(request); },
});
