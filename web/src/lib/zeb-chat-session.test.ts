import { describe, expect, it } from "vitest";
import {
  chatSessionStorageKey,
  restoreChatMessages,
  storedSessionId,
} from "./zeb-chat-session";

describe("zeb chat session restoration", () => {
  it("prefers the durable session key over a live websocket id", () => {
    expect(
      storedSessionId({
        session_id: "live-1",
        session_key: "stored-1",
        stored_session_id: "stored-2",
      }),
    ).toBe("stored-1");
  });

  it("restores visible turns and an in-flight reply without internal rows", () => {
    expect(
      restoreChatMessages({
        session_id: "live-1",
        messages: [
          { role: "system", text: "private" },
          { role: "user", text: "hello" },
          { role: "tool", text: "hidden tool output" },
        ],
        inflight: { user: "keep going", assistant: "Working", streaming: true },
      }),
    ).toEqual([
      { role: "user", content: "hello" },
      { role: "user", content: "keep going" },
      { role: "assistant", content: "Working", streaming: true },
    ]);
  });

  it("isolates primary and secondary panes per profile", () => {
    expect(chatSessionStorageKey("work", "primary")).toBe(
      "zeb.chat.session.work.primary",
    );
    expect(chatSessionStorageKey("work", "secondary")).not.toBe(
      chatSessionStorageKey("work", "primary"),
    );
  });
});
