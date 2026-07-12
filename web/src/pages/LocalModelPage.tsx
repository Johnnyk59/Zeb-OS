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
import { Activity, Cpu, Database, HardDrive, RotateCw, Wifi } from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { api } from "@/lib/api";
import type { LocalModelStatus } from "@/lib/api";

const POLL_MS = 2500;

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
