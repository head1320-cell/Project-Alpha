import type { Page } from "@playwright/test";

// External hosts blocked by the sandbox/CSP (fonts, analytics) are not app failures.
const IGNORE_URL = /fonts\.googleapis\.com|fonts\.gstatic\.com|google-analytics|gtag/;
const IGNORE_CONSOLE = /ERR_CONNECTION_RESET|Failed to load resource.*font|net::ERR_/;

export interface ErrorSink {
  pageErrors: string[];
  consoleErrors: string[];
  api404: string[];
  apiOther4xx5xx: string[];
}

/** Attach listeners that record page errors, console errors, and any /api/backend 4xx/5xx. */
export function trackErrors(page: Page): ErrorSink {
  const sink: ErrorSink = { pageErrors: [], consoleErrors: [], api404: [], apiOther4xx5xx: [] };
  page.on("pageerror", (e) => sink.pageErrors.push(e.stack || e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !IGNORE_CONSOLE.test(m.text())) sink.consoleErrors.push(m.text());
  });
  page.on("response", (r) => {
    const u = r.url();
    if (!u.includes("/api/backend/")) return;
    const tag = `${r.request().method()} ${u.split("/api/backend")[1]}`;
    if (r.status() === 404) sink.api404.push(tag);
    else if (r.status() >= 400) sink.apiOther4xx5xx.push(`[${r.status()}] ${tag}`);
  });
  page.on("requestfailed", (r) => {
    const u = r.url();
    if (u.includes("/api/backend/") && !IGNORE_URL.test(u))
      sink.apiOther4xx5xx.push(`FAILED ${r.method()} ${u.split("/api/backend")[1]} :: ${r.failure()?.errorText}`);
  });
  return sink;
}

export const uniq = (a: string[]) => [...new Set(a)];
