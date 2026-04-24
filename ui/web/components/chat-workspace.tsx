"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatRequestError, streamChat } from "@/lib/sse";
import type {
  MessageIn,
  Tier,
  ToolActivity,
  ToolCallEvent,
} from "@/lib/api";
import { extractPathway, type PathwayData } from "@/lib/pathway";
import { Header } from "./header";
import { MainPane } from "./main-pane";
import { EvidenceRail, type EvidenceRailHandle } from "./evidence-rail";
import { EvidenceDrawer } from "./evidence-drawer";
import type { InputAreaHandle } from "./input-area";
import type { ChatMessage, StreamingState } from "./message-list";

const STORAGE_KEY = "metaboagent.chat.v1";

function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function toMessageIn(messages: ChatMessage[]): MessageIn[] {
  return messages.map((m) => ({ role: m.role, content: m.content }));
}

/**
 * Persisted shape is just the prose — role, content, id, and the
 * stable-ish error/canceled markers. We deliberately drop toolCalls
 * (bulky, stale by the time a page reloads) and pathway/toolActivity
 * (session-only state). The user gets their message thread back; they
 * don't get every tool result frozen in amber, which would be noise.
 */
function loadMessages(): ChatMessage[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (m): m is ChatMessage =>
        !!m &&
        typeof m === "object" &&
        typeof (m as ChatMessage).id === "string" &&
        typeof (m as ChatMessage).content === "string" &&
        ((m as ChatMessage).role === "user" ||
          (m as ChatMessage).role === "assistant"),
    );
  } catch {
    return [];
  }
}

function saveMessages(messages: ChatMessage[]) {
  if (typeof window === "undefined") return;
  try {
    const persisted = messages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      error: m.error,
      canceled: m.canceled,
    }));
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  } catch {
    // quota exceeded / storage disabled — silently drop
  }
}

export function ChatWorkspace() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([]);
  const [pathway, setPathway] = useState<PathwayData | null>(null);
  const [deepMode, setDeepMode] = useState(false);

  // Hydrate message history from localStorage on mount.
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;
    const saved = loadMessages();
    if (saved.length > 0) setMessages(saved);
  }, []);

  // Persist message history on every change (after hydration).
  useEffect(() => {
    if (!hydratedRef.current) return;
    saveMessages(messages);
  }, [messages]);

  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<InputAreaHandle | null>(null);
  const railRef = useRef<EvidenceRailHandle | null>(null);

  const handleAbort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const runChat = useCallback(
    async (history: ChatMessage[], assistantId: string, tier: Tier) => {
      let accumulatedText = "";
      const accumulatedTools: ToolCallEvent[] = [];
      let errorMessage: string | null = null;
      let wasAborted = false;

      const ctrl = new AbortController();
      abortRef.current = ctrl;

      try {
        for await (const ev of streamChat(toMessageIn(history), {
          signal: ctrl.signal,
          tier,
        })) {
          switch (ev.type) {
            case "token":
              accumulatedText += ev.content;
              setStreaming((s) =>
                s && s.id === assistantId
                  ? { ...s, text: accumulatedText }
                  : s,
              );
              break;
            case "tool_call": {
              accumulatedTools.push(ev);
              setStreaming((s) =>
                s && s.id === assistantId
                  ? { ...s, toolCalls: [...accumulatedTools] }
                  : s,
              );
              const activity: ToolActivity = {
                id: ev.id,
                name: ev.name,
                args: ev.args,
                status: "running",
                startedAt: Date.now(),
              };
              setToolActivity((prev) => [activity, ...prev]);
              break;
            }
            case "tool_result":
              setToolActivity((prev) =>
                prev.map((a) =>
                  a.id === ev.id
                    ? {
                        ...a,
                        status: "done",
                        result: ev.content,
                        endedAt: Date.now(),
                      }
                    : a,
                ),
              );
              break;
            case "tool_error":
              setToolActivity((prev) =>
                prev.map((a) =>
                  a.id === ev.id
                    ? {
                        ...a,
                        status: "error",
                        error: ev.message,
                        endedAt: Date.now(),
                      }
                    : a,
                ),
              );
              break;
            case "final_answer": {
              if (
                ev.content &&
                ev.content.length > accumulatedText.length
              ) {
                accumulatedText = ev.content;
                setStreaming((s) =>
                  s && s.id === assistantId
                    ? { ...s, text: accumulatedText }
                    : s,
                );
              }
              // Try to extract a pathway from the final answer. Only
              // replace pathway state if we found at least one step —
              // otherwise we'd clobber a useful pathway from an earlier
              // turn with nothing.
              const extracted = extractPathway(
                accumulatedText,
                assistantId,
              );
              if (extracted.steps.length > 0) setPathway(extracted);
              break;
            }
            case "error":
              errorMessage = `${ev.where}: ${ev.message}`;
              break;
            case "done":
              break;
          }
        }
      } catch (err) {
        if ((err as Error)?.name === "AbortError") {
          wasAborted = true;
        } else if (err instanceof ChatRequestError) {
          errorMessage = err.message;
        } else {
          errorMessage =
            err instanceof Error ? err.message : "network error";
        }
      } finally {
        abortRef.current = null;
      }

      // Any tool calls still "running" mean we aborted or errored before
      // their result arrived — mark them as errored with a "canceled" note
      // so the rail doesn't keep spinners forever.
      if (wasAborted || errorMessage) {
        setToolActivity((prev) =>
          prev.map((a) =>
            a.status === "running"
              ? {
                  ...a,
                  status: "error",
                  error: wasAborted ? "canceled" : "stream ended",
                  endedAt: Date.now(),
                }
              : a,
          ),
        );
      }

      const finalMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: accumulatedText,
        toolCalls: accumulatedTools.length ? accumulatedTools : undefined,
        error: errorMessage ?? undefined,
        canceled: wasAborted || undefined,
      };

      setMessages((prev) => [...prev, finalMessage]);
      setStreaming(null);
      if (errorMessage) setLastError(errorMessage);
    },
    [],
  );

  const handleSubmit = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || streaming) return;

    const userMsg: ChatMessage = {
      id: newId(),
      role: "user",
      content: trimmed,
    };
    const assistantId = newId();
    const nextHistory = [...messages, userMsg];

    setMessages(nextHistory);
    setInput("");
    setLastError(null);
    setStreaming({ id: assistantId, text: "", toolCalls: [] });

    await runChat(nextHistory, assistantId, deepMode ? "deep" : "default");
  }, [input, messages, streaming, runChat, deepMode]);

  const handleRetry = useCallback(async () => {
    if (streaming || messages.length === 0) return;
    // Retry replays the history we already have (last message should be
    // the canceled/errored assistant turn; the agent re-runs from the
    // preceding user message).
    setLastError(null);
    const assistantId = newId();
    setStreaming({ id: assistantId, text: "", toolCalls: [] });
    await runChat(messages, assistantId, deepMode ? "deep" : "default");
  }, [messages, streaming, runChat, deepMode]);

  const fillInput = useCallback((prompt: string) => {
    setInput(prompt);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const handleToolCrumbClick = useCallback((id: string) => {
    railRef.current?.scrollToToolCall(id);
  }, []);

  const handleNewConversation = useCallback(() => {
    if (streaming) return;
    if (messages.length === 0) return;
    const confirmed = window.confirm(
      "Clear the current conversation? Message history will be deleted.",
    );
    if (!confirmed) return;
    setMessages([]);
    setToolActivity([]);
    setPathway(null);
    setLastError(null);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // ignore
      }
    }
  }, [messages.length, streaming]);

  return (
    <>
      <Header
        deepMode={deepMode}
        onDeepModeChange={setDeepMode}
        onNewConversation={handleNewConversation}
        canClearConversation={messages.length > 0 && !streaming}
      />
      <div className="flex h-[calc(100vh-56px)]">
        <MainPane
          messages={messages}
          streaming={streaming}
          input={input}
          onInputChange={setInput}
          onSubmit={handleSubmit}
          onAbort={handleAbort}
          onPickPrompt={fillInput}
          onRetry={handleRetry}
          lastError={lastError}
          inputRef={inputRef}
          onToolCrumbClick={handleToolCrumbClick}
        />
        <EvidenceRail
          ref={railRef}
          toolActivity={toolActivity}
          pathway={pathway}
        />
        <EvidenceDrawer toolActivity={toolActivity} pathway={pathway} />
      </div>
    </>
  );
}
