/**
 * DiagnosePage — offline health check + self-repair.
 *
 * Runs the same pure-Python checks the background monitor uses (disk,
 * sqlite, config YAML, local-model liveness). Several checks self-repair
 * as they run — unloading a wedged model, repairing a malformed state.db —
 * so "Run auto-heal" is literally "run the checks and let them fix what
 * they safely can". Works with no AI provider and no network.
 */
import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  HeartPulse,
  Stethoscope,
  Wrench,
  XCircle,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { api } from "@/lib/api";
import type { DiagnoseResponse } from "@/lib/api";

export default function DiagnosePage() {
  const [report, setReport] = useState<DiagnoseResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [healing, setHealing] = useState(false);
  const { toast, showToast } = useToast();

  const run = useCallback(
    async (repair: boolean) => {
      repair ? setHealing(true) : setRunning(true);
      try {
        const res = repair
          ? await api.runDiagnoseRepair()
          : await api.getDiagnose();
        setReport(res);
        if (repair) {
          const fixed = res.summary?.repaired ?? 0;
          showToast(
            fixed > 0
              ? `Auto-heal repaired ${fixed} component${fixed === 1 ? "" : "s"}`
              : "All checks ran — nothing needed repair",
            "success",
          );
        }
      } catch (e) {
        showToast(`Diagnostics failed: ${e}`, "error");
      } finally {
        repair ? setHealing(false) : setRunning(false);
      }
    },
    [showToast],
  );

  useEffect(() => {
    void run(false);
  }, [run]);

  const overall = report?.overall ?? "unknown";
  const overallTone =
    overall === "ok"
      ? "bg-success/15 text-success"
      : overall === "degraded"
        ? "bg-warning/15 text-warning"
        : overall === "critical"
          ? "bg-destructive/15 text-destructive"
          : "bg-midground/10 text-text-secondary";

  return (
    <div className="flex flex-col gap-4">
      {toast && <Toast toast={toast} />}

      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div className="flex items-center gap-3">
            <HeartPulse className="h-6 w-6 text-midground" />
            <div className="flex flex-col">
              <div className="flex items-center gap-3">
                <span className="text-lg text-midground">System health</span>
                <Badge className={overallTone}>{overall.toUpperCase()}</Badge>
              </div>
              <span className="text-sm text-text-secondary">
                Offline checks — no AI provider or network required.
                {report?.summary
                  ? ` ${report.summary.ok ?? 0} ok · ${report.summary.degraded ?? 0} degraded · ${report.summary.critical ?? 0} critical`
                  : ""}
              </span>
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              onClick={() => void run(false)}
              disabled={running || healing}
              prefix={running ? <Spinner /> : <Stethoscope className="h-4 w-4" />}
              className="uppercase"
              ghost
            >
              Run diagnostics
            </Button>
            <Button
              onClick={() => void run(true)}
              disabled={running || healing}
              prefix={healing ? <Spinner /> : <Wrench className="h-4 w-4" />}
              className="uppercase"
            >
              Run auto-heal
            </Button>
          </div>
        </CardContent>
      </Card>

      {report?.error ? (
        <Card>
          <CardContent className="p-5 text-sm text-destructive">
            {report.error}
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-2">
        {(report?.checks ?? []).map((c) => (
          <Card key={c.component}>
            <CardContent className="flex items-start gap-3 p-4">
              {c.status === "ok" ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
              ) : c.status === "degraded" ? (
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              )}
              <div className="flex min-w-0 flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-midground">
                    {c.component}
                  </span>
                  {c.repaired ? (
                    <Badge className="bg-success/15 text-success">
                      repaired
                    </Badge>
                  ) : null}
                </div>
                <span className="text-xs text-text-secondary">{c.message}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {!running && (report?.checks?.length ?? 0) === 0 && !report?.error ? (
        <span className="py-6 text-center text-sm text-text-tertiary">
          No checks reported.
        </span>
      ) : null}
    </div>
  );
}
