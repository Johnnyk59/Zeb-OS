export interface ModelIdentity {
  model?: string;
  provider?: string;
}

export interface LiveTask {
  id: string;
  title: string;
  detail?: string;
  progress?: number;
  eta?: string;
  startedAt: number;
}

interface AgentDashboardLocation {
  origin: string;
  basePath?: string;
  pageHostname: string;
}

type EventPayload = Record<string, unknown>;

const text = (value: unknown): string =>
  typeof value === "string" ? value.trim() : "";

const finiteNumber = (value: unknown): number | undefined => {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

export function resolveAgentDashboardUrl(
  raw: string,
  location: AgentDashboardLocation,
): string {
  const value = String(raw || "").trim();
  if (!value) return "";
  const basePath = String(location.basePath || "").replace(/\/+$/, "");
  if (value.startsWith("//") || value.includes("\\")) return "";
  if (value.startsWith("/")) {
    if (!basePath || value === basePath || value.startsWith(`${basePath}/`)) {
      return value;
    }
    return `${basePath}${value}`;
  }
  if (!/^[a-z][a-z0-9+.-]*:/i.test(value)) return "";

  try {
    const url = new URL(value, location.origin);
    if (url.protocol === "https:") return url.href;
    const localHosts = ["localhost", "127.0.0.1", "::1"];
    const localDevelopment = localHosts.includes(url.hostname);
    const localDashboard = localHosts.includes(location.pageHostname);
    return url.protocol === "http:" && localDevelopment && localDashboard ? url.href : "";
  } catch {
    return "";
  }
}

export function mergeModelIdentity(
  payload: unknown,
  fallback: ModelIdentity = {},
): ModelIdentity {
  if (!payload || typeof payload !== "object") return fallback;
  const candidate = payload as EventPayload;
  const model = text(candidate.model) || fallback.model;
  const provider = text(candidate.provider) || fallback.provider;
  return { model, provider };
}

export function modelIdentityLabel(identity: ModelIdentity): string {
  const model = text(identity.model);
  const provider = text(identity.provider);
  if (!model) return provider;
  if (!provider || model.toLowerCase().startsWith(`${provider.toLowerCase()}/`)) {
    return model;
  }
  return `${provider}/${model}`;
}

export function gatewayModelSwitchValue(provider: string, model: string): string {
  return `${model.trim()} --provider ${provider.trim()}`;
}

function taskProgress(payload: EventPayload): number | undefined {
  const direct = finiteNumber(payload.progress ?? payload.percent);
  if (direct !== undefined) {
    return Math.max(0, Math.min(100, direct <= 1 ? direct * 100 : direct));
  }

  const index = finiteNumber(payload.task_index);
  const count = finiteNumber(payload.task_count);
  if (index !== undefined && count !== undefined && count > 0) {
    return Math.max(0, Math.min(100, (index / count) * 100));
  }
  return undefined;
}

function taskEta(payload: EventPayload): string | undefined {
  const explicit = text(payload.eta);
  if (explicit) return explicit;
  const seconds = finiteNumber(payload.eta_seconds);
  if (seconds === undefined || seconds < 0) return undefined;
  if (seconds < 60) return `~${Math.ceil(seconds)}s`;
  return `~${Math.ceil(seconds / 60)}m`;
}

function upsertTask(tasks: LiveTask[], task: LiveTask): LiveTask[] {
  const index = tasks.findIndex((candidate) => candidate.id === task.id);
  if (index < 0) return [...tasks, task];
  const next = [...tasks];
  next[index] = { ...tasks[index], ...task, startedAt: tasks[index].startedAt };
  return next;
}

function removeTask(tasks: LiveTask[], id: string): LiveTask[] {
  return tasks.filter((task) => task.id !== id);
}

function toolTaskId(payload: EventPayload): string {
  return `tool:${text(payload.tool_id) || text(payload.name) || "active"}`;
}

function subagentTaskId(payload: EventPayload): string {
  const taskIndex = finiteNumber(payload.task_index);
  return `agent:${
    text(payload.subagent_id) ||
    text(payload.child_session_id) ||
    (taskIndex !== undefined ? String(taskIndex) : "") ||
    "active"
  }`;
}

function taskDetail(payload: EventPayload): string | undefined {
  return (
    text(payload.text) ||
    text(payload.preview) ||
    text(payload.context) ||
    text(payload.summary) ||
    undefined
  );
}

/** Reduce only task evidence emitted by the live gateway. */
export function reduceLiveTasks(
  tasks: LiveTask[],
  eventType: string,
  rawPayload: unknown,
  now = Date.now(),
): LiveTask[] {
  const payload =
    rawPayload && typeof rawPayload === "object"
      ? (rawPayload as EventPayload)
      : {};

  if (eventType === "tool.start" || eventType === "tool.generating") {
    const name = text(payload.name) || "Tool";
    const id = toolTaskId(payload);
    const nextTasks = text(payload.tool_id)
      ? removeTask(tasks, `tool:${name}`)
      : tasks;
    return upsertTask(nextTasks, {
      id,
      title: name.replaceAll("_", " "),
      detail: taskDetail(payload),
      progress: taskProgress(payload),
      eta: taskEta(payload),
      startedAt: now,
    });
  }

  if (eventType === "tool.progress") {
    const name = text(payload.name);
    const requestedId = toolTaskId(payload);
    const existing =
      tasks.find((task) => task.id === requestedId) ||
      (!text(payload.tool_id) && name
        ? [...tasks]
            .reverse()
            .find((task) => task.title === name.replaceAll("_", " "))
        : undefined);
    const id = existing?.id || requestedId;
    return upsertTask(tasks, {
      id,
      title: existing?.title || (text(payload.name) || "Tool").replaceAll("_", " "),
      detail: taskDetail(payload) || existing?.detail,
      progress: taskProgress(payload) ?? existing?.progress,
      eta: taskEta(payload) ?? existing?.eta,
      startedAt: existing?.startedAt ?? now,
    });
  }

  if (eventType === "tool.complete") {
    const name = text(payload.name);
    const title = name.replaceAll("_", " ");
    return tasks.filter(
      (task) =>
        task.id !== toolTaskId(payload) &&
        task.id !== `tool:${name}` &&
        (!title || task.title !== title),
    );
  }

  if (eventType === "subagent.start" || eventType === "subagent.progress") {
    const id = subagentTaskId(payload);
    const existing = tasks.find((task) => task.id === id);
    const count = finiteNumber(payload.task_count);
    const index = finiteNumber(payload.task_index);
    const ordinal =
      count !== undefined && index !== undefined
        ? `Task ${Math.min(index + 1, count)} of ${count}`
        : undefined;
    return upsertTask(tasks, {
      id,
      title: text(payload.goal) || existing?.title || "Delegated task",
      detail: taskDetail(payload) || ordinal || existing?.detail,
      progress: taskProgress(payload) ?? existing?.progress,
      eta: taskEta(payload) ?? existing?.eta,
      startedAt: existing?.startedAt ?? now,
    });
  }

  if (eventType === "subagent.complete") {
    return removeTask(tasks, subagentTaskId(payload));
  }

  if (eventType === "status.update") {
    const kind = text(payload.kind) || "status";
    const detail = text(payload.text);
    const id = `status:${kind}`;
    if (!detail || /^(ready|idle|complete|completed)$/i.test(detail)) {
      return removeTask(tasks, id);
    }
    return upsertTask(tasks, {
      id,
      title: kind.replaceAll("_", " "),
      detail,
      progress: taskProgress(payload),
      eta: taskEta(payload),
      startedAt: now,
    });
  }

  return tasks;
}
