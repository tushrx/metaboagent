"use client";

import { ArrowDown } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ChatMessage, StreamingState } from "./message-list";
import { MessageList } from "./message-list";
import { InputArea, type InputAreaHandle } from "./input-area";
import { SuggestedPrompts } from "./suggested-prompts";
import type { Ref } from "react";

const BOTTOM_THRESHOLD_PX = 40;

interface Props {
  messages: ChatMessage[];
  streaming: StreamingState | null;
  input: string;
  onInputChange: (next: string) => void;
  onSubmit: () => void;
  onAbort: () => void;
  onPickPrompt: (prompt: string) => void;
  onRetry: () => void;
  lastError: string | null;
  inputRef: Ref<InputAreaHandle>;
  onToolCrumbClick?: (toolCallId: string) => void;
}

export function MainPane({
  messages,
  streaming,
  input,
  onInputChange,
  onSubmit,
  onAbort,
  onPickPrompt,
  onRetry,
  lastError,
  inputRef,
  onToolCrumbClick,
}: Props) {
  const isEmpty = messages.length === 0 && !streaming;

  const scrollRef = useRef<HTMLDivElement>(null);
  // atBottom tracks whether the user is within BOTTOM_THRESHOLD_PX of
  // the bottom. While true, we auto-scroll on new content. While false,
  // we pause auto-scroll and show a "Jump to latest" button.
  const [atBottom, setAtBottom] = useState(true);

  const scrollToBottom = useCallback((smooth = true) => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
  }, []);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight;
    setAtBottom(distanceFromBottom <= BOTTOM_THRESHOLD_PX);
  }, []);

  // Auto-scroll when new messages or streaming content arrives — but
  // only if the user hasn't scrolled up.
  useEffect(() => {
    if (atBottom) scrollToBottom();
    // Fire also when tool crumbs tick — preserves stream-time UX.
  }, [
    atBottom,
    messages.length,
    streaming?.text.length,
    streaming?.toolCalls.length,
    scrollToBottom,
  ]);

  const showJumpButton = !atBottom && !isEmpty;

  return (
    <section
      className="relative flex min-w-0 flex-1 flex-col bg-white"
      aria-label="Chat"
    >
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {isEmpty ? (
          <SuggestedPrompts onPick={onPickPrompt} />
        ) : (
          <MessageList
            messages={messages}
            streaming={streaming}
            onToolCrumbClick={onToolCrumbClick}
          />
        )}
      </div>

      {showJumpButton && (
        <button
          type="button"
          onClick={() => {
            scrollToBottom();
            setAtBottom(true);
          }}
          aria-label="Jump to latest message"
          className="absolute bottom-[88px] right-5 z-10 flex items-center gap-1.5 rounded-full border border-gray-200 bg-white/95 px-3 py-1.5 text-[12px] font-medium text-gray-700 shadow-md backdrop-blur transition-colors hover:border-blue-300 hover:text-blue-700"
        >
          <ArrowDown size={12} />
          Jump to latest
        </button>
      )}

      {lastError && !streaming && (
        <div className="mx-auto w-full max-w-3xl px-6">
          <div className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            <span>{lastError}</span>
            <button
              type="button"
              onClick={onRetry}
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
        onChange={onInputChange}
        onSubmit={onSubmit}
        onAbort={onAbort}
        streaming={!!streaming}
      />
    </section>
  );
}
