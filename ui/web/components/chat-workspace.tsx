"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatRequestError, streamChat } from "@/lib/sse";
import type {
  Attachment,
  HealthResponse,
  MessageIn,
  Tier,
  ToolActivity,
  ToolCallEvent,
} from "@/lib/api";
import { extractPathway, type PathwayData } from "@/lib/pathway";
import {
  preprocessImage,
  MAX_FILE_BYTES,
} from "@/lib/image-preprocess";
import { MAX_ATTACHMENTS } from "./input-area";
import { Header } from "./header";
import { MainPane } from "./main-pane";
import { EvidenceRail, type EvidenceRailHandle } from "./evidence-rail";
import { EvidenceDrawer } from "./evidence-drawer";
import { DemoModeBanner } from "./demo-mode-banner";
import { ToastProvider, useToast } from "./toast";
import type { InputAreaHandle } from "./input-area";
import type { ChatMessage, StreamingState } from "./message-list";

const STORAGE_KEY = "metaboagent.chat.v1";

function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function toMessageIn(messages: ChatMessage[]): MessageIn[] {
  return messages.map((m) => {
    const base: MessageIn = { role: m.role, content: m.content };
    // Only forward attachments whose full-resolution bytes are still
    // present. After a localStorage restore data_base64 is null — those
    // messages ride along as text-only context.
    if (m.attachments && m.attachments.length > 0) {
      const live = m.attachments.filter(
        (a): a is Attachment & { data_base64: string } =>
          typeof a.data_base64 === "string" && a.data_base64.length > 0,
      );
      if (live.length > 0) base.attachments = live;
    }
    return base;
  });
}

/**
 * Persisted shape is the prose plus small thumbnail previews for any
 * attachments. We deliberately drop toolCalls (bulky, stale by the
 * time a page reloads) and pathway/toolActivity (session-only state),
 * and we null out attachment.data_base64 so a handful of full-resolution
 * images don't blow past the ~5 MB localStorage budget.
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
      attachments: m.attachments?.map((a) => ({
        kind: a.kind,
        mime_type: a.mime_type,
        filename: a.filename,
        // Drop the full-resolution payload on persistence; thumbnails
        // are enough for history rendering and fit inside localStorage.
        data_base64: null,
        thumbnail_base64: a.thumbnail_base64,
      })),
    }));
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
  } catch {
    // quota exceeded / storage disabled — silently drop
  }
}

export function ChatWorkspace() {
  return (
    <ToastProvider>
      <ChatWorkspaceInner />
    </ToastProvider>
  );
}

function ChatWorkspaceInner() {
  const toast = useToast();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([]);
  const [pathway, setPathway] = useState<PathwayData | null>(null);
  const [deepMode, setDeepMode] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<Attachment[]>([]);

  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;
    const saved = loadMessages();
    if (saved.length > 0) setMessages(saved);
  }, []);

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

  const handleSelectFiles = useCallback(
    async (files: File[]) => {
      const current = pendingAttachments.length;
      const remaining = MAX_ATTACHMENTS - current;
      if (remaining <= 0) {
        toast.push(
          `Already at the ${MAX_ATTACHMENTS}-image limit for this message.`,
          "info",
        );
        return;
      }
      const overflow = files.length > remaining;
      const take = overflow ? files.slice(0, remaining) : files;
      if (overflow) {
        toast.push(
          `Attached first ${remaining}; 5.6 limits ${MAX_ATTACHMENTS} per message.`,
          "info",
        );
      }

      const results = await Promise.all(take.map((f) => preprocessImage(f)));
      const accepted: Attachment[] = [];
      results.forEach((r, i) => {
        if (r.ok) {
          accepted.push({
            kind: "image",
            mime_type: r.image.mime_type,
            filename: r.image.filename,
            data_base64: r.image.data_base64,
            thumbnail_base64: r.image.thumbnail_base64,
          });
        } else {
          toast.push(`${take[i].name}: ${r.reason}`);
        }
      });
      if (accepted.length > 0) {
        setPendingAttachments((prev) => [...prev, ...accepted]);
      }
    },
    [pendingAttachments.length, toast],
  );

  const handleRemoveAttachment = useCallback((index: number) => {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
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
    const attachments = pendingAttachments;
    if ((!trimmed && attachments.length === 0) || streaming) return;

    const userMsg: ChatMessage = {
      id: newId(),
      role: "user",
      content: trimmed,
      attachments: attachments.length > 0 ? attachments : undefined,
    };
    const assistantId = newId();
    const nextHistory = [...messages, userMsg];

    setMessages(nextHistory);
    setInput("");
    setPendingAttachments([]);
    setLastError(null);
    setStreaming({ id: assistantId, text: "", toolCalls: [] });

    await runChat(nextHistory, assistantId, deepMode ? "deep" : "default");
  }, [input, messages, pendingAttachments, streaming, runChat, deepMode]);

  const handleRetry = useCallback(async () => {
    if (streaming || messages.length === 0) return;
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

  const handleHealth = useCallback((h: HealthResponse | null) => {
    setDemoMode(h?.demo_mode === true);
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
    setPendingAttachments([]);
    if (typeof window !== "undefined") {
      try {
        window.localStorage.removeItem(STORAGE_KEY);
      } catch {
        // ignore
      }
    }
  }, [messages.length, streaming]);

  return (
    <div className="flex h-screen flex-col">
      <Header
        deepMode={deepMode}
        onDeepModeChange={setDeepMode}
        onNewConversation={handleNewConversation}
        canClearConversation={messages.length > 0 && !streaming}
        streaming={!!streaming}
        onHealth={handleHealth}
      />
      <DemoModeBanner visible={demoMode} />
      <div className="flex min-h-0 flex-1">
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
          attachments={pendingAttachments}
          onSelectFiles={handleSelectFiles}
          onRemoveAttachment={handleRemoveAttachment}
        />
        <EvidenceRail
          ref={railRef}
          toolActivity={toolActivity}
          pathway={pathway}
        />
        <EvidenceDrawer toolActivity={toolActivity} pathway={pathway} />
      </div>
    </div>
  );
}

// Re-export for modules that only want the raw limit constant.
export { MAX_FILE_BYTES };
