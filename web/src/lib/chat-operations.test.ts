import { describe, expect, it } from "vitest";
import {
  gatewayModelSwitchValue,
  mergeModelIdentity,
  modelIdentityLabel,
  reduceLiveTasks,
} from "./chat-operations";

describe("chat operations", () => {
  it("builds a session-scoped model switch command", () => {
    expect(gatewayModelSwitchValue("anthropic", "claude-sonnet-4.6")).toBe(
      "claude-sonnet-4.6 --provider anthropic",
    );
  });

  it("merges and formats the actual gateway model identity", () => {
    const identity = mergeModelIdentity(
      { model: "claude-sonnet-4.6" },
      { provider: "anthropic", model: "old" },
    );
    expect(identity).toEqual({ provider: "anthropic", model: "claude-sonnet-4.6" });
    expect(modelIdentityLabel(identity)).toBe("anthropic/claude-sonnet-4.6");
    expect(
      modelIdentityLabel({ provider: "openrouter", model: "openrouter/auto" }),
    ).toBe("openrouter/auto");
  });

  it("tracks tools and removes them only on matching completion", () => {
    const started = reduceLiveTasks(
      [],
      "tool.start",
      { tool_id: "t1", name: "web_search", context: "Zeb OS" },
      100,
    );
    expect(started).toEqual([
      {
        id: "tool:t1",
        title: "web search",
        detail: "Zeb OS",
        progress: undefined,
        eta: undefined,
        startedAt: 100,
      },
    ]);
    expect(reduceLiveTasks(started, "tool.complete", { tool_id: "t2" })).toEqual(
      started,
    );
    expect(reduceLiveTasks(started, "tool.complete", { tool_id: "t1" })).toEqual(
      [],
    );
  });

  it("associates id-less progress with the matching running tool", () => {
    const started = reduceLiveTasks([], "tool.start", {
      tool_id: "t1",
      name: "web_search",
    });
    const progressed = reduceLiveTasks(started, "tool.progress", {
      name: "web_search",
      preview: "Reading results",
    });
    expect(progressed).toHaveLength(1);
    expect(progressed[0]).toMatchObject({ id: "tool:t1", detail: "Reading results" });
  });

  it("shows progress and ETA only when the event provides evidence", () => {
    const tasks = reduceLiveTasks(
      [],
      "subagent.start",
      {
        subagent_id: "a1",
        goal: "Run verification",
        task_index: 1,
        task_count: 4,
        eta_seconds: 90,
      },
      200,
    );
    expect(tasks[0]).toMatchObject({ progress: 25, eta: "~2m" });

    const noEstimate = reduceLiveTasks([], "tool.start", {
      tool_id: "t1",
      name: "terminal",
    });
    expect(noEstimate[0].progress).toBeUndefined();
    expect(noEstimate[0].eta).toBeUndefined();
  });
});
