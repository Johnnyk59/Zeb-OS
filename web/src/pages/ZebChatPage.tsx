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
 * The brain's energy tracks agent activity: idle 0.05, waiting/streaming
 * ~0.75, thinking bursts ~0.95 — the same "thinks harder while working"
 * behaviour as the local backbone it visualizes.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CircleStop, Plus, Send, Wrench } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { cn } from "@/lib/utils";
import { BrainCanvas } from "@/components/BrainCanvas";
import { Markdown } from "@/components/Markdown";
import { GatewayClient } from "@/lib/gatewayClient";
import { useProfileScope } from "@/contexts/useProfileScope";
import { api } from "@/lib/api";

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
}

let _mid = 0;
const nextId = () => `m${++_mid}`;

export default function ZebChatPage({
  isActive = true,
  sidebarCollapsed = false,
}: {
  isActive?: boolean;
  sidebarCollapsed?: boolean;
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
  const [nonce, setNonce] = useState(0);

  const gwRef = useRef<GatewayClient | null>(null);
  const sessionIdRef = useRef<string>("");
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const { profile: scopedProfile } = useProfileScope();

  // Brain energy: thinking beats streaming beats idle.
  const energy = thinking ? 0.95 : busy ? 0.72 : 0.06;
  const split = sidebarCollapsed;

  // Model label for the top bar (best-effort).
  useEffect(() => {
    api
      .getModelInfo()
      .then((info) => {
        const m = info?.model || "";
        const p = info?.provider || "";
        setModelLabel(m ? (p ? `${p}/${m}` : m) : "");
      })
      .catch(() => setModelLabel(""));
  }, [nonce]);

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
        { id: nextId(), role: "assistant", content: text, streaming: true },
      ];
    });
  }, []);

  // Connect + wire events. Re-runs on New Chat (nonce) or profile switch.
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
    sessionIdRef.current = "";

    const mine = (sid?: string) =>
      !sid || !sessionIdRef.current || sid === sessionIdRef.current;

    (async () => {
      try {
        await gw.connect();
        if (cancelled) return;

        offs.push(
          gw.on<{ text?: string }>("message.start", (ev) => {
            if (!mine(ev.session_id)) return;
            setThinking(false);
            setMessages((msgs) => [
              ...msgs,
              { id: nextId(), role: "assistant", content: "", streaming: true },
            ]);
          }),
          gw.on<{ text?: string }>("message.delta", (ev) => {
            if (!mine(ev.session_id)) return;
            setThinking(false);
            appendAssistantDelta(ev.payload?.text ?? "");
          }),
          gw.on<{ text?: string }>("message.complete", (ev) => {
            if (!mine(ev.session_id)) return;
            setBusy(false);
            setThinking(false);
            setMessages((msgs) => {
              const finalText = ev.payload?.text ?? "";
              const last = msgs[msgs.length - 1];
              if (last && last.role === "assistant" && last.streaming) {
                const next = msgs.slice(0, -1);
                next.push({
                  ...last,
                  streaming: false,
                  content: last.content || finalText,
                });
                return next;
              }
              if (finalText) {
                return [
                  ...msgs,
                  { id: nextId(), role: "assistant", content: finalText },
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
                },
              ];
            });
          }),
          gw.on<{ tool_id?: string }>("tool.complete", (ev) => {
            if (!mine(ev.session_id)) return;
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
          gw.on<{ message?: string; text?: string }>("error", (ev) => {
            if (!mine(ev.session_id)) return;
            setBusy(false);
            setThinking(false);
            const msg =
              ev.payload?.message || ev.payload?.text || "Something went wrong";
            setMessages((msgs) => [
              ...msgs,
              { id: nextId(), role: "assistant", content: msg, error: true },
            ]);
          }),
          gw.onState((s) => {
            if (cancelled) return;
            if (s === "closed" || s === "error") setConn(s);
          }),
        );

        const res = await gw.request<{ session_id: string }>(
          "session.create",
          {},
        );
        if (cancelled) return;
        sessionIdRef.current = res.session_id;
        setConn("open");
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, scopedProfile]);

  // Autoscroll on new content while the tab is active.
  useEffect(() => {
    if (!isActive) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, isActive]);

  const send = useCallback(() => {
    const text = input.trim();
    const gw = gwRef.current;
    if (!text || !gw || conn !== "open" || !sessionIdRef.current) return;
    setInput("");
    setBusy(true);
    setMessages((msgs) => [
      ...msgs,
      { id: nextId(), role: "user", content: text },
    ]);
    gw.request("prompt.submit", {
      session_id: sessionIdRef.current,
      text,
    }).catch((e) => {
      setBusy(false);
      setMessages((msgs) => [
        ...msgs,
        {
          id: nextId(),
          role: "assistant",
          content: e instanceof Error ? e.message : "Failed to send",
          error: true,
        },
      ]);
    });
  }, [input, conn]);

  const interrupt = useCallback(() => {
    const gw = gwRef.current;
    if (!gw || !sessionIdRef.current) return;
    gw.request("session.interrupt", { session_id: sessionIdRef.current }).catch(
      () => {},
    );
    setBusy(false);
    setThinking(false);
  }, []);

  const newChat = useCallback(() => setNonce((n) => n + 1), []);

  const statusDot = useMemo(() => {
    const color =
      conn === "open"
        ? "bg-success"
        : conn === "connecting"
          ? "bg-warning"
          : "bg-destructive";
    const label =
      conn === "open"
        ? busy
          ? thinking
            ? "Thinking…"
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
  }, [conn, busy, thinking]);

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
      {/* Brain overlay — pointer-transparent; chat flows beneath it.
          Corner badge when the sidebar is visible, right half in split. */}
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute right-0 top-0 z-10",
          "transition-[width,height] duration-300 ease-[cubic-bezier(0.23,1,0.32,1)]",
          split ? "h-full w-1/2" : "h-[46%] w-[38%] min-w-72",
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

      {/* Top bar — full width, floats above the brain */}
      <header className="relative z-20 flex h-12 shrink-0 items-center justify-between gap-3 border-b border-current/10 bg-background-base/75 px-4 backdrop-blur-sm">
        <div className="flex min-w-0 items-center gap-3">
          <span className="font-sans text-display text-sm uppercase tracking-[0.14em] text-midground">
            Chat
          </span>
          {statusDot}
        </div>
        <div className="flex items-center gap-3">
          {modelLabel ? (
            <span className="hidden truncate font-mono text-xs text-text-tertiary sm:block">
              {modelLabel}
            </span>
          ) : null}
          <Button
            ghost
            size="sm"
            onClick={newChat}
            prefix={<Plus className="h-3.5 w-3.5" />}
            className="uppercase"
          >
            New chat
          </Button>
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
            split ? "w-1/2 max-w-[50%] pr-6" : "max-w-3xl",
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
                "max-w-full rounded-[var(--radius)] px-4 py-2.5",
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
              {m.role === "user" ? (
                <div className="whitespace-pre-wrap text-sm text-midground">
                  {m.content}
                </div>
              ) : (
                <Markdown content={m.content} streaming={m.streaming} />
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
      <footer className="relative z-20 shrink-0 border-t border-current/10 bg-background-base/75 px-4 py-3 backdrop-blur-sm sm:px-6">
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
              "max-h-40 min-h-[2.5rem] flex-1 resize-none rounded-[var(--radius)]",
              "border border-current/15 bg-midground/[0.04] px-3.5 py-2.5",
              "font-sans text-sm text-midground placeholder:text-text-tertiary",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/50",
              "disabled:cursor-not-allowed disabled:opacity-60",
            )}
          />
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
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={conn !== "open" || !input.trim()}
              aria-label="Send"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </form>
      </footer>
    </div>
  );
}
