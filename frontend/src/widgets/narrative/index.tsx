"use client";

/**
 * Narrative Components — Phase 3 AI Intelligence
 * ==========================================================================
 * 통합 컴포넌트 모음 (단일 파일로 응집):
 *   · NarrativeDisplay     — Markdown 렌더링 + 메타데이터 + PDF/복사 버튼
 *   · NarrativeGenerator   — 도메인 선택 + 인풋 + 생성 + 스트리밍
 *   · StreamingNarrative   — SSE 실시간 청크 렌더
 *   · UsageMonitor         — 토큰 + 비용 추적 패널
 *   · CompactNarrative     — 다른 페이지에 임베드용 (작은 사이즈)
 */

import { useEffect, useState, useRef } from "react";
import {
  Sparkles, Brain, Loader2, Copy, Download, Check, X,
  TrendingUp, DollarSign, Clock, Zap, Database, AlertCircle,
} from "lucide-react";
import {
  narrativeApi, DOMAIN_LABELS, DOMAIN_COLORS, DOMAIN_DESCRIPTIONS,
  type NarrativeResponse, type NarrativeDomain, type UsageStats,
} from "@/entities/narrative/api";

// ═══════════════════════════════════════════════════════════════════════════════
// Lightweight Markdown Renderer
// ═══════════════════════════════════════════════════════════════════════════════

function renderMarkdown(text: string): string {
  if (!text) return "";
  // Heading
  let html = text
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Bold + Italic + Code
  html = html
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>');

  // Tables
  html = html.replace(
    /^(\|.+\|)\n(\|[-:\s|]+\|)\n((?:\|.+\|\n?)+)/gm,
    (_match, header: string, _sep: string, rows: string) => {
      const ths = header.split("|").slice(1, -1).map(c => `<th>${c.trim()}</th>`).join("");
      const trs = rows.trim().split("\n").map(row => {
        const tds = row.split("|").slice(1, -1).map(c => `<td>${c.trim()}</td>`).join("");
        return `<tr>${tds}</tr>`;
      }).join("");
      return `<table class="md-table"><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
    }
  );

  // Lists
  html = html
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.+<\/li>\n?)+/g, m => `<ul>${m}</ul>`);

  // Blockquote
  html = html.replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>');

  // Paragraphs (any line not already wrapped)
  html = html.split(/\n{2,}/).map(block => {
    const trimmed = block.trim();
    if (!trimmed) return "";
    if (/^<(h\d|ul|table|blockquote)/.test(trimmed)) return trimmed;
    return `<p>${trimmed.replace(/\n/g, "<br/>")}</p>`;
  }).join("\n");

  return html;
}

// ═══════════════════════════════════════════════════════════════════════════════
// NarrativeDisplay — 결과 + 메타데이터 표시
// ═══════════════════════════════════════════════════════════════════════════════

export function NarrativeDisplay({
  response, domain, onClose,
}: {
  response: NarrativeResponse;
  domain?: NarrativeDomain;
  onClose?: () => void;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(response.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([response.content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `narrative-${domain || "report"}-${Date.now()}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const html = renderMarkdown(response.content);
  const color = domain ? DOMAIN_COLORS[domain] : "#1200ff";

  return (
    <div className="card-md">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-default"
            style={{ borderTop: `3px solid ${color}` }}>
        <div className="flex items-center gap-2">
          <Brain size={16} style={{ color }} />
          <span className="text-sm font-bold text-primary">
            {domain ? DOMAIN_LABELS[domain] : "AI 분석"}
          </span>
          {response.cached && (
            <span className="text-[9px] px-1.5 py-0.5 bg-light rounded uppercase tracking-wider text-secondary font-mono">
              cached
            </span>
          )}
          {response.error && (
            <span className="text-[9px] px-1.5 py-0.5 rounded uppercase tracking-wider font-mono"
                   style={{ background: "#fef2f2", color: "#dc2626" }}>
              mock
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={handleCopy} className="p-1.5 hover:bg-light rounded transition" title="복사">
            {copied ? <Check size={12} style={{ color: "#16a34a" }} /> : <Copy size={12} />}
          </button>
          <button onClick={handleDownload} className="p-1.5 hover:bg-light rounded transition" title="다운로드">
            <Download size={12} />
          </button>
          {onClose && (
            <button onClick={onClose} className="p-1.5 hover:bg-light rounded transition" title="닫기">
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div
        className="narrative-body p-4"
        dangerouslySetInnerHTML={{ __html: html }}
      />

      {/* Meta footer */}
      <div className="px-3 py-2 border-t border-default text-[10px] font-mono text-secondary flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span><Database size={9} className="inline mr-1" /> {response.model}</span>
          <span><Zap size={9} className="inline mr-1" /> {response.total_tokens} tokens</span>
          <span><Clock size={9} className="inline mr-1" /> {response.elapsed_seconds}s</span>
          {response.cost_krw > 0 && (
            <span><DollarSign size={9} className="inline mr-1" /> {response.cost_krw.toFixed(1)}원</span>
          )}
        </div>
        <span>{new Date(response.timestamp).toLocaleString("ko-KR")}</span>
      </div>

      <style jsx>{`
        :global(.narrative-body) {
          font-size: 13px;
          line-height: 1.7;
          color: #212529;
        }
        :global(.narrative-body h1) {
          font-size: 1.5rem; font-weight: 700; margin: 1.5rem 0 0.75rem;
          padding-bottom: 0.5rem; border-bottom: 1px solid #dee2e6;
        }
        :global(.narrative-body h2) {
          font-size: 1.15rem; font-weight: 700; margin: 1.2rem 0 0.5rem;
          color: ${color};
        }
        :global(.narrative-body h3) {
          font-size: 1rem; font-weight: 600; margin: 0.9rem 0 0.4rem;
        }
        :global(.narrative-body p) {
          margin: 0 0 0.75rem;
        }
        :global(.narrative-body ul) {
          margin: 0.5rem 0; padding-left: 1.5rem;
        }
        :global(.narrative-body li) {
          margin: 0.25rem 0;
        }
        :global(.narrative-body strong) {
          font-weight: 600; color: #111;
        }
        :global(.narrative-body code) {
          font-family: 'Roboto Mono', monospace;
          background: #f3f4f7; padding: 0.1em 0.3em;
          border-radius: 3px; font-size: 0.9em;
        }
        :global(.narrative-body blockquote) {
          border-left: 3px solid ${color}; opacity: 0.85;
          padding: 0.5em 1em; margin: 0.75em 0;
          background: #f8f9fa; font-size: 0.95em;
        }
        :global(.narrative-body .md-table) {
          width: 100%; border-collapse: collapse; margin: 0.75em 0;
          font-size: 0.9em;
        }
        :global(.narrative-body .md-table th),
        :global(.narrative-body .md-table td) {
          border: 1px solid #dee2e6; padding: 0.4em 0.6em; text-align: left;
        }
        :global(.narrative-body .md-table th) {
          background: #f8f9fa; font-weight: 600;
        }
      `}</style>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// StreamingNarrative — SSE 청크 실시간 렌더
// ═══════════════════════════════════════════════════════════════════════════════

export function StreamingNarrative({
  domain, inputs, onComplete,
}: {
  domain: NarrativeDomain;
  inputs: Record<string, unknown>;
  onComplete?: (content: string) => void;
}) {
  const [content, setContent] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStreaming(true);
    setContent("");
    setError(null);

    let acc = "";
    narrativeApi
      .stream(domain, inputs, (chunk) => {
        if (cancelled) return;
        acc += chunk;
        setContent(acc);
      })
      .then(() => {
        if (!cancelled) {
          setStreaming(false);
          onComplete?.(acc);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) {
          setError(e.message);
          setStreaming(false);
        }
      });

    return () => { cancelled = true; };
  }, [domain, JSON.stringify(inputs)]);

  const html = renderMarkdown(content);
  const color = DOMAIN_COLORS[domain];

  return (
    <div className="card-md">
      <div className="flex items-center gap-2 p-3 border-b border-default"
            style={{ borderTop: `3px solid ${color}` }}>
        <Brain size={16} style={{ color }} />
        <span className="text-sm font-bold text-primary">{DOMAIN_LABELS[domain]}</span>
        {streaming && (
          <span className="ml-auto flex items-center gap-1 text-[10px] text-secondary">
            <Loader2 size={10} className="animate-spin" />
            스트리밍 중...
          </span>
        )}
      </div>

      {error && (
        <div className="p-4 text-xs" style={{ color: "#dc2626" }}>
          <AlertCircle size={14} className="inline mr-1" />
          {error}
        </div>
      )}

      <div className="narrative-body p-4" dangerouslySetInnerHTML={{ __html: html }}>
      </div>

      {streaming && content && (
        <div className="px-4 pb-3 text-[10px] text-secondary">
          <span className="inline-block w-2 h-3 bg-current animate-pulse" />
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// CompactNarrative — 다른 페이지에 임베드용 ("AI 분석" 버튼)
// ═══════════════════════════════════════════════════════════════════════════════

export function CompactNarrativeButton({
  domain, inputs, label, className,
}: {
  domain: NarrativeDomain;
  inputs: () => Record<string, unknown>;  // lazy
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [resp, setResp] = useState<NarrativeResponse | null>(null);

  const fire = async () => {
    if (loading) return;
    setOpen(true);
    setLoading(true);
    try {
      const apiFn = (narrativeApi as unknown as Record<string,
        (...args: unknown[]) => Promise<NarrativeResponse>>)[domain];
      const ipt = inputs();
      let r: NarrativeResponse;
      if (domain === "stock") {
        r = await narrativeApi.stock(
          ipt.stock_item as Record<string, unknown>,
          (ipt.valuation_detail as Record<string, unknown>) || {},
        );
      } else if (domain === "portfolio") {
        r = await narrativeApi.portfolio(
          ipt.backtest_result as Record<string, unknown>,
          (ipt.attribution as Record<string, unknown>) || {},
        );
      } else if (domain === "macro") {
        r = await narrativeApi.macro(ipt.regime_state as Record<string, unknown>);
      } else if (domain === "operations") {
        r = await narrativeApi.operations(
          (ipt.events as Array<Record<string, unknown>>) || [],
          (ipt.audit_summary as Record<string, unknown>) || {},
        );
      } else if (domain === "counterfactual") {
        r = await narrativeApi.counterfactual(
          ipt.actual as Record<string, unknown>,
          (ipt.scenarios as Array<Record<string, unknown>>) || [],
        );
      } else {
        r = await narrativeApi.daily(ipt.activities as Record<string, unknown>);
      }
      setResp(r);
    } catch (e) {
      setResp({
        content: `⚠ 오류: ${(e as Error).message}`,
        model: "error", input_tokens: 0, output_tokens: 0, total_tokens: 0,
        cost_usd: 0, cost_krw: 0, elapsed_seconds: 0, cached: false,
        error: (e as Error).message, timestamp: new Date().toISOString(),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={fire}
        disabled={loading}
        className={className ?? "btn-primary text-xs py-1.5 px-3 flex items-center gap-1.5"}
        style={{ background: DOMAIN_COLORS[domain] }}
      >
        {loading ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
        {label ?? "AI 분석"}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.5)" }}
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            {loading && (
              <div className="p-12 text-center">
                <Loader2 size={32} className="animate-spin mx-auto mb-3 text-secondary" />
                <div className="text-sm text-secondary">Claude가 분석 중...</div>
                <div className="text-[10px] text-secondary mt-1 font-mono">
                  평균 3-8초 소요
                </div>
              </div>
            )}
            {resp && !loading && (
              <NarrativeDisplay
                response={resp}
                domain={domain}
                onClose={() => { setOpen(false); setResp(null); }}
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// UsageMonitor — 토큰 + 비용 추적
// ═══════════════════════════════════════════════════════════════════════════════

export function UsageMonitor() {
  const [stats, setStats] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const s = await narrativeApi.usage();
        setStats(s);
      } catch (e) {
        // ignore
      } finally {
        setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  if (loading || !stats) {
    return (
      <div className="card-md p-3">
        <Loader2 size={14} className="animate-spin text-secondary" />
      </div>
    );
  }

  return (
    <div className="card-md p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-bold text-primary">Claude API 사용 통계</h3>
          <p className="text-[10px] text-secondary mt-0.5 font-mono">
            {stats.configured ? "✓ API 연결됨" : "⚠ Mock 모드 (API key 미설정)"}
            {" · "}모델: {stats.model}
          </p>
        </div>
        <button
          onClick={async () => {
            await narrativeApi.cacheClear();
            const s = await narrativeApi.usage();
            setStats(s);
          }}
          className="text-[10px] px-2 py-1 hover:bg-light rounded text-secondary"
        >
          캐시 비우기
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="총 호출" value={stats.total_calls.toLocaleString()} color="#0891b2" />
        <Stat label="캐시 히트" value={stats.total_cached.toLocaleString()} color="#16a34a" />
        <Stat
          label="총 토큰"
          value={`${(stats.total_input_tokens + stats.total_output_tokens).toLocaleString()}`}
          color="#8b5cf6"
        />
        <Stat
          label="총 비용 (원)"
          value={`${stats.total_cost_krw.toFixed(0)}`}
          color="#dc2626"
        />
      </div>

      {stats.last_call_at && (
        <div className="mt-3 pt-3 border-t border-default text-[10px] text-secondary">
          마지막 호출: {new Date(stats.last_call_at).toLocaleString("ko-KR")}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="rounded border border-default p-2.5" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="text-[10px] text-secondary uppercase tracking-wider">{label}</div>
      <div className="text-xl font-bold font-mono mt-0.5" style={{ color }}>{value}</div>
    </div>
  );
}
