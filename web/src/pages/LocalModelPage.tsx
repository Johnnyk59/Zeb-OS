/**
 * LocalModelPage — live status for the always-on local backbone model.
 *
 * ZebOS runs a local GGUF model 24/7 in the background: it powers the brain
 * visualization and autonomous thinking while a provider model handles
 * user-facing chat. This page shows the model's identity, health, and live
 * resource usage (CPU / RAM / bandwidth), plus a Restart button to recover
 * a wedged model without touching the rest of the server.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  BrainCircuit,
  Cpu,
  Database,
  FileText,
  Gauge,
  HardDrive,
  RotateCw,
  Sparkles,
  Wifi,
  Zap,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { Markdown } from "@/components/Markdown";
import { api } from "@/lib/api";
import type {
  EvolutionStatus,
  LocalModelStatus,
  ModelReview,
} from "@/lib/api";

const POLL_MS = 2500;

function fmtAgo(ts?: number | null): string {
  if (!ts) return "never";
  const secs = Date.now() / 1000 - ts;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${(secs / 3600).toFixed(1)}h ago`;
  return `${(secs / 86400).toFixed(1)}d ago`;
}

function fmtBytes(n?: number): string {
  if (!n || n <= 0) return "—";
  if (n >= 1 << 30) return `${(n / (1 << 30)).toFixed(2)} GB`;
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)} MB`;
  return `${Math.round(n / 1024)} KB`;
}

function fmtCtx(n: number): string {
  return n >= 1024 ? `${Math.round(n / 1024)}K` : String(n || "—");
}

export default function LocalModelPage() {
  const [status, setStatus] = useState<LocalModelStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [restarting, setRestarting] = useState(false);
  const [evolution, setEvolution] = useState<EvolutionStatus | null>(null);
  const [reviews, setReviews] = useState<ModelReview[]>([]);
  const [activeWindow, setActiveWindow] = useState<"6h" | "12h" | "24h">("6h");
  const [genWindow, setGenWindow] = useState<string | null>(null);
  const { toast, showToast } = useToast();
  // Previous net counters → live bandwidth (bytes/s) between polls.
  const prevNetRef = useRef<{ ts: number; sent: number; recv: number } | null>(null);
  const [bandwidth, setBandwidth] = useState<{ up: number; down: number }>({
    up: 0,
    down: 0,
  });

  const load = useCallback(async () => {
    try {
      const s = await api.getLocalModel();
      setStatus(s);
      const now = Date.now();
      const sent = s.net?.bytes_sent ?? 0;
      const recv = s.net?.bytes_recv ?? 0;
      const prev = prevNetRef.current;
      if (prev && now > prev.ts) {
        const dt = (now - prev.ts) / 1000;
        setBandwidth({
          up: Math.max(0, (sent - prev.sent) / dt),
          down: Math.max(0, (recv - prev.recv) / dt),
        });
      }
      prevNetRef.current = { ts: now, sent, recv };
    } catch {
      /* poll again */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => {
      if (!document.hidden) void load();
    }, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  // Evolution manifest + persisted reviews poll on a slower cadence.
  const loadEvolution = useCallback(async () => {
    try {
      setEvolution(await api.getEvolution());
    } catch {
      /* keep last */
    }
  }, []);
  const loadReviews = useCallback(async () => {
    try {
      const res = await api.getModelReviews();
      setReviews(res.reviews ?? []);
    } catch {
      /* keep last */
    }
  }, []);

  useEffect(() => {
    void loadEvolution();
    void loadReviews();
    const id = setInterval(() => {
      if (document.hidden) return;
      void loadEvolution();
      void loadReviews();
    }, 6000);
    return () => clearInterval(id);
  }, [loadEvolution, loadReviews]);

  const handleGenerateReview = async (window: "6h" | "12h" | "24h") => {
    setActiveWindow(window);
    setGenWindow(window);
    try {
      const r = await api.generateModelReview(window);
      if (r.error) showToast(r.error, "error");
      else showToast(`Generating ${window} review…`, "success");
      // The model writes in the background; poll picks up the result.
      void loadReviews();
    } catch (e) {
      showToast(`Review failed: ${e}`, "error");
    } finally {
      // Clear the local spinner shortly; server ``generating`` flag takes over.
      setTimeout(() => setGenWindow(null), 1500);
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      const res = await api.restartLocalModel();
      if (res.ok) {
        showToast("Local model restarting — reloads on next use", "success");
      } else {
        showToast(res.error || "Restart failed", "error");
      }
      void load();
    } catch (e) {
      showToast(`Restart failed: ${e}`, "error");
    } finally {
      setRestarting(false);
    }
  };

  if (loading && !status) {
    return (
      <div className="flex items-center gap-2 py-10 text-text-secondary">
        <Spinner /> Loading local model status…
      </div>
    );
  }

  const s = status;
  const activeReview = reviews.find((r) => r.window === activeWindow);
  const stateLabel = s?.loaded
    ? "Active"
    : s?.download?.active
      ? "Downloading"
      : s?.ready
        ? "Standby"
        : "Inactive";
  const stateTone = s?.loaded
    ? "bg-success/15 text-success"
    : s?.download?.active
      ? "bg-warning/15 text-warning"
      : s?.ready
        ? "bg-midground/10 text-text-secondary"
        : "bg-destructive/15 text-destructive";

  return (
    <div className="flex flex-col gap-4">
      {toast && <Toast toast={toast} />}

      {/* Identity + restart */}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex items-center gap-3">
              <span className="font-mono text-lg text-midground">
                {s?.name || "Local model"}
              </span>
              <Badge className={stateTone}>{stateLabel}</Badge>
            </div>
            <span className="text-sm text-text-secondary">
              Always-on backbone — powers the brain and autonomous thinking;
              provider models handle chat.
            </span>
            {s?.path ? (
              <span className="truncate font-mono text-xs text-text-tertiary">
                {s.path}
              </span>
            ) : null}
          </div>
          <Button
            onClick={handleRestart}
            disabled={restarting}
            prefix={restarting ? <Spinner /> : <RotateCw className="h-4 w-4" />}
            className="uppercase"
          >
            Restart local model
          </Button>
        </CardContent>
      </Card>

      {/* Live metrics */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          icon={<Cpu className="h-4 w-4" />}
          label="CPU"
          value={`${(s?.cpu_percent ?? 0).toFixed(0)}%`}
          sub={`process ${(s?.process_cpu_percent ?? 0).toFixed(0)}%`}
        />
        <MetricCard
          icon={<Database className="h-4 w-4" />}
          label="RAM"
          value={
            s?.ram?.process_mb != null
              ? `${(s.ram.process_mb / 1024).toFixed(1)} GB`
              : "—"
          }
          sub={
            s?.ram?.system_used_mb != null && s?.ram?.system_total_mb != null
              ? `system ${(s.ram.system_used_mb / 1024).toFixed(1)} / ${(s.ram.system_total_mb / 1024).toFixed(0)} GB (${s.ram.percent ?? 0}%)`
              : ""
          }
        />
        <MetricCard
          icon={<Wifi className="h-4 w-4" />}
          label="Bandwidth"
          value={`↓ ${fmtBytes(bandwidth.down)}/s`}
          sub={`↑ ${fmtBytes(bandwidth.up)}/s`}
        />
        <MetricCard
          icon={<HardDrive className="h-4 w-4" />}
          label="Weights"
          value={fmtBytes(s?.size_bytes)}
          sub={`context ${fmtCtx(s?.ctx ?? 0)}`}
        />
      </div>

      {/* Self-evolution engine — Zeb building its own faster brain */}
      <Card>
        <CardContent className="flex flex-col gap-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm uppercase tracking-[0.1em] text-text-secondary">
              <BrainCircuit className="h-4 w-4" /> Self-evolution engine
            </div>
            <Badge
              className={
                evolution?.enabled
                  ? "bg-[#a884ff]/15 text-[#a884ff]"
                  : "bg-midground/10 text-text-secondary"
              }
            >
              {evolution?.enabled ? "Evolving 24/7" : "Idle"}
            </Badge>
          </div>
          <span className="text-xs text-text-tertiary">
            Runs continuously: harvests training data from every chat, caches
            repeat reasoning for faster thinking, measures latency, and fine-tunes
            new generations when a trainer is configured.
          </span>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <EvoStat
              icon={<Sparkles className="h-4 w-4" />}
              label="Generation"
              value={`#${evolution?.generation ?? 0}`}
              sub={evolution?.training_state ?? "collecting"}
            />
            <EvoStat
              icon={<Database className="h-4 w-4" />}
              label="Training data"
              value={`${(evolution?.dataset_examples ?? 0).toLocaleString()}`}
              sub="examples harvested"
            />
            <EvoStat
              icon={<Zap className="h-4 w-4" />}
              label="Effective speed-up"
              value={
                evolution?.speedup_pct != null
                  ? `${evolution.speedup_pct}%`
                  : "—"
              }
              sub={`cache ${Math.round((evolution?.cache_hit_rate ?? 0) * 100)}% hit`}
            />
            <EvoStat
              icon={<Gauge className="h-4 w-4" />}
              label="Latency"
              value={
                evolution?.latency_current_ms != null
                  ? `${Math.round(evolution.latency_current_ms)}ms`
                  : "—"
              }
              sub={
                evolution?.latency_baseline_ms != null
                  ? `baseline ${Math.round(evolution.latency_baseline_ms)}ms`
                  : "measuring…"
              }
            />
          </div>

          {evolution?.notes ? (
            <div className="rounded-[var(--radius)] border border-current/10 bg-midground/[0.04] px-3 py-2 text-xs text-text-secondary">
              {evolution.notes}
              {!evolution.trainer_available ? (
                <span className="mt-1 block text-text-tertiary">
                  No trainer backend configured — set{" "}
                  <code className="font-mono">
                    autonomy.self_evolution.trainer_cmd
                  </code>{" "}
                  to fine-tune custom generations from the collected data.
                </span>
              ) : null}
            </div>
          ) : null}

          <div className="flex items-center justify-between text-xs text-text-tertiary">
            <span>Last cycle {fmtAgo(evolution?.last_tick)}</span>
            <span>
              {(evolution?.cache_hits ?? 0).toLocaleString()} cache hits ·{" "}
              {(evolution?.cache_entries ?? 0).toLocaleString()} cached
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Self-reviews — Zeb summarizes its own work */}
      <Card>
        <CardContent className="flex flex-col gap-4 p-5">
          <div className="flex items-center gap-2 text-sm uppercase tracking-[0.1em] text-text-secondary">
            <FileText className="h-4 w-4" /> Self-reviews
          </div>
          <span className="-mt-2 text-xs text-text-tertiary">
            Zeb writes and keeps these current automatically. Click to
            regenerate one now.
          </span>
          <div className="flex flex-wrap gap-2">
            {(["6h", "12h", "24h"] as const).map((w) => {
              const r = reviews.find((x) => x.window === w);
              const busy = genWindow === w || r?.generating;
              return (
                <Button
                  key={w}
                  ghost={activeWindow !== w}
                  size="sm"
                  onClick={() => {
                    setActiveWindow(w);
                    void handleGenerateReview(w);
                  }}
                  prefix={busy ? <Spinner /> : <RotateCw className="h-3.5 w-3.5" />}
                  className="uppercase"
                >
                  {w === "6h"
                    ? "Six-hour"
                    : w === "12h"
                      ? "Twelve-hour"
                      : "Twenty-four-hour"}{" "}
                  review
                </Button>
              );
            })}
          </div>

          {/* Window tabs */}
          <div className="flex gap-1 border-b border-current/10">
            {(["6h", "12h", "24h"] as const).map((w) => (
              <button
                key={w}
                onClick={() => setActiveWindow(w)}
                className={
                  "px-3 py-1.5 text-xs uppercase tracking-[0.1em] transition-colors " +
                  (activeWindow === w
                    ? "border-b-2 border-midground text-midground"
                    : "text-text-tertiary hover:text-text-secondary")
                }
              >
                {w}
              </button>
            ))}
          </div>

          <div className="min-h-24 rounded-[var(--radius)] border border-current/10 bg-midground/[0.03] p-4">
            {activeReview?.generating ? (
              <div className="flex items-center gap-2 text-sm text-text-secondary">
                <Spinner /> Zeb is writing the {activeWindow} review…
              </div>
            ) : activeReview?.markdown ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-xs text-text-tertiary">
                  {activeReview.stale ? (
                    <Badge className="bg-warning/15 text-warning">Stale</Badge>
                  ) : (
                    <Badge className="bg-success/15 text-success">Current</Badge>
                  )}
                  <span>generated {fmtAgo(activeReview.generated_at)}</span>
                </div>
                <Markdown content={activeReview.markdown} />
              </div>
            ) : (
              <span className="text-sm text-text-tertiary">
                No {activeWindow} review yet — click the button above to have Zeb
                write one.
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Download progress, when active */}
      {s?.download?.active ? (
        <Card>
          <CardContent className="flex flex-col gap-2 p-5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">
                Downloading {s.download.file || "weights"}…
              </span>
              <span className="font-mono text-midground">
                {(s.download.percent ?? 0).toFixed(0)}%
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-midground/10">
              <div
                className="h-full rounded-full bg-midground/70 transition-[width] duration-500"
                style={{ width: `${Math.min(100, s.download.percent ?? 0)}%` }}
              />
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Activity feed */}
      <Card>
        <CardContent className="flex flex-col gap-1 p-5">
          <div className="mb-2 flex items-center gap-2 text-sm uppercase tracking-[0.1em] text-text-secondary">
            <Activity className="h-4 w-4" /> Activity
          </div>
          {(s?.events?.length ?? 0) === 0 ? (
            <span className="text-sm text-text-tertiary">
              No recent activity.
            </span>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {(s?.events ?? [])
                .slice(-30)
                .reverse()
                .map((e, i) => (
                  <li
                    key={`${e.ts ?? i}-${i}`}
                    className="flex items-baseline gap-3 font-mono text-xs"
                  >
                    <span className="shrink-0 text-text-tertiary">
                      {e.ts
                        ? new Date(e.ts * 1000).toLocaleTimeString()
                        : "—"}
                    </span>
                    <span
                      className={
                        e.level === "error"
                          ? "text-destructive"
                          : e.level === "warn"
                            ? "text-warning"
                            : "text-text-secondary"
                      }
                    >
                      [{e.event}] {e.detail}
                    </span>
                  </li>
                ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 p-4">
        <div className="flex items-center gap-2 text-xs uppercase tracking-[0.1em] text-text-tertiary">
          {icon} {label}
        </div>
        <span className="font-mono text-xl text-midground">{value}</span>
        {sub ? (
          <span className="truncate text-xs text-text-tertiary">{sub}</span>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** Compact stat tile for the self-evolution grid (borderless, denser). */
function EvoStat({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-[var(--radius)] border border-current/10 bg-midground/[0.04] p-3">
      <div className="flex items-center gap-1.5 text-[0.65rem] uppercase tracking-[0.1em] text-text-tertiary">
        {icon} {label}
      </div>
      <span className="font-mono text-lg text-midground">{value}</span>
      {sub ? (
        <span className="truncate text-[0.65rem] text-text-tertiary">{sub}</span>
      ) : null}
    </div>
  );
}
