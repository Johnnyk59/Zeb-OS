/**
 * ZebChatPage — ZebOS bubble chat with the thinking-brain overlay.
 *
 * Speaks the same JSON-RPC gateway dialect the TUI uses, over /api/ws
 * (`session.create` → `prompt.submit` → `message.delta` stream), so chat
 * runs on Hermes' proven backend with a completely redesigned surface:
 *
 *   ┌──────────────── top bar (full width) ────────────────┐
 *   │ messages, pinned LEFT            ╭─ brain overlay ─╮ │
 *   │ (bubbles never cross under       │  neurons firing │ │
 *   │  the brain in split mode)        ╰─────────────────╯ │
 *   └────────────── composer (full width) ─────────────────┘
 *
 * Sidebar visible → brain floats in the top-right corner.
 * Sidebar hidden  → 50/50 split: chat left half, brain right half.
 *
 * The brain's energy tracks agent activity and prompt complexity: it rests
 * motionless at idle, wakes for work, and becomes a full signal storm for
 * difficult tasks.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  CircleStop,
  ExternalLink,
  FileText,
  Mic,
  Plus,
  Send,
  Volume2,
  VolumeX,
  Wrench,
  X,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { cn } from "@/lib/utils";
import { BrainCanvas } from "@/components/BrainCanvas";
import { Markdown } from "@/components/Markdown";
import { GatewayClient } from "@/lib/gatewayClient";
import {
  gatewayModelSwitchValue,
  mergeModelIdentity,
  modelIdentityLabel,
  reduceLiveTasks,
  resolveAgentDashboardUrl,
  type LiveTask,
  type ModelIdentity,
} from "@/lib/chat-operations";
import {
  chatSessionStorageKey,
  restoreChatMessages,
  storedSessionId,
  type GatewaySessionPayload,
} from "@/lib/zeb-chat-session";
import {
  deriveBrainEnergy,
  estimateTaskIntensity,
} from "@/lib/brain-activity";
import { useProfileScope } from "@/contexts/useProfileScope";
import { useVoiceChat } from "@/hooks/useVoiceChat";
import { api, ZEB_BASE_PATH } from "@/lib/api";
import type { AgentRecord, ModelOptionsResponse } from "@/lib/api";

interface ToolChip {
  id: string;
  name: string;
  done: boolean;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  tools?: ToolChip[];
  error?: boolean;
  model?: string;
  provider?: string;
  delivery?: "queued" | "steered";
}

interface PendingAttachment {
  id: string;
  file: File;
  state: "uploading" | "ready" | "error";
  promptRef?: string;
  error?: string;
}

interface QueuedPrompt {
  id: string;
  text: string;
  files: File[];
}

let _mid = 0;
const nextId = () => `m${++_mid}`;
const MAX_BROWSER_ATTACHMENT_BYTES = 24 * 1024 * 1024;

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

async function uploadChatAttachment(
  gateway: GatewayClient,
  sessionId: string,
  file: File,
): Promise<string> {
  const dataUrl = await fileToDataUrl(file);
  if (file.type.startsWith("image/")) {
    const result = await gateway.request<{ text?: string }>("image.attach_bytes", {
      session_id: sessionId,
      content_base64: dataUrl,
      filename: file.name,
    });
    return result.text || `[User attached image: ${file.name}]`;
  }
  if (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) {
    try {
      const result = await gateway.request<{ text?: string }>("pdf.attach", {
        session_id: sessionId,
        content_base64: dataUrl,
        filename: file.name,
      });
      return result.text || `[User attached PDF: ${file.name}]`;
    } catch {
      // A PDF remains usable as a normal file if poppler is unavailable.
    }
  }
  const result = await gateway.request<{ ref_text?: string }>("file.attach", {
    session_id: sessionId,
    path: file.name,
    data_url: dataUrl,
    name: file.name,
  });
  return result.ref_text || `@file:${file.name}`;
}

const AGENT_SLOTS = [
  { id: "quant", label: "Quant Bot", defaultUrl: "/agent-dashboards/quant/" },
  { id: "socials", label: "Socials Agent", defaultUrl: "" },
  { id: "jewelry", label: "Jew", defaultUrl: "" },
] as const;

export default function ZebChatPage({
  isActive = true,
  sidebarCollapsed = false,
}: {
  isActive?: boolean;
  sidebarCollapsed?: boolean;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const routedPrimary =
    searchParams.get("primary") || searchParams.get("resume") || "";
  const routedSecondary = searchParams.get("secondary") || "";
  const routedSplit = searchParams.get("split") === "1";
  const [dualOpen, setDualOpen] = useState(false);
  const dual = dualOpen || Boolean(routedSecondary || routedSplit);

  const updateRoute = useCallback(
    (pane: "primary" | "secondary", sessionId: string) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          next.delete("resume");
          next.set(pane, sessionId);
          if (pane === "secondary") next.delete("split");
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const openDual = useCallback(() => {
    setDualOpen(true);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.set("split", "1");
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);
  const closeDual = useCallback(() => {
    setDualOpen(false);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("secondary");
        next.delete("split");
        return next;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1", dual ? "flex-row" : "flex-col")}>
      <div className={cn("flex min-h-0 min-w-0", dual ? "w-1/2 border-r border-current/10" : "flex-1")}>
        <ChatPane
          pane="primary"
          requestedStoredSessionId={routedPrimary}
          isActive={isActive}
          sidebarCollapsed={sidebarCollapsed}
          showBrain={!dual}
          showAgentNav={!dual}
          onOpenSplit={!dual ? openDual : undefined}
          onStoredSessionChange={(sessionId) => {
            if (isActive) updateRoute("primary", sessionId);
          }}
        />
      </div>
      {dual ? (
        <div className="flex min-h-0 min-w-0 w-1/2">
          <ChatPane
            pane="secondary"
            requestedStoredSessionId={routedSecondary}
            isActive={isActive}
            sidebarCollapsed={false}
            showBrain={false}
            showAgentNav={false}
            onStoredSessionChange={(sessionId) => {
              if (isActive) updateRoute("secondary", sessionId);
            }}
            onClose={closeDual}
          />
        </div>
      ) : null}
    </div>
  );
}

function ChatPane({
  pane,
  requestedStoredSessionId,
  isActive = true,
  sidebarCollapsed = false,
  showBrain = true,
  showAgentNav = true,
  onOpenSplit,
  onStoredSessionChange,
  onClose,
}: {
  pane: "primary" | "secondary";
  requestedStoredSessionId?: string;
  isActive?: boolean;
  sidebarCollapsed?: boolean;
  showBrain?: boolean;
  showAgentNav?: boolean;
  onOpenSplit?: () => void;
  onStoredSessionChange?: (sessionId: string) => void;
  onClose?: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [conn, setConn] = useState<"connecting" | "open" | "error" | "closed">(
    "connecting",
  );
  const [banner, setBanner] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [modelLabel, setModelLabel] = useState("");
  const [modelOpts, setModelOpts] = useState<ModelOptionsResponse | null>(null);
  const [switching, setSwitching] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [taskIntensity, setTaskIntensity] = useState(0.55);
  const [toolStarts, setToolStarts] = useState(0);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [draggingFile, setDraggingFile] = useState(false);
  const [queuedCount, setQueuedCount] = useState(0);
  const [activeTasks, setActiveTasks] = useState<LiveTask[]>([]);

  const gwRef = useRef<GatewayClient | null>(null);
  const sessionIdRef = useRef<string>("");
  const storedSessionIdRef = useRef<string>("");
  const requestedSessionIdRef = useRef(requestedStoredSessionId || "");
  const observedRouteRef = useRef(false);
  const forceFreshSessionRef = useRef(false);
  const busyRef = useRef(false);
  const currentModelRef = useRef<ModelIdentity>({});
  const responseModelRef = useRef<ModelIdentity>({});
  const queuedPromptsRef = useRef<QueuedPrompt[]>([]);
  const dispatchPromptRef = useRef<(prompt: QueuedPrompt) => void>(() => {});
  const drainQueueRef = useRef<() => void>(() => {});
  const onStoredSessionChangeRef = useRef(onStoredSessionChange);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const { profile: scopedProfile } = useProfileScope();
  busyRef.current = busy;
  onStoredSessionChangeRef.current = onStoredSessionChange;

  const adoptModelIdentity = useCallback((identity: ModelIdentity) => {
    currentModelRef.current = identity;
    setModelLabel(modelIdentityLabel(identity));
    setModelOpts((previous) =>
      previous
        ? {
            ...previous,
            model: identity.model || previous.model,
            provider: identity.provider || previous.provider,
          }
        : previous,
    );
  }, []);

  const applyTaskEvent = useCallback((type: string, payload: unknown) => {
    setActiveTasks((current) => reduceLiveTasks(current, type, payload));
  }, []);

  useEffect(() => {
    requestedSessionIdRef.current = requestedStoredSessionId || "";
    if (!observedRouteRef.current) {
      observedRouteRef.current = true;
      return;
    }
    if (
      requestedStoredSessionId &&
      requestedStoredSessionId !== storedSessionIdRef.current
    ) {
      setNonce((value) => value + 1);
    }
  }, [requestedStoredSessionId]);

  useEffect(() => {
    let alive = true;
    const poll = () => {
      if (document.hidden) return;
      api
        .getAgents()
        .then((result) => {
          if (alive) setAgents(result.agents ?? []);
        })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const resizeInput = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, Math.floor(window.innerHeight * 0.4))}px`;
  }, []);

  useEffect(() => {
    resizeInput();
  }, [input, resizeInput]);

  // Background brain activity (autonomy / self-evolution / self-review),
  // polled from the server. The live chat turn overrides it below.
  const [bgStatus, setBgStatus] = useState<string>("idle");
  useEffect(() => {
    let alive = true;
    const poll = () => {
      if (document.hidden) return;
      api
        .getBrainStatus()
        .then((s) => {
          if (alive) setBgStatus(s.status || "idle");
        })
        .catch(() => {});
    };
    poll();
    const id = setInterval(poll, 4000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Live brain status pill. Chat-turn state wins; otherwise reflect the
  // background mind ("Learning" while bots run), else Idle.
  const brainStatus = useMemo<{ label: string; dot: string; text: string }>(() => {
    if (conn === "connecting")
      return { label: "Connecting", dot: "bg-warning", text: "text-warning" };
    if (conn === "error" || conn === "closed")
      return { label: "Offline", dot: "bg-destructive", text: "text-destructive" };
    if (thinking)
      return { label: "Thinking", dot: "bg-warning", text: "text-warning" };
    if (busy)
      return { label: "Processing", dot: "bg-[#c8ccd3]", text: "text-[#c8ccd3]" };
    if (bgStatus === "learning")
      return { label: "Learning", dot: "bg-[#d3ad78]", text: "text-[#d3ad78]" };
    if (bgStatus === "processing" || bgStatus === "thinking")
      return { label: "Processing", dot: "bg-[#c8ccd3]", text: "text-[#c8ccd3]" };
    return { label: "Idle", dot: "bg-white/35", text: "text-text-secondary" };
  }, [conn, thinking, busy, bgStatus]);

  const energy = deriveBrainEnergy({
    busy,
    thinking,
    taskIntensity,
    toolStarts,
    bgStatus,
  });
  const split = sidebarCollapsed && showBrain;

  // Model label for the top bar (best-effort).
  useEffect(() => {
    api
      .getModelInfo()
      .then((info) => {
        if (!sessionIdRef.current) {
          adoptModelIdentity(mergeModelIdentity(info));
        }
      })
      .catch(() => setModelLabel(""));
  }, [adoptModelIdentity, nonce]);

  // Available models (local + every connected provider) for the in-chat
  // switcher. One dropdown, one click to change who's answering.
  useEffect(() => {
    api
      .getModelOptions()
      .then((options) => {
        if (!sessionIdRef.current) setModelOpts(options);
      })
      .catch(() => setModelOpts(null));
  }, [nonce]);

  // Switch the already-open gateway session, not only persisted config.
  const switchModel = useCallback(
    async (value: string) => {
      const [provider, model] = value.split(" ");
      const gateway = gwRef.current;
      const sessionId = sessionIdRef.current;
      if (!provider || !model || !gateway || !sessionId || busyRef.current) return;
      setSwitching(true);
      setBanner(null);
      try {
        const result = await gateway.request<{
          value?: string;
          warning?: string;
          confirm_required?: boolean;
          confirm_message?: string;
        }>("config.set", {
          session_id: sessionId,
          key: "model",
          value: gatewayModelSwitchValue(provider, model),
          confirm_expensive_model: true,
        });
        if (result.confirm_required) {
          throw new Error(result.confirm_message || "Model switch needs confirmation");
        }
        adoptModelIdentity({ provider, model: result.value || model });
        if (result.warning) setBanner(result.warning);
      } catch (error) {
        setBanner(error instanceof Error ? error.message : "Could not switch model");
      } finally {
        setSwitching(false);
      }
    },
    [adoptModelIdentity],
  );

  const appendAssistantDelta = useCallback((text: string) => {
    setMessages((msgs) => {
      const last = msgs[msgs.length - 1];
      if (last && last.role === "assistant" && last.streaming) {
        const next = msgs.slice(0, -1);
        next.push({ ...last, content: last.content + text });
        return next;
      }
      return [
        ...msgs,
        {
          id: nextId(),
          role: "assistant",
          content: text,
          streaming: true,
          ...responseModelRef.current,
        },
      ];
    });
  }, []);

  // Connect to the exact durable session for this pane. The live gateway id is
  // transport-only; the stored id survives refreshes and is routed in the URL.
  useEffect(() => {
    let cancelled = false;
    const gw = new GatewayClient();
    gwRef.current = gw;
    const offs: Array<() => void> = [];
    setConn("connecting");
    setBanner(null);
    setMessages([]);
    setBusy(false);
    setThinking(false);
    setActiveTasks([]);
    setAttachments([]);
    queuedPromptsRef.current = [];
    setQueuedCount(0);
    sessionIdRef.current = "";
    storedSessionIdRef.current = "";

    const mine = (sid?: string) =>
      Boolean(sid && sessionIdRef.current && sid === sessionIdRef.current);

    (async () => {
      try {
        await gw.connect();
        if (cancelled) return;

        offs.push(
          gw.on<{ text?: string; model?: string; provider?: string }>("message.start", (ev) => {
            if (!mine(ev.session_id)) return;
            const identity = mergeModelIdentity(ev.payload, currentModelRef.current);
            responseModelRef.current = identity;
            setBusy(true);
            setThinking(false);
            setMessages((msgs) => [
              ...msgs,
              {
                id: nextId(),
                role: "assistant",
                content: "",
                streaming: true,
                ...identity,
              },
            ]);
          }),
          gw.on<{ text?: string }>("message.delta", (ev) => {
            if (!mine(ev.session_id)) return;
            setThinking(false);
            appendAssistantDelta(ev.payload?.text ?? "");
          }),
          gw.on<{ text?: string; model?: string; provider?: string }>("message.complete", (ev) => {
            if (!mine(ev.session_id)) return;
            const identity = mergeModelIdentity(
              ev.payload,
              responseModelRef.current.model
                ? responseModelRef.current
                : currentModelRef.current,
            );
            setThinking(false);
            setActiveTasks([]);
            // Read the reply aloud when voice mode is on (no-op otherwise).
            speakRef.current(ev.payload?.text ?? "");
            setMessages((msgs) => {
              const finalText = ev.payload?.text ?? "";
              const last = msgs[msgs.length - 1];
              if (last && last.role === "assistant" && last.streaming) {
                const next = msgs.slice(0, -1);
                next.push({
                  ...last,
                  ...identity,
                  streaming: false,
                  content: last.content || finalText,
                });
                return next;
              }
              if (finalText) {
                return [
                  ...msgs,
                  { id: nextId(), role: "assistant", content: finalText, ...identity },
                ];
              }
              return msgs;
            });
          }),
          gw.on("thinking.delta", (ev) => {
            if (!mine(ev.session_id)) return;
            setThinking(true);
          }),
          gw.on<{ tool_id?: string; name?: string }>("tool.start", (ev) => {
            if (!mine(ev.session_id)) return;
            applyTaskEvent("tool.start", ev.payload);
            setToolStarts((count) => count + 1);
            const chip: ToolChip = {
              id: ev.payload?.tool_id || nextId(),
              name: ev.payload?.name || "tool",
              done: false,
            };
            setMessages((msgs) => {
              const last = msgs[msgs.length - 1];
              if (last && last.role === "assistant" && last.streaming) {
                const next = msgs.slice(0, -1);
                next.push({ ...last, tools: [...(last.tools ?? []), chip] });
                return next;
              }
              return [
                ...msgs,
                {
                  id: nextId(),
                  role: "assistant",
                  content: "",
                  streaming: true,
                  tools: [chip],
                  ...responseModelRef.current,
                },
              ];
            });
          }),
          gw.on<{ tool_id?: string }>("tool.complete", (ev) => {
            if (!mine(ev.session_id)) return;
            applyTaskEvent("tool.complete", ev.payload);
            const tid = ev.payload?.tool_id;
            if (!tid) return;
            setMessages((msgs) =>
              msgs.map((m) =>
                m.tools?.some((t) => t.id === tid)
                  ? {
                      ...m,
                      tools: m.tools!.map((t) =>
                        t.id === tid ? { ...t, done: true } : t,
                      ),
                    }
                  : m,
              ),
            );
          }),
          gw.on("tool.progress", (ev) => {
            if (!mine(ev.session_id)) return;
            applyTaskEvent("tool.progress", ev.payload);
          }),
          gw.on("tool.generating", (ev) => {
            if (!mine(ev.session_id)) return;
            applyTaskEvent("tool.generating", ev.payload);
          }),
          gw.on("status.update", (ev) => {
            if (!mine(ev.session_id)) return;
            applyTaskEvent("status.update", ev.payload);
          }),
          ...(["subagent.start", "subagent.progress", "subagent.complete"] as const).map(
            (type) =>
              gw.on(type, (ev) => {
                if (!mine(ev.session_id)) return;
                applyTaskEvent(type, ev.payload);
              }),
          ),
          gw.on<{ message?: string; text?: string }>("error", (ev) => {
            if (!mine(ev.session_id)) return;
            setBusy(false);
            busyRef.current = false;
            setThinking(false);
            setActiveTasks([]);
            const msg =
              ev.payload?.message || ev.payload?.text || "Something went wrong";
            setMessages((msgs) => [
              ...msgs,
              { id: nextId(), role: "assistant", content: msg, error: true },
            ]);
            queueMicrotask(() => drainQueueRef.current());
          }),
          gw.on<{ running?: boolean; model?: string; provider?: string }>("session.info", (ev) => {
            if (!mine(ev.session_id)) return;
            const identity = mergeModelIdentity(ev.payload, currentModelRef.current);
            adoptModelIdentity(identity);
            setMessages((current) => {
              const last = current[current.length - 1];
              if (!last || last.role !== "assistant" || !last.streaming) return current;
              return [...current.slice(0, -1), { ...last, ...identity }];
            });
            const running = Boolean(ev.payload?.running);
            setBusy(running);
            busyRef.current = running;
            if (!running) {
              setThinking(false);
              queueMicrotask(() => drainQueueRef.current());
            }
          }),
          gw.onState((s) => {
            if (cancelled) return;
            if (s === "closed" || s === "error") setConn(s);
          }),
        );

        const storageKey = chatSessionStorageKey(scopedProfile, pane);
        const forceFreshSession = forceFreshSessionRef.current;
        forceFreshSessionRef.current = false;
        let resumeTarget = requestedSessionIdRef.current;
        if (!resumeTarget) {
          try {
            resumeTarget = localStorage.getItem(storageKey) || "";
          } catch {
            resumeTarget = "";
          }
        }
        if (!forceFreshSession && !resumeTarget && pane === "primary") {
          try {
            const latest = await gw.request<{ session_id?: string | null }>(
              "session.most_recent",
              scopedProfile ? { profile: scopedProfile } : {},
            );
            resumeTarget = latest.session_id || "";
          } catch {
            // A first-run install simply has no recent session.
          }
        }

        let res: GatewaySessionPayload;
        if (resumeTarget) {
          try {
            res = await gw.request<GatewaySessionPayload>("session.resume", {
              session_id: resumeTarget,
              source: "web",
              ...(scopedProfile ? { profile: scopedProfile } : {}),
            });
          } catch {
            res = await gw.request<GatewaySessionPayload>("session.create", {
              source: "web",
              ...(scopedProfile ? { profile: scopedProfile } : {}),
            });
          }
        } else {
          res = await gw.request<GatewaySessionPayload>("session.create", {
            source: "web",
            ...(scopedProfile ? { profile: scopedProfile } : {}),
          });
        }
        if (cancelled) return;
        sessionIdRef.current = res.session_id;
        adoptModelIdentity(mergeModelIdentity(res.info, currentModelRef.current));
        const durableId = storedSessionId(res);
        storedSessionIdRef.current = durableId;
        setMessages(
          restoreChatMessages(res).map((message) => ({
            ...message,
            id: nextId(),
          })),
        );
        const running = Boolean(res.running || res.status === "streaming");
        setBusy(running);
        busyRef.current = running;
        if (durableId) {
          try {
            localStorage.setItem(storageKey, durableId);
          } catch {
            // URL routing remains the durable fallback when storage is blocked.
          }
          onStoredSessionChangeRef.current?.(durableId);
        }
        setConn("open");
        void gw
          .request<ModelOptionsResponse>("model.options", {
            session_id: res.session_id,
          })
          .then((options) => {
            if (!cancelled) setModelOpts(options);
          })
          .catch(() => {});
      } catch (e) {
        if (cancelled) return;
        setConn("error");
        setBanner(
          e instanceof Error ? e.message : "Could not connect to the gateway",
        );
      }
    })();

    return () => {
      cancelled = true;
      offs.forEach((off) => off());
      gw.close();
    };
  }, [
    adoptModelIdentity,
    appendAssistantDelta,
    applyTaskEvent,
    nonce,
    pane,
    scopedProfile,
  ]);

  // Autoscroll on new content while the tab is active.
  useEffect(() => {
    if (!isActive) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isActive]);

  const dispatchPrompt = useCallback((prompt: QueuedPrompt) => {
    const gw = gwRef.current;
    const sessionId = sessionIdRef.current;
    if (!gw || !sessionId) return;
    busyRef.current = true;
    setBusy(true);
    setTaskIntensity(
      estimateTaskIntensity(
        `${prompt.text}\n${prompt.files.map((file) => file.name).join("\n")}`,
      ),
    );
    setToolStarts(0);

    void (async () => {
      try {
        const attachmentRefs: string[] = [];
        for (const file of prompt.files) {
          attachmentRefs.push(await uploadChatAttachment(gw, sessionId, file));
        }
        const text = [attachmentRefs.join("\n"), prompt.text]
          .filter(Boolean)
          .join("\n\n") || "Review the attached file.";
        await gw.request("prompt.submit", { session_id: sessionId, text });
      } catch (error) {
        busyRef.current = false;
        setBusy(false);
        setThinking(false);
        setMessages((current) => [
          ...current,
          {
            id: nextId(),
            role: "assistant",
            content: error instanceof Error ? error.message : "Failed to send",
            error: true,
          },
        ]);
        queueMicrotask(() => drainQueueRef.current());
      }
    })();
  }, []);
  dispatchPromptRef.current = dispatchPrompt;

  const drainQueue = useCallback(() => {
    if (busyRef.current || conn !== "open") return;
    const next = queuedPromptsRef.current.shift();
    setQueuedCount(queuedPromptsRef.current.length);
    if (next) dispatchPromptRef.current(next);
  }, [conn]);
  drainQueueRef.current = drainQueue;

  const sendText = useCallback(
    (raw: string) => {
      const text = raw.trim();
      const files = attachments
        .filter((attachment) => attachment.state === "ready")
        .map((attachment) => attachment.file);
      if (
        (!text && files.length === 0) ||
        conn !== "open" ||
        !sessionIdRef.current
      ) {
        return;
      }

      const prompt: QueuedPrompt = { id: nextId(), text, files };
      const queued = busyRef.current;
      const fileSummary = files.length
        ? `\n${files.map((file) => `Attached: ${file.name}`).join("\n")}`
        : "";
      setInput("");
      setAttachments([]);
      setMessages((current) => [
        ...current,
        {
          id: prompt.id,
          role: "user",
          content: `${text}${fileSummary}`.trim(),
          delivery: queued ? "queued" : undefined,
        },
      ]);
      if (queued) {
        queuedPromptsRef.current.push(prompt);
        setQueuedCount(queuedPromptsRef.current.length);
      } else {
        dispatchPromptRef.current(prompt);
      }
    },
    [attachments, conn],
  );

  const send = useCallback(() => sendText(input), [sendText, input]);

  const interrupt = useCallback(() => {
    const gw = gwRef.current;
    if (!gw || !sessionIdRef.current || !busyRef.current) return;
    gw.request("session.interrupt", { session_id: sessionIdRef.current }).catch(
      () => {},
    );
    setThinking(false);
  }, []);

  const voice = useVoiceChat(
    (transcript) => sendText(transcript),
    () => {
      if (busyRef.current) interrupt();
    },
  );
  const speakRef = useRef(voice.speak);
  speakRef.current = voice.speak;

  const steer = useCallback(() => {
    const text = input.trim();
    const gw = gwRef.current;
    if (
      !text ||
      !gw ||
      !sessionIdRef.current ||
      !busyRef.current ||
      attachments.some((attachment) => attachment.state === "ready")
    ) {
      return;
    }
    setInput("");
    void gw
      .request("session.steer", { session_id: sessionIdRef.current, text })
      .then(() => {
        setMessages((current) => [
          ...current,
          {
            id: nextId(),
            role: "user",
            content: text,
            delivery: "steered",
          },
        ]);
      })
      .catch(() => {
        const prompt = { id: nextId(), text, files: [] };
        queuedPromptsRef.current.push(prompt);
        setQueuedCount(queuedPromptsRef.current.length);
        setMessages((current) => [
          ...current,
          {
            id: prompt.id,
            role: "user",
            content: text,
            delivery: "queued",
          },
        ]);
      });
  }, [attachments, input]);

  const openSplit = useCallback(() => onOpenSplit?.(), [onOpenSplit]);

  const startNewChat = useCallback(() => {
    if (pane !== "primary") return;
    const storageKey = chatSessionStorageKey(scopedProfile, pane);
    try {
      localStorage.removeItem(storageKey);
    } catch {
      // The route is replaced once the fresh durable session is created.
    }
    requestedSessionIdRef.current = "";
    forceFreshSessionRef.current = true;
    storedSessionIdRef.current = "";
    queuedPromptsRef.current = [];
    setQueuedCount(0);
    const gateway = gwRef.current;
    const sessionId = sessionIdRef.current;
    const reconnect = () => setNonce((value) => value + 1);
    if (!gateway || !sessionId) {
      reconnect();
      return;
    }
    void gateway
      .request("session.close", { session_id: sessionId })
      .catch(() => {})
      .finally(reconnect);
  }, [pane, scopedProfile]);

  const addDroppedFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files).map<PendingAttachment>((file) =>
      file.size > MAX_BROWSER_ATTACHMENT_BYTES
        ? {
            id: `${nextId()}-${file.name}`,
            file,
            state: "error",
            error: "File is larger than the 24 MB browser upload limit",
          }
        : { id: `${nextId()}-${file.name}`, file, state: "ready" },
    );
    setAttachments((current) => [...current, ...incoming]);
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((current) =>
      current.filter((attachment) => attachment.id !== id),
    );
  }, []);

  const statusDot = useMemo(() => {
    const color =
      conn === "open"
        ? "bg-[#c8ccd3]"
        : conn === "connecting"
          ? "bg-warning"
          : "bg-destructive";
    const label =
      conn === "open"
        ? busy
          ? thinking
            ? "Thinking…"
            : queuedCount
              ? `Working · ${queuedCount} queued`
              : "Working…"
          : "Ready"
        : conn === "connecting"
          ? "Connecting…"
          : "Disconnected";
    return (
      <span className="flex items-center gap-2 text-xs text-text-secondary">
        <span className={cn("h-1.5 w-1.5 rounded-full", color)} />
        {label}
      </span>
    );
  }, [conn, busy, queuedCount, thinking]);

  const agentSlots: AgentRecord[] = AGENT_SLOTS.map((slot) => {
    const record = agents.find((agent) => agent.id === slot.id);
    return {
      id: slot.id,
      label: slot.label,
      dashboard_url: record?.dashboard_url || slot.defaultUrl,
      status: record?.status ?? "awaiting Zeb",
      updated_at: record?.updated_at,
    };
  });
  const openAgentDashboard = useCallback((agent: AgentRecord) => {
    const target = agentDashboardUrl(agent.dashboard_url);
    if (!target) {
      setBanner(`${agent.label} is waiting for Zeb to register its dashboard URL.`);
      return;
    }
    window.open(target, "_blank", "noopener,noreferrer");
  }, []);
  const visibleTasks = useMemo<LiveTask[]>(
    () => [
      ...(busy
        ? [
            {
              id: "current-response",
              title: thinking ? "Reasoning through response" : "Building response",
              detail: modelLabel || undefined,
              startedAt: 0,
            },
          ]
        : []),
      ...activeTasks,
    ],
    [activeTasks, busy, modelLabel, thinking],
  );
  const selectedModelValue = useMemo(() => {
    const provider = modelOpts?.provider || "";
    const model = modelOpts?.model || "";
    const providerModels =
      modelOpts?.providers?.find((candidate) => candidate.slug === provider)?.models ?? [];
    const optionModel =
      providerModels.find((candidate) => candidate === model) ||
      providerModels.find((candidate) => model.endsWith(`/${candidate}`)) ||
      model;
    return `${provider} ${optionModel}`;
  }, [modelOpts]);

  return (
    <div
      className="zeb-chat-pane relative flex min-h-0 min-w-0 flex-1 flex-col"
      onDragEnter={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          setDraggingFile(true);
        }
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }
      }}
      onDragLeave={(event) => {
        const next = event.relatedTarget;
        if (!(next instanceof Node) || !event.currentTarget.contains(next)) {
          setDraggingFile(false);
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDraggingFile(false);
        if (event.dataTransfer.files.length) {
          addDroppedFiles(event.dataTransfer.files);
        }
      }}
    >
      {draggingFile ? (
        <div className="pointer-events-none absolute inset-3 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-[#69d5ff]/60 bg-black/80 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 text-center">
            <FileText className="h-9 w-9 text-[#69d5ff]" />
            <span className="font-mono text-sm uppercase tracking-[0.16em] text-white">
              Drop files into this chat
            </span>
          </div>
        </div>
      ) : null}
      {/* Brain overlay — removed entirely while two independent chats are open. */}
      {showBrain ? (
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute -right-[4%] top-0 z-10",
            "transition-[width,height] duration-300 ease-[cubic-bezier(0.23,1,0.32,1)]",
            split ? "h-full w-[44%]" : "h-[58%] w-[44%] min-w-80",
          )}
          style={{
            WebkitMaskImage:
              "radial-gradient(ellipse 70% 70% at center, black 52%, transparent 82%)",
            maskImage:
              "radial-gradient(ellipse 70% 70% at center, black 52%, transparent 82%)",
          }}
        >
          <BrainCanvas energy={energy} className="h-full w-full" />
        </div>
      ) : null}

      {/* Brain status pill — real-time label of what Zeb is doing, floating
          over the brain. Chat-turn state (Thinking/Processing) overrides the
          background mind (Learning/Idle). */}
      {showBrain ? <div
        aria-live="polite"
        className={cn(
          "pointer-events-none absolute z-30 flex items-center gap-2 rounded-full",
          "border border-current/10 bg-background-base/70 px-3 py-1 backdrop-blur-md",
          "font-mono text-[0.7rem] uppercase tracking-[0.14em] shadow-sm",
          split ? "right-6 top-16" : "right-5 top-16",
          brainStatus.text,
        )}
      >
        <span
          className={cn(
            "h-1.5 w-1.5 rounded-full",
            brainStatus.dot,
            brainStatus.label !== "Idle" && brainStatus.label !== "Offline"
              ? "animate-pulse"
              : "",
          )}
        />
        {brainStatus.label}
      </div> : null}

      {showBrain ? (
        <aside
          aria-label="Active tasks"
          aria-live="polite"
          className={cn(
            "pointer-events-none absolute right-5 top-[58%] z-10 hidden w-[min(26rem,38vw)] sm:block",
            "max-h-[24%] overflow-hidden rounded-xl border border-white/10",
            "bg-black/25 px-3 py-2.5 shadow-[0_16px_48px_rgba(0,0,0,.18)] backdrop-blur-md",
          )}
        >
          <div className="mb-2 flex items-center justify-between gap-3 font-mono text-[0.62rem] uppercase tracking-[0.15em] text-text-tertiary">
            <span>Active tasks</span>
            <span>{visibleTasks.length}</span>
          </div>
          <div className="flex max-h-[calc(24dvh-2.5rem)] flex-col gap-2 overflow-hidden">
            {visibleTasks.length ? (
              visibleTasks.map((task) => (
                <div key={task.id} className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-2.5 py-2">
                  <div className="flex items-center gap-2">
                    <Spinner className="shrink-0 text-[0.55rem]" />
                    <span className="min-w-0 flex-1 truncate text-xs text-text-secondary">
                      {task.title}
                    </span>
                    {task.progress !== undefined ? (
                      <span className="font-mono text-[0.62rem] text-text-tertiary">
                        {Math.round(task.progress)}%
                      </span>
                    ) : null}
                    {task.eta ? (
                      <span className="font-mono text-[0.62rem] text-text-tertiary">
                        {task.eta}
                      </span>
                    ) : null}
                  </div>
                  {task.detail ? (
                    <div className="mt-1 truncate pl-5 text-[0.68rem] text-text-tertiary">
                      {task.detail}
                    </div>
                  ) : null}
                  {task.progress !== undefined ? (
                    <div className="mt-1.5 ml-5 h-px overflow-hidden bg-white/10">
                      <div
                        className="h-full bg-white/55 transition-[width] duration-300"
                        style={{ width: `${task.progress}%` }}
                      />
                    </div>
                  ) : null}
                </div>
              ))
            ) : (
              <div className="py-1 text-xs text-text-tertiary">No active tasks</div>
            )}
          </div>
        </aside>
      ) : null}

      {/* Top bar — full width, floats above the brain */}
      <header className="zeb-chat-header relative z-20 flex min-h-14 shrink-0 items-center justify-between gap-3 border-b border-current/10 px-3 sm:px-5">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          {statusDot}
          {showAgentNav ? <nav className="scrollbar-none flex min-w-0 flex-1 items-center gap-2 overflow-x-auto" aria-label="Agent dashboards">
            {agentSlots.map((agent) => {
              const connected = Boolean(agentDashboardUrl(agent.dashboard_url));
              return (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => openAgentDashboard(agent)}
                  className={cn(
                    "zeb-agent-tab group relative flex shrink-0 items-center gap-2 rounded-full border px-3.5 py-1.5",
                    "font-mono text-[0.66rem] font-bold uppercase tracking-[0.11em] transition-all duration-300",
                    connected
                      ? "border-white/15 text-[#e8e8e8] hover:border-white/35 hover:text-white"
                      : "border-white/8 text-text-tertiary hover:border-white/20 hover:text-text-secondary",
                  )}
                  title={connected ? `Open ${agent.label} in a new tab` : `${agent.label}: ${agent.status}`}
                >
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full transition-all duration-300",
                      connected
                        ? "bg-[#d7dae0] shadow-[0_0_10px_rgba(215,218,224,.55)]"
                        : "bg-current opacity-35 group-hover:opacity-70",
                    )}
                  />
                  {agent.label}
                  {connected ? <ExternalLink className="h-2.5 w-2.5 opacity-55" /> : null}
                </button>
              );
            })}
          </nav> : null}
        </div>
        <div className="flex items-center gap-2">
          {/* In-chat model switcher — local model + every connected provider,
              one click to change who answers. */}
          {modelOpts?.providers?.length ? (
            <div className="relative mr-3 hidden items-center sm:flex">
              <select
                value={selectedModelValue}
                onChange={(e) => void switchModel(e.target.value)}
                disabled={switching || busy}
                aria-label="Select model"
                className={cn(
                  "max-w-52 appearance-none truncate rounded-[var(--radius)]",
                  "border border-current/15 bg-midground/[0.04] py-1 pl-2.5 pr-7",
                  "font-mono text-xs text-text-secondary",
                  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/50",
                  "disabled:opacity-60",
                )}
              >
                {modelOpts.providers.map((p) => (
                  <optgroup key={p.slug} label={p.name}>
                    {(p.models ?? []).map((m) => (
                      <option key={`${p.slug}-${m}`} value={`${p.slug} ${m}`}>
                        {m}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
              {switching ? (
                <Spinner className="pointer-events-none absolute right-2 text-[0.6rem]" />
              ) : (
                <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5 text-text-tertiary" />
              )}
            </div>
          ) : modelLabel ? (
            <span className="mr-3 hidden truncate font-mono text-xs text-text-tertiary sm:block">
              {modelLabel}
            </span>
          ) : null}
          {pane === "primary" ? (
            <Button
              ghost
              size="sm"
              onClick={startNewChat}
              aria-label="New chat"
              title="Start a new chat"
              className="whitespace-nowrap font-mono text-[0.68rem] uppercase tracking-[0.1em]"
            >
              New Chat
            </Button>
          ) : null}
          {onOpenSplit ? (
            <Button
              ghost
              size="icon"
              onClick={openSplit}
              aria-label="Open split chat"
              title="Open split chat"
            >
              <Plus className="h-4 w-4" />
            </Button>
          ) : null}
          {onClose ? (
            <Button
              ghost
              size="icon"
              onClick={onClose}
              aria-label="Close second chat"
              title="Close second chat"
            >
              <X className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </header>

      {/* Messages — bubbles pinned to the left; in split mode they never
          cross into the brain's half. */}
      <div
        ref={scrollRef}
        className="relative z-0 min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6"
      >
        <div
          className={cn(
            "flex flex-col items-start gap-3",
            split ? "w-[60%] max-w-[60%] pr-6" : "max-w-4xl",
          )}
        >
          {banner ? (
            <div className="w-full rounded-[var(--radius)] border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {banner}
            </div>
          ) : null}

          {messages.length === 0 && !banner ? (
            <div className="flex flex-col gap-1 py-10 text-text-tertiary">
              <span className="text-lg text-text-secondary">
                What are we building?
              </span>
              <span className="text-sm">
                Provider model answers here — the local brain keeps thinking in
                the background.
              </span>
            </div>
          ) : null}

          {messages.map((m) => (
            <div
              key={m.id}
              className={cn(
                "zeb-message max-w-full rounded-[var(--radius)] px-5 py-4",
                m.role === "user"
                  ? "border border-midground/20 bg-midground/10"
                  : m.error
                    ? "border border-destructive/40 bg-destructive/10"
                    : "border border-current/10 bg-midground/[0.04]",
              )}
            >
              {m.tools && m.tools.length > 0 ? (
                <div className="mb-1.5 flex flex-wrap gap-1.5">
                  {m.tools.map((tl) => (
                    <span
                      key={tl.id}
                      className={cn(
                        "flex items-center gap-1 rounded-full border border-current/15 px-2 py-0.5 font-mono text-[0.65rem]",
                        tl.done
                          ? "text-text-tertiary"
                          : "text-midground",
                      )}
                    >
                      <Wrench className="h-2.5 w-2.5" />
                      {tl.name}
                      {!tl.done && <Spinner className="text-[0.55rem]" />}
                    </span>
                  ))}
                </div>
              ) : null}
              {m.delivery ? (
                <div className="mb-1.5 font-mono text-[0.62rem] uppercase tracking-[0.13em] text-[#69d5ff]">
                  {m.delivery === "steered" ? "Steered into live task" : "Queued next"}
                </div>
              ) : null}
              {m.role === "user" ? (
                <div className="whitespace-pre-wrap text-[1.0625rem] leading-7 text-midground">
                  {m.content}
                </div>
              ) : (
                <>
                  <Markdown content={m.content} streaming={m.streaming} size="chat" />
                  {modelIdentityLabel(m) ? (
                    <div className="mt-2 border-t border-white/[0.06] pt-1.5 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-text-tertiary">
                      {m.streaming ? "Responding with" : "Answered by"}{" "}
                      <span className="normal-case tracking-normal text-text-secondary">
                        {modelIdentityLabel(m)}
                      </span>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          ))}

          {busy &&
          !messages.some((m) => m.role === "assistant" && m.streaming) ? (
            <div className="flex items-center gap-2 px-1 py-1 text-sm text-text-tertiary">
              <Spinner /> {thinking ? "Thinking…" : "Zeb is on it…"}
            </div>
          ) : null}
        </div>
      </div>

      {/* Composer — full width, floats above the brain */}
      <footer className="zeb-composer relative z-20 shrink-0 border-t border-current/10 px-4 py-3 sm:px-6">
        {attachments.length ? (
          <div className="mb-2 flex flex-wrap gap-2" aria-label="Attached files">
            {attachments.map((attachment) => (
              <span
                key={attachment.id}
                className={cn(
                  "flex max-w-full items-center gap-2 rounded-full border px-3 py-1 font-mono text-xs",
                  attachment.state === "error"
                    ? "border-destructive/40 text-destructive"
                    : "border-[#69d5ff]/25 bg-[#69d5ff]/[0.06] text-[#bdeeff]",
                )}
                title={attachment.error || attachment.file.name}
              >
                <FileText className="h-3 w-3 shrink-0" />
                <span className="max-w-52 truncate">{attachment.file.name}</span>
                <button
                  type="button"
                  onClick={() => removeAttachment(attachment.id)}
                  aria-label={`Remove ${attachment.file.name}`}
                  className="rounded-full p-0.5 opacity-70 transition-opacity hover:opacity-100"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        ) : null}
        {voice.listening && voice.transcript ? (
          <div className="mb-2 rounded-lg border border-[#69d5ff]/20 bg-[#69d5ff]/[0.05] px-3 py-2 text-sm text-[#bdeeff]">
            {voice.transcript}
            <span className="ml-2 font-mono text-[0.62rem] uppercase tracking-[0.12em] text-text-tertiary">
              sends after {voice.silenceMs / 1000}s silence
            </span>
          </div>
        ) : null}
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            rows={1}
            placeholder={
              conn === "open" ? "Message Zeb…" : "Connecting to gateway…"
            }
            disabled={conn !== "open"}
            className={cn(
              "max-h-[40vh] min-h-14 flex-1 resize-none overflow-y-auto rounded-xl",
              "border border-current/15 bg-black/20 px-5 py-4 shadow-inner",
              "font-sans text-base text-midground placeholder:text-text-tertiary",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/50",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
          />
          {/* Voice chat — talk to Zeb in real time. Same session, same
              permissions as text. The mic sends what you say; the speaker
              toggles Zeb reading its replies back aloud. */}
          {voice.supported ? (
            <>
              <Button
                type="button"
                ghost
                size="icon"
                onClick={voice.toggleVoiceMode}
                aria-label={voice.voiceMode ? "Mute Zeb's voice" : "Let Zeb speak"}
                title={voice.voiceMode ? "Voice conversation on" : "Voice conversation off"}
                className={
                  voice.voiceMode ? "text-[#d1d4da]" : "text-text-tertiary"
                }
              >
                {voice.voiceMode ? (
                  <Volume2 className="h-4 w-4" />
                ) : (
                  <VolumeX className="h-4 w-4" />
                )}
              </Button>
              <Button
                type="button"
                ghost={!voice.listening}
                size="icon"
                onClick={() =>
                  voice.listening ? voice.stopListening() : voice.startListening()
                }
                disabled={conn !== "open"}
                aria-label={voice.listening ? "Stop listening" : "Talk to Zeb"}
                title={
                  voice.listening
                    ? "Listening until 2.5 seconds of silence"
                    : voice.speaking
                      ? "Interrupt Zeb and speak"
                      : "Start voice conversation"
                }
                className={
                  voice.listening
                    ? "animate-pulse bg-destructive/15 text-destructive"
                    : "text-midground"
                }
              >
                <Mic className="h-4 w-4" />
              </Button>
            </>
          ) : null}
          {busy ? (
            <Button
              type="button"
              ghost
              size="sm"
              onClick={steer}
              disabled={
                !input.trim() ||
                attachments.some((attachment) => attachment.state === "ready")
              }
              aria-label="Steer current task"
              title="Inject this into Zeb's current work without stopping it"
              className="font-mono text-xs uppercase tracking-[0.1em] text-[#69d5ff]"
            >
              Steer
            </Button>
          ) : null}
          {busy ? (
            <Button
              type="button"
              ghost
              size="icon"
              onClick={interrupt}
              aria-label="Stop"
              className="text-destructive"
            >
              <CircleStop className="h-4 w-4" />
            </Button>
          ) : null}
          <Button
            type="submit"
            size="icon"
            disabled={
              conn !== "open" ||
              (!input.trim() &&
                !attachments.some((attachment) => attachment.state === "ready"))
            }
            aria-label={busy ? "Queue message" : "Send"}
            title={busy ? "Queue for the next turn" : "Send"}
          >
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </footer>
    </div>
  );
}

function agentDashboardUrl(raw: string): string {
  return resolveAgentDashboardUrl(raw, {
    origin: window.location.origin,
    basePath: ZEB_BASE_PATH,
    pageHostname: window.location.hostname,
  });
}
