/**
 * ReposPage — saved open-source GitHub repos + discovery scan.
 *
 * Two actions: **Search** filters the saved list; **Scan GitHub** describes
 * a need in plain words, searches GitHub for matching open-source repos,
 * and saves every hit into the store (de-duped) ready for integration.
 */
import { useCallback, useEffect, useState } from "react";
import {
  Boxes,
  ExternalLink,
  Github,
  RefreshCw,
  Search,
  Star,
  Telescope,
  Trash2,
} from "lucide-react";
import { Badge } from "@nous-research/ui/ui/components/badge";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent } from "@nous-research/ui/ui/components/card";
import { Input } from "@nous-research/ui/ui/components/input";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { Switch } from "@nous-research/ui/ui/components/switch";
import { Toast } from "@nous-research/ui/ui/components/toast";
import { useToast } from "@nous-research/ui/hooks/use-toast";
import { api } from "@/lib/api";
import type { SavedRepo } from "@/lib/api";

export default function ReposPage() {
  const [repos, setRepos] = useState<SavedRepo[]>([]);
  const [totals, setTotals] = useState<{
    total: number;
    enabled: number;
    extracted: number;
  }>({ total: 0, enabled: 0, extracted: 0 });
  const [query, setQuery] = useState("");
  const [scanQuery, setScanQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const { toast, showToast } = useToast();

  const load = useCallback(
    async (q = "") => {
      setLoading(true);
      try {
        const res = await api.getRepos(q);
        setRepos(res.repos ?? []);
        setTotals({
          total: res.total ?? (res.repos ?? []).length,
          enabled: res.enabled_count ?? 0,
          extracted: res.extracted ?? 0,
        });
        if (res.error) showToast(res.error, "error");
      } catch (e) {
        showToast(`Failed to load repos: ${e}`, "error");
      } finally {
        setLoading(false);
      }
    },
    [showToast],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const res = await api.syncRepos();
      if (res.error) showToast(res.error, "error");
      else
        showToast(
          `Synced — ${res.extracted}/${res.total} repos extracted`,
          "success",
        );
      void load(query.trim());
    } catch (e) {
      showToast(`Sync failed: ${e}`, "error");
    } finally {
      setSyncing(false);
    }
  };

  const handleToggle = async (repo: SavedRepo, enabled: boolean) => {
    setToggling(repo.id);
    // Optimistic flip so the switch feels instant.
    setRepos((rs) => rs.map((r) => (r.id === repo.id ? { ...r, enabled } : r)));
    setTotals((t) => ({ ...t, enabled: t.enabled + (enabled ? 1 : -1) }));
    try {
      const res = await api.setRepoEnabled(repo.id, enabled);
      if (res.skills_toggled)
        showToast(
          `${enabled ? "Enabled" : "Disabled"} ${res.skills_toggled} skill${res.skills_toggled === 1 ? "" : "s"}`,
          "success",
        );
    } catch (e) {
      // Revert on failure.
      setRepos((rs) =>
        rs.map((r) => (r.id === repo.id ? { ...r, enabled: !enabled } : r)),
      );
      setTotals((t) => ({ ...t, enabled: t.enabled + (enabled ? -1 : 1) }));
      showToast(`Toggle failed: ${e}`, "error");
    } finally {
      setToggling(null);
    }
  };

  const handleSearch = () => void load(query.trim());

  const handleScan = async () => {
    const q = scanQuery.trim();
    if (!q) {
      showToast("Describe what you're looking for first", "error");
      return;
    }
    setScanning(true);
    try {
      const res = await api.scanRepos(q);
      if (res.error) {
        showToast(res.error, "error");
      } else {
        showToast(
          `Found ${res.results.length} repo${res.results.length === 1 ? "" : "s"}, saved ${res.added.length} new`,
          "success",
        );
      }
      void load(query.trim());
    } catch (e) {
      showToast(`Scan failed: ${e}`, "error");
    } finally {
      setScanning(false);
    }
  };

  const handleDelete = async (rid: string) => {
    setDeleting(rid);
    try {
      await api.deleteRepo(rid);
      setRepos((rs) => rs.filter((r) => r.id !== rid));
    } catch (e) {
      showToast(`Delete failed: ${e}`, "error");
    } finally {
      setDeleting(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {toast && <Toast toast={toast} />}

      {/* Discovery scan */}
      <Card>
        <CardContent className="flex flex-col gap-3 p-5">
          <div className="flex items-center gap-2 text-sm uppercase tracking-[0.1em] text-text-secondary">
            <Telescope className="h-4 w-4" /> Discover open-source repos
          </div>
          <div className="flex flex-wrap gap-2">
            <Input
              className="min-w-64 flex-1"
              placeholder="Describe a need — e.g. “offline text to speech”, “vector database”…"
              value={scanQuery}
              onChange={(e) => setScanQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleScan()}
            />
            <Button
              onClick={handleScan}
              disabled={scanning}
              prefix={scanning ? <Spinner /> : <Github className="h-4 w-4" />}
              className="uppercase"
            >
              Scan GitHub
            </Button>
          </div>
          <span className="text-xs text-text-tertiary">
            Results are saved below automatically, ready for integration.
          </span>
        </CardContent>
      </Card>

      {/* Saved repos + search */}
      <Card>
        <CardContent className="flex flex-col gap-3 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm uppercase tracking-[0.1em] text-text-secondary">
                GitHub repos
              </span>
              <Badge className="bg-midground/10 text-text-secondary">
                {totals.total} tracked
              </Badge>
              <Badge className="bg-[#40e8dc]/15 text-[#40e8dc]">
                {totals.extracted} extracted
              </Badge>
              <Badge className="bg-success/15 text-success">
                {totals.enabled} enabled
              </Badge>
            </div>
            <div className="flex gap-2">
              <Input
                className="w-52"
                placeholder="Filter repos…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              />
              <Button
                ghost
                onClick={handleSearch}
                prefix={<Search className="h-4 w-4" />}
                className="uppercase"
              >
                Search
              </Button>
              <Button
                ghost
                onClick={handleSync}
                disabled={syncing}
                prefix={
                  syncing ? <Spinner /> : <RefreshCw className="h-4 w-4" />
                }
                className="uppercase"
              >
                Sync
              </Button>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 py-6 text-text-secondary">
              <Spinner /> Loading…
            </div>
          ) : repos.length === 0 ? (
            <span className="py-6 text-center text-sm text-text-tertiary">
              No saved repos yet — scan GitHub above to discover some.
            </span>
          ) : (
            <ul className="flex flex-col divide-y divide-current/10">
              {repos.map((r) => (
                <li
                  key={r.id}
                  className={
                    "flex items-center justify-between gap-3 py-3 transition-opacity " +
                    (r.enabled === false ? "opacity-50" : "")
                  }
                >
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <div className="flex items-center gap-2">
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center gap-1.5 font-mono text-sm text-midground hover:underline"
                      >
                        {r.full_name}
                        <ExternalLink className="h-3 w-3 shrink-0 opacity-60" />
                      </a>
                      {r.extracted ? (
                        <Badge className="bg-[#40e8dc]/15 text-[#40e8dc]">
                          <Boxes className="mr-1 h-3 w-3" /> extracted
                        </Badge>
                      ) : null}
                    </div>
                    {r.description ? (
                      <span className="truncate text-xs text-text-secondary">
                        {r.description}
                      </span>
                    ) : null}
                    <span className="flex flex-wrap items-center gap-3 text-xs text-text-tertiary">
                      {r.language ? <span>{r.language}</span> : null}
                      {r.stars != null ? (
                        <span className="flex items-center gap-1">
                          <Star className="h-3 w-3" /> {r.stars}
                        </span>
                      ) : null}
                      {r.skills && r.skills.length > 0 ? (
                        <span className="font-mono">
                          {r.skills.join(", ")}
                        </span>
                      ) : null}
                    </span>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    {/* Enable/disable — cascades to the repo's extracted skills. */}
                    <div className="flex items-center gap-1.5">
                      {toggling === r.id ? <Spinner /> : null}
                      <Switch
                        checked={r.enabled !== false}
                        onCheckedChange={(v) => void handleToggle(r, v)}
                        aria-label={`${r.enabled !== false ? "Disable" : "Enable"} ${r.full_name}`}
                      />
                    </div>
                    <Button
                      ghost
                      size="icon"
                      aria-label={`Remove ${r.full_name}`}
                      onClick={() => void handleDelete(r.id)}
                      disabled={deleting === r.id}
                      className="text-text-tertiary hover:text-destructive"
                    >
                      {deleting === r.id ? (
                        <Spinner />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
