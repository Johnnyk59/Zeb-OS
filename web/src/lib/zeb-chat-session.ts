export interface GatewayHistoryMessage {
  role?: string;
  text?: string;
  model?: string;
  provider?: string;
}

export interface GatewaySessionInfo {
  model?: string;
  provider?: string;
  running?: boolean;
}

export interface GatewaySessionPayload {
  session_id: string;
  stored_session_id?: string;
  session_key?: string;
  resumed?: string;
  messages?: GatewayHistoryMessage[];
  running?: boolean;
  status?: string;
  inflight?: {
    user?: string;
    assistant?: string;
    streaming?: boolean;
  } | null;
  info?: GatewaySessionInfo;
}

export interface RestoredChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  model?: string;
  provider?: string;
}

export function storedSessionId(payload: GatewaySessionPayload): string {
  return (
    payload.session_key ||
    payload.stored_session_id ||
    payload.resumed ||
    ""
  ).trim();
}

export function restoreChatMessages(
  payload: GatewaySessionPayload,
): RestoredChatMessage[] {
  const restored: RestoredChatMessage[] = [];
  for (const message of payload.messages ?? []) {
    if (message.role !== "user" && message.role !== "assistant") continue;
    const content = String(message.text ?? "");
    if (!content.trim()) continue;
    restored.push({
      role: message.role,
      content,
      ...(message.model ? { model: message.model } : {}),
      ...(message.provider ? { provider: message.provider } : {}),
    });
  }

  const inflight = payload.inflight;
  if (inflight?.user?.trim()) {
    const latestUser = [...restored].reverse().find((message) => message.role === "user");
    if (latestUser?.content !== inflight.user) {
      restored.push({ role: "user", content: inflight.user });
    }
  }
  if (inflight && (inflight.assistant || inflight.streaming)) {
    restored.push({
      role: "assistant",
      content: inflight.assistant ?? "",
      streaming: true,
    });
  }
  return restored;
}

export function chatSessionStorageKey(
  profile: string | null | undefined,
  pane: "primary" | "secondary",
): string {
  const scope = (profile || "default").trim() || "default";
  return `zeb.chat.session.${scope}.${pane}`;
}
