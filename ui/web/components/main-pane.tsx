"use client";

import { useCallback, useRef, useState } from "react";
import { ChatRequestError, streamChat } from "@/lib/sse";
import type { MessageIn, ToolCallEvent } from "@/lib/api";
import { InputArea, type InputAreaHandle } from "./input-area";
import {
  MessageList,
  type ChatMessage,
  type StreamingState,
} from "./message-list";
import { SuggestedPrompts } from "./suggested-prompts";

function newId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function toMessageIn(messages: ChatMessage[]): MessageIn[] {
  return messages.map((m) => ({ role: m.role, content: m.content }));
}

export function MainPane() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<InputAreaHandle | null>(null);

  const handleAbort = useCallback(() => {
    abortRef.current?.abort();
  }, []);

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

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    let accumulatedText = "";
    const accumulatedTools: ToolCallEvent[] = [];
    let errorMessage: string | null = null;
    let wasAborted = false;

    try {
      for await (const ev of streamChat(toMessageIn(nextHistory), {
        signal: ctrl.signal,
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
          case "tool_call":
            accumulatedTools.push(ev);
            setStreaming((s) =>
              s && s.id === assistantId
                ? { ...s, toolCalls: [...accumulatedTools] }
                : s,
            );
            break;
          case "tool_result":
          case "tool_error":
            // Keep the tool-call strip as-is for 5.2; results flow to
            // the evidence rail in 5.3.
            break;
          case "final_answer":
            // Prefer the final_answer's full content over the accumulated
            // token stream (they should match, but tokens can skip if the
            // server only emitted a final-answer blob).
            if (ev.content && ev.content.length > accumulatedText.length) {
              accumulatedText = ev.content;
              setStreaming((s) =>
                s && s.id === assistantId
                  ? { ...s, text: accumulatedText }
                  : s,
              );
            }
            break;
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
  }, [input, messages, streaming]);

  const fillInput = useCallback((prompt: string) => {
    setInput(prompt);
    // Defer focus so the textarea renders before we touch it.
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const isEmpty = messages.length === 0 && !streaming;

  return (
    <section
      className="flex min-w-0 flex-1 flex-col bg-white"
      aria-label="Chat"
    >
      <div className="flex-1 overflow-y-auto">
        {isEmpty ? (
          <SuggestedPrompts onPick={fillInput} />
        ) : (
          <MessageList messages={messages} streaming={streaming} />
        )}
      </div>

      {lastError && !streaming && (
        <div className="mx-auto w-full max-w-3xl px-6">
          <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            <span>{lastError}</span>
            <button
              type="button"
              onClick={() => {
                setLastError(null);
                handleSubmit();
              }}
              className="ml-3 rounded-md border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      <InputArea
        ref={inputRef}
        value={input}
        onChange={setInput}
        onSubmit={handleSubmit}
        onAbort={handleAbort}
        streaming={!!streaming}
      />
    </section>
  );
}

