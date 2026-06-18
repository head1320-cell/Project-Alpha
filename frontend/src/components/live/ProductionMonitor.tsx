"use client";

import { useState, useEffect, useCallback } from "react";
import {
  GitMerge, Zap, BellRing, Activity, AlertOctagon,
  CheckCircle2, XCircle, Loader2, RefreshCw, Cpu, GitBranch,
} from "lucide-react";

import { API_BASE } from "@/lib/apiBase";

// ═══════════════════════════════════════════════════════════════════════════════
// Types
// ═══════════════════════════════════════════════════════════════════════════════

interface GatewayStats {
  queue_size: number;
  queue_max: number;
  queue_by_priority: { KILL?: number; SELL?: number; BUY?: number; QUERY?: number };
  total_enqueued: number;
  total_executed: number;
  total_failed: number;
  total_timeouts: number;
  avg_wait_ms: number;
  avg_exec_ms: number;
  p95_wait_ms: number;
  circuit_state: string;
  circuit_failures: number;
  rate_limit_per_sec: number;
  current_tokens: number;
  by_priority: { KILL: number; SELL: number; BUY: number; QUERY: number };
  last_call_at?: string;
  last_error?: string;
}

interface ReconcilerStatus {
  last_sync_id?: string;
  last_sync_at?: string;
  last_severity?: string;
  is_fresh: boolean;
  critical_drift_count: number;
  periodic_running: boolean;
}

interface NotifierStats {
  total_enqueued: number;
  total_sent: number;
  total_failed: number;
  total_dedup_skip: number;
  queue_size: number;
  worker_alive: boolean;
  slack_configured: boolean;
  discord_configured: boolean;
  by_severity: { INFO: number; WARN: number; CRITICAL: number };
  last_sent_at?: string;
}

interface ActiveOrder {
  client_order_id: string;
  ticker: string;
  side: string;
  quantity: number;
  filled_quantity?: number;
  status: string;
  execution_mode: string;
  created_at: string;
}

interface HealthSummary {
  health: string;
  critical_issues: string[];
  execution_mode: string;
  kill_switch_active: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main Component
// ═══════════════════════════════════════════════════════════════════════════════

export default function ProductionMonitor() {
  const [gateway, setGateway] = useState<GatewayStats | null>(null);
  const [reconciler, setReconciler] = useState<ReconcilerStatus | null>(null);
  const [notifier, setNotifier] = useState<NotifierStats | null>(null);
  const [activeOrders, setActiveOrders] = useState<ActiveOrder[]>([]);
  const [health, setHealth] = useState<HealthSummary | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [g, r, n, a, h] = await Promise.all([
        fetch(`${API_BASE}/api/v1/live/gateway/stats`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v1/live/reconcile/status`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v1/live/notifier/stats`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v1/live/orders/active`).then((r) => r.json()).catch(() => null),
        fetch(`${API_BASE}/api/v1/live/health`).then((r) => r.json()).catch(() => null),
      ]);
      if (g) setGateway(g);
      if (r) setReconciler(r);
      if (n) setNotifier(n);
      if (a?.orders) setActiveOrders(a.orders);
      if (h) setHealth(h);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);   // 3초 polling
    return () => clearInterval(interval);
  }, [refresh]);

  const syncNow = async () => {
    await fetch(`${API_BASE}/api/v1/live/reconcile/sync`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "manual_cockpit" }),
    });
    refresh();
  };

  const testNotify = async (severity: string) => {
    await fetch(`${API_BASE}/api/v1/live/notifier/test`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        severity, title: `Cockpit Test ${severity}`,
        message: "Production monitor manual test",
      }),
    });
    refresh();
  };

  return (
    <div className="space-y-6">
      {/* Health Banner */}
      {health && (
        <HealthBanner health={health} loading={loading} onRefresh={refresh} />
      )}

      {/* 4-pane production monitor */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <KISGatewayPanel stats={gateway} />
        <ReconcilerPanel stats={reconciler} onSync={syncNow} />
        <ActiveOrdersPanel orders={activeOrders} />
        <NotifierPanel stats={notifier} onTest={testNotify} />
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Sub-components
// ═══════════════════════════════════════════════════════════════════════════════

function HealthBanner({ health, loading, onRefresh }: {
  health: HealthSummary; loading: boolean; onRefresh: () => void;
}) {
  const healthColor =
    health.health === "HEALTHY"  ? "#DEFF9A" :
    health.health === "DEGRADED" ? "#FFC857" : "#FF6B6B";

  const HealthIcon =
    health.health === "HEALTHY"  ? CheckCircle2 :
    health.health === "DEGRADED" ? AlertOctagon : XCircle;

  return (
    <div
      className="rounded-2xl p-5 border"
      style={{
        background: `linear-gradient(135deg, ${healthColor}08, transparent)`,
        borderColor: `${healthColor}30`,
      }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div
            className="p-3 rounded-xl"
            style={{
              background: `${healthColor}15`,
              boxShadow: health.health !== "HEALTHY" ? `0 0 24px ${healthColor}40` : "none",
            }}
          >
            <HealthIcon size={24} color={healthColor} />
          </div>
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-bold tracking-tight">
                System Health
              </h2>
              <span
                className="px-2.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-widest"
                style={{
                  background: `${healthColor}15`,
                  color: healthColor,
                  border: `1px solid ${healthColor}40`,
                }}
              >
                {health.health}
              </span>
            </div>
            <div className="text-[11px] text-zinc-500 font-mono mt-1">
              Mode: <span style={{ color: healthColor }}>{health.execution_mode}</span>
              {health.kill_switch_active && (
                <span className="ml-3 text-[#FF6B6B] font-bold">⚠ KILL SWITCH ACTIVE</span>
              )}
              {health.critical_issues.length > 0 && (
                <span className="ml-3 text-[#FF6B6B]">
                  · {health.critical_issues.join(", ")}
                </span>
              )}
            </div>
          </div>
        </div>

        <button
          onClick={onRefresh}
          className="flex items-center gap-2 px-3 py-2 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-[10px] text-zinc-300"
        >
          {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          Refresh
        </button>
      </div>
    </div>
  );
}

function KISGatewayPanel({ stats }: { stats: GatewayStats | null }) {
  if (!stats) return <PanelSkeleton title="KIS Gateway" />;

  const queueFillPct = (stats.queue_size / stats.queue_max) * 100;
  const circuitColor =
    stats.circuit_state === "CLOSED" ? "#DEFF9A" :
    stats.circuit_state === "HALF_OPEN" ? "#FFC857" : "#FF6B6B";

  return (
    <Panel
      icon={Zap}
      iconColor="#DEFF9A"
      title="KIS Gateway"
      subtitle="Priority queue · rate limiter · circuit breaker"
    >
      <div className="space-y-4">
        {/* Circuit + Queue stats */}
        <div className="grid grid-cols-2 gap-3">
          <Metric
            label="Circuit"
            value={stats.circuit_state}
            color={circuitColor}
            sub={stats.circuit_failures > 0 ? `${stats.circuit_failures} fails` : "stable"}
          />
          <Metric
            label="Queue Depth"
            value={`${stats.queue_size} / ${stats.queue_max}`}
            color={queueFillPct > 70 ? "#FFC857" : "#DAFFDE"}
            sub={`${queueFillPct.toFixed(1)}% full`}
          />
        </div>

        {/* Priority queue distribution */}
        <div>
          <Label>Pending by Priority</Label>
          <div className="grid grid-cols-4 gap-1 mt-1.5">
            {[
              ["KILL", "#FF6B6B"],
              ["SELL", "#FFC857"],
              ["BUY",  "#DAFFDE"],
              ["QUERY","#7DD3FC"],
            ].map(([p, color]) => (
              <div key={p} className="rounded p-2 bg-zinc-950/50 border border-zinc-900">
                <div className="text-[8px] font-mono uppercase text-zinc-500">{p}</div>
                <div className="text-base font-bold font-mono" style={{ color }}>
                  {stats.queue_by_priority[p as keyof typeof stats.queue_by_priority] || 0}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Throughput */}
        <div className="grid grid-cols-2 gap-3 pt-3 border-t border-zinc-900">
          <Metric label="Avg Wait" value={`${stats.avg_wait_ms.toFixed(0)}ms`} color="#DAFFDE" sub={`p95: ${stats.p95_wait_ms.toFixed(0)}ms`} />
          <Metric label="Avg Exec" value={`${stats.avg_exec_ms.toFixed(0)}ms`} color="#DEFF9A" sub={`rate ${stats.rate_limit_per_sec}/s`} />
        </div>

        {/* Totals */}
        <div className="grid grid-cols-3 gap-2 text-[9px] font-mono pt-3 border-t border-zinc-900">
          <MiniStat label="Executed" value={stats.total_executed.toLocaleString()} color="#DEFF9A" />
          <MiniStat label="Failed" value={stats.total_failed.toLocaleString()} color="#FF6B6B" />
          <MiniStat label="Timeouts" value={stats.total_timeouts.toLocaleString()} color="#FFC857" />
        </div>
      </div>
    </Panel>
  );
}

function ReconcilerPanel({ stats, onSync }: {
  stats: ReconcilerStatus | null; onSync: () => void;
}) {
  if (!stats) return <PanelSkeleton title="Broker Reconciliation" />;

  const sevColor =
    stats.last_severity === "OK" || !stats.last_severity ? "#DEFF9A" :
    stats.last_severity === "WARN" ? "#FFC857" : "#FF6B6B";

  return (
    <Panel
      icon={GitMerge}
      iconColor="#7DD3FC"
      title="Broker Reconciliation"
      subtitle="KIS = source of truth · 자동 drift 감지"
      action={
        <button
          onClick={onSync}
          className="px-3 py-1 rounded bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-[10px] font-bold text-zinc-300"
        >
          Sync Now
        </button>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Metric
            label="Last Severity"
            value={stats.last_severity || "—"}
            color={sevColor}
            sub={stats.is_fresh ? "fresh" : "stale"}
          />
          <Metric
            label="Periodic"
            value={stats.periodic_running ? "RUNNING" : "STOPPED"}
            color={stats.periodic_running ? "#DEFF9A" : "#6b7280"}
            sub={`drift count: ${stats.critical_drift_count}`}
          />
        </div>

        {stats.last_sync_at && (
          <div className="pt-3 border-t border-zinc-900">
            <Label>Last Sync</Label>
            <div className="text-[10px] font-mono text-zinc-400 mt-1">
              {new Date(stats.last_sync_at).toLocaleString("ko-KR")}
            </div>
            {stats.last_sync_id && (
              <div className="text-[9px] font-mono text-zinc-600 mt-0.5">
                {stats.last_sync_id}
              </div>
            )}
          </div>
        )}

        {/* Fresh indicator */}
        <div className={`p-2 rounded text-[10px] font-mono ${
          stats.is_fresh ? "bg-[#DEFF9A]/10 text-[#DEFF9A]" : "bg-[#FFC857]/10 text-[#FFC857]"
        }`}>
          {stats.is_fresh
            ? "✓ Pre-order sync 유효 (30초 이내)"
            : "⚠ Sync 오래됨 — 다음 주문 시 자동 동기화"}
        </div>
      </div>
    </Panel>
  );
}

function ActiveOrdersPanel({ orders }: { orders: ActiveOrder[] }) {
  return (
    <Panel
      icon={Activity}
      iconColor="#FFC857"
      title="Active Orders"
      subtitle={`체결 대기 중 ${orders.length}건 · 실시간 상태 머신`}
    >
      {orders.length === 0 ? (
        <div className="rounded-lg bg-zinc-950/50 border border-dashed border-zinc-900 p-6 text-center">
          <div className="text-[10px] text-zinc-600 font-mono">활성 주문 없음</div>
        </div>
      ) : (
        <div className="space-y-1.5 max-h-[260px] overflow-y-auto">
          {orders.slice(0, 8).map((o) => {
            const remaining = (o.quantity || 0) - (o.filled_quantity || 0);
            const fillPct = ((o.filled_quantity || 0) / o.quantity) * 100;
            const stateColors: Record<string, string> = {
              PENDING:      "#FFC857",
              SUBMITTED:    "#7DD3FC",
              ACCEPTED:     "#DEFF9A",
              PARTIAL_FILL: "#DAFFDE",
            };
            return (
              <div
                key={o.client_order_id}
                className="p-2.5 rounded bg-zinc-950/50 border border-zinc-900 hover:border-zinc-800"
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2 text-[10px]">
                    <span className="font-mono text-zinc-300">{o.ticker}</span>
                    <span className={`font-bold ${o.side === "BUY" ? "text-[#DEFF9A]" : "text-[#FF6B6B]"}`}>
                      {o.side}
                    </span>
                    <span className="text-zinc-500 font-mono">{o.quantity}주</span>
                  </div>
                  <span
                    className="px-1.5 py-0.5 rounded text-[8px] font-bold uppercase"
                    style={{
                      background: `${stateColors[o.status] || "#6b7280"}15`,
                      color: stateColors[o.status] || "#a1a1aa",
                    }}
                  >
                    {o.status}
                  </span>
                </div>
                {o.status === "PARTIAL_FILL" && (
                  <div className="mt-1.5">
                    <div className="h-1 bg-zinc-800 rounded overflow-hidden">
                      <div
                        className="h-full bg-[#DAFFDE] transition-all"
                        style={{ width: `${fillPct}%` }}
                      />
                    </div>
                    <div className="text-[8px] text-zinc-500 font-mono mt-0.5">
                      체결 {o.filled_quantity}/{o.quantity} · 잔여 {remaining}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

function NotifierPanel({ stats, onTest }: {
  stats: NotifierStats | null; onTest: (sev: string) => void;
}) {
  if (!stats) return <PanelSkeleton title="Notifier" />;

  return (
    <Panel
      icon={BellRing}
      iconColor="#DEFF9A"
      title="Notification System"
      subtitle="Slack / Discord webhook · throttled · severity routing"
      action={
        <div className="flex gap-1">
          {["INFO", "WARN", "CRITICAL"].map((s) => (
            <button
              key={s}
              onClick={() => onTest(s)}
              className="px-2 py-1 rounded text-[9px] font-bold uppercase border"
              style={{
                background: s === "CRITICAL" ? "#FF6B6B15" : s === "WARN" ? "#FFC85715" : "#DEFF9A15",
                borderColor: s === "CRITICAL" ? "#FF6B6B40" : s === "WARN" ? "#FFC85740" : "#DEFF9A40",
                color: s === "CRITICAL" ? "#FF6B6B" : s === "WARN" ? "#FFC857" : "#DEFF9A",
              }}
            >
              Test {s}
            </button>
          ))}
        </div>
      }
    >
      <div className="space-y-3">
        {/* Channel status */}
        <div className="grid grid-cols-2 gap-2">
          <ChannelChip
            label="Slack"
            configured={stats.slack_configured}
          />
          <ChannelChip
            label="Discord"
            configured={stats.discord_configured}
          />
        </div>

        {/* Severity breakdown */}
        <div>
          <Label>Sent by Severity</Label>
          <div className="grid grid-cols-3 gap-2 mt-1.5">
            <MiniStat label="Info" value={stats.by_severity.INFO} color="#DEFF9A" />
            <MiniStat label="Warn" value={stats.by_severity.WARN} color="#FFC857" />
            <MiniStat label="Critical" value={stats.by_severity.CRITICAL} color="#FF6B6B" />
          </div>
        </div>

        {/* System health */}
        <div className="grid grid-cols-2 gap-3 pt-3 border-t border-zinc-900">
          <Metric
            label="Worker"
            value={stats.worker_alive ? "RUNNING" : "DEAD"}
            color={stats.worker_alive ? "#DEFF9A" : "#FF6B6B"}
            sub={`queue: ${stats.queue_size}`}
          />
          <Metric
            label="Throughput"
            value={`${stats.total_sent.toLocaleString()}`}
            color="#DAFFDE"
            sub={`fail: ${stats.total_failed}, dedup: ${stats.total_dedup_skip}`}
          />
        </div>
      </div>
    </Panel>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Building blocks
// ═══════════════════════════════════════════════════════════════════════════════

function Panel({ icon: Icon, iconColor, title, subtitle, action, children }: any) {
  return (
    <div className="rounded-2xl bg-[#111111] border border-zinc-800 p-5 overflow-hidden">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 rounded-lg" style={{ background: `${iconColor}10` }}>
            <Icon size={14} color={iconColor} />
          </div>
          <div>
            <h3 className="text-[12px] font-bold uppercase tracking-wide">{title}</h3>
            <p className="text-[10px] text-zinc-500 font-mono mt-0.5">{subtitle}</p>
          </div>
        </div>
        {action}
      </div>
      {children}
    </div>
  );
}

function PanelSkeleton({ title }: { title: string }) {
  return (
    <div className="rounded-2xl bg-[#111111] border border-zinc-800 p-5">
      <div className="text-[12px] font-bold uppercase mb-3 text-zinc-500">{title}</div>
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-8 bg-zinc-900 rounded animate-pulse" />
        ))}
      </div>
    </div>
  );
}

function Label({ children }: any) {
  return (
    <div className="text-[9px] font-bold uppercase tracking-[0.15em] text-zinc-500">
      {children}
    </div>
  );
}

function Metric({ label, value, color, sub }: any) {
  return (
    <div>
      <Label>{label}</Label>
      <div className="text-base font-bold font-mono mt-1" style={{ color }}>
        {value}
      </div>
      {sub && <div className="text-[9px] text-zinc-600 font-mono mt-0.5">{sub}</div>}
    </div>
  );
}

function MiniStat({ label, value, color }: any) {
  return (
    <div className="text-center p-1.5 rounded bg-zinc-950/50 border border-zinc-900">
      <div className="text-[8px] uppercase text-zinc-600">{label}</div>
      <div className="text-[12px] font-bold font-mono" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function ChannelChip({ label, configured }: { label: string; configured: boolean }) {
  return (
    <div
      className="flex items-center justify-between p-2 rounded border"
      style={{
        borderColor: configured ? "#DEFF9A30" : "#27272a",
        background: configured ? "#DEFF9A05" : "transparent",
      }}
    >
      <span className="text-[10px] font-bold text-zinc-300">{label}</span>
      <span
        className="text-[8px] font-mono uppercase"
        style={{ color: configured ? "#DEFF9A" : "#6b7280" }}
      >
        {configured ? "✓ configured" : "○ off"}
      </span>
    </div>
  );
}
